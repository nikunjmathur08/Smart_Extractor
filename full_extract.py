import re
import asyncio
import json
import subprocess
import urllib.parse
from crawl4ai import *
from typing import List, Dict, Optional
import pandas as pd
import requests
from more_itertools import chunked

SITE_URL_BUILDERS = {
    "amazon": lambda query: f"https://www.amazon.in/s?k={urllib.parse.quote_plus(query)}",
    "flipkart": lambda query: f"https://www.flipkart.com/search?q={urllib.parse.quote(query, safe='')}",
    "croma": lambda query: f"https://www.croma.com/searchB?q={urllib.parse.quote(query, safe='')}%3Arelevance&text={urllib.parse.quote(query, safe='')}",
    "tatacliq": lambda query: f"https://www.tatacliq.com/search/?searchCategory={urllib.parse.quote_plus(query)}",
    "duckduckgo": lambda query: f"https://duckduckgo.com/?q={urllib.parse.quote_plus(query)}",
}

DEFAULT_SITE = "duckduckgo"

def ask_ollama (model: str, prompt: str, stream=False) -> str:
    url = "http://localhost:11434/api/generate"
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": stream
    }

    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()

    if stream:
        output = ""
        for line in response.iter_lines():
            if line:
                chunk = json.loads(line.decode("utf-8"))
                output += chunk.get("response", "")
        return output
    else:
        return response.json().get("response", "")

def extract_detailed_product_info(blocks: List[str], chunk_size: int = 10) -> List[Dict]:
    extracted = []
    chunks = dynamic_chunk(blocks)

    for idx, chunk in enumerate(chunks, 1):
        joined = "\n\n---\n\n".join(chunk)
        print(joined)
        prompt = f"""
            Now extract from these blocks:
            {joined}
        """
        try:
            response_text = ask_ollama("extract-details", prompt)
            response_text = response_text.strip()
            if response_text.startswith('[') and response_text.endswith(']'):
                batch_data = json.loads(response_text)
                extracted.extend(batch_data)
            else:
                json_match = re.search(r'\[\s*\{[\s\S]*?\}\s*\]', response_text)
                if json_match:
                    batch_data = json.loads(json_match.group(0))
                    extracted.extend(batch_data)
                else:
                    print(f"No valid JSON array returned for chunk #{idx}")
        except Exception as e:
            print(f"⚠️ Failed to extract batch #{idx}: {e}")
    return extracted

def dynamic_chunk(blocks, max_chars = 12000):
    chunks = []
    current_chunk = []
    current_len = 0
    for block in blocks:
        block_len = len(block)
        if current_len + block_len + len("\n\n---\n\n") > max_chars:
            chunks.append(current_chunk)
            current_chunk = [block]
            current_len = block_len
        else:
            current_chunk.append(block)
            current_len += block_len + len("\n\n---\n\n")
    if current_chunk:
        chunks.append(current_chunk)
    return chunks

def extract_search_terms(structured_query):
    """Extract clean search terms from structured query"""
    product_type = structured_query.get('product_type', '')
    additional_filters = structured_query.get('additional_filters', [])
    
    search_terms = [product_type] if product_type else []
    
    # Handle additional_filters properly - check if it's a list of dicts or strings
    if isinstance(additional_filters, list):
        for filter_item in additional_filters:
            if isinstance(filter_item, dict):
                # Extract values from dict format
                values = filter_item.get('values', [])
                if isinstance(values, list):
                    search_terms.extend(v for v in values if v not in ['premium', 'budget', 'cheap', 'expensive'])
            elif isinstance(filter_item, str):
                if filter_item not in ['premium', 'budget', 'cheap', 'expensive']:
                    search_terms.append(filter_item)
    
    if not search_terms:
        original = structured_query.get('query', '')
        cleaned = re.sub(r'\b(on|from)\s+(amazon|flipkart|croma|tatacliq)\b', '', original, flags=re.IGNORECASE)
        cleaned = re.sub(r'\b(under|below|above|over)\s+\d+\b', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\b(₹|rs\.?|inr)\s*\d+\b', '', cleaned, flags=re.IGNORECASE)
        search_terms.append(cleaned.strip())
    
    return ' '.join(search_terms).strip()

def create_fallback_query(user_input: str) -> Dict:
    """Create a fallback structured query when LLM fails"""
    # Basic extraction of product type and price from user input
    price_match = re.search(r'(?:under|below|max|maximum)\s*(?:₹|rs\.?|inr)?\s*(\d+(?:,\d+)*)', user_input, re.IGNORECASE)
    max_price = int(price_match.group(1).replace(',', '')) if price_match else 999999
    
    # Extract site preference
    site_match = re.search(r'\b(amazon|flipkart|croma|tatacliq)\b', user_input, re.IGNORECASE)
    site = site_match.group(1).lower() if site_match else DEFAULT_SITE
    
    # Clean the query
    cleaned_query = sanitize_query(user_input)
    
    return {
        "site": site,
        "product_type": "electronics",  # default category
        "min_price": 0,
        "max_price": max_price,
        "sort_order": None,
        "additional_filters": [],
        "goal": f"search for {cleaned_query}",
        "query": cleaned_query
    }

def query_llama(user_input: str) -> Optional[Dict]:
    """Uses Ollama to extract structured info with robust JSON parsing"""
    try:
        response_text = ask_ollama("query-llama", user_input)
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if not json_match:
            print("⚠️ LLM didn't return valid JSON, creating fallback query...")
            return create_fallback_query(user_input)
            
        result = json.loads(json_match.group(0))

        if result.get('max_price') is None:
            result['max_price'] = 999999
        
        # Ensure query field exists
        if 'query' not in result:
            result['query'] = sanitize_query(user_input)
            
        return result
    except (json.JSONDecodeError, ValueError, subprocess.TimeoutExpired) as e:
        print(f"⚠️ LLM processing error: {str(e)}, creating fallback query...")
        return create_fallback_query(user_input)
    except FileNotFoundError:
        print("⚠️ Ollama not found, creating fallback query...")
        return create_fallback_query(user_input)

def ask_follow_up_questions(user_input: str, structured_query: Dict) -> List[str]:
    """Ask follow-up questions based on the input using LLM"""
    prompt = f"""
    **User Input**: {user_input}
    **Structured Query**: {json.dumps(structured_query, indent=2)}
    """
    try:
        response_text = ask_ollama("follow-ups", prompt)
        json_match = re.search(r'\[[\s\S]*\]', response_text)
        return json.loads(json_match.group(0)) if json_match else []
    except Exception as e:
        print(f"⚠️ Could not generate questions: {str(e)}")
        return []
    
def refine_structured_query_with_answers(original_input: str, answers: List[str], previous_query: Dict) -> Dict:
    """Regenerate final structured query after follow-up answers."""
    prompt = f"""
        **Original Input**: {original_input}

        **Previous Structured Query**:
        {json.dumps(previous_query, indent=2)}

        **Follow-up Answers**:
        {json.dumps(answers, indent=2)}

        Output only the updated structured query as JSON:
    """
    try:
        response_text = ask_ollama("refine-query", prompt)
        json_match = re.search(r'\{[\s\S]*\}', response_text)

        result = json.loads(json_match.group(0)) if json_match else previous_query

        if result.get('max_price') is None:
            result['max_price'] = 999999

        # Ensure query field exists
        if 'query' not in result:
            result['query'] = sanitize_query(original_input)

        return result
    except Exception as e:
        print(f"⚠️ Failed to refine structured query: {e}")
        return previous_query

def build_source_url(site_key: str, query: str) -> str:
    builder = SITE_URL_BUILDERS.get(site_key.lower(), SITE_URL_BUILDERS[DEFAULT_SITE])
    url = builder(query)
    print(f"Generated URL: {url}")
    return url

def generate_paginated_urls(base_url: str, site_key: str, pages: int = 5) -> List[str]:
    urls = [base_url]

    for i in range(2, pages + 1):
        if site_key == "amazon":
            urls.append(f"{base_url}&page={i}")
        elif site_key == "flipkart":
            urls.append(f"{base_url}&page={i}")
        elif site_key == "croma":
            urls.append(f"{base_url}&page={i}")
        elif site_key == "duckduckgo":
            urls.append(f"{base_url}&start={(i - 1) * 30}")
        else:
            break
    
    return urls

async def run_crawl4ai_scraper(structured: Dict) -> List[Dict]:
    """Main scraping function with proper error handling"""
    if not structured:
        print("❌ No structured query provided")
        return []
    
    site_key = structured.get("site", DEFAULT_SITE)
    if site_key is None:
        site_key = DEFAULT_SITE
    
    site_key = site_key.lower()
    
    query = structured.get('query', '')
    if not query:
        print("❌ No query found in structured data")
        return []
    
    source_url = build_source_url(site_key, query)
    paginated_urls = generate_paginated_urls(source_url, site_key, pages=3)  # Reduced pages for testing
    
    browser_conf = BrowserConfig(
        headless=False,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    )
    
    run_conf = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        wait_for_images=True,
        magic=True,
        simulate_user=True,
        override_navigator=True,
        scan_full_page=True,
        delay_before_return_html=7,
        js_code=[
            "window.scrollTo(0, document.body.scrollHeight/2);",
            "await new Promise(resolve => setTimeout(resolve, 3000));"
        ]
    )

    all_products = []

    try:
        async with AsyncWebCrawler(config=browser_conf) as crawler:
            for i, url in enumerate(paginated_urls, start=1):
                print(f"🔍 Scraping page {i}: {url}")
                result = await crawler.arun(url=url, config=run_conf)
            
                if not result.success:
                    print(f"❌ Failed to scrape page {i}: {result.error_message}")
                    continue

                # Split markdown into potential product blocks
                product_blocks = split_markdown_to_product_blocks(result.markdown)
                
                # Extract detailed info using LLM for each block
                detailed_products = extract_detailed_product_info(product_blocks)
                page_products = []
                for product in detailed_products:
                    if product and product.get('title') and product.get('price') is not None:
                        price = product['price']
                        min_price = structured.get('min_price', 0)
                        max_price = structured.get('max_price', 999999)
                        if min_price <= price <= max_price:
                            page_products.append(product)

                all_products.extend(page_products)
                print(f"✅ Found {len(page_products)} products on page {i}")

                await asyncio.sleep(2)
                
        print(f"🎉 Total products found: {len(all_products)}")
        return all_products
    except Exception as e:
        print(f"⚠️ Scraping error: {str(e)}")
        return []
    
async def url_scraper(url: str, min_price: int = 0, max_price: int = 999999) -> List[Dict]:
    """Scrape a single URL"""
    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        wait_for_images=True,
        magic=True,
        simulate_user=True,
        override_navigator=True,
        scan_full_page=True,
        delay_before_return_html=7,
        js_code=[
            "window.scrollTo(0, document.body.scrollHeight/2);",
            "await new Promise(resolve => setTimeout(resolve, 3000));"
        ]
    )
    browser_conf = BrowserConfig(
        headless=False,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    )

    try:
        async with AsyncWebCrawler(config=browser_conf) as crawler:
            result = await crawler.arun(url, config=config)  

            if not result.success:
                print(f"❌ Failed to scrape: {result.error_message}")
                return []
            
            # Split markdown into potential product blocks
            product_blocks = split_markdown_to_product_blocks(result.markdown)
            
            # Extract detailed info using LLM for each block
            detailed_products = extract_detailed_product_info(product_blocks)
            products = []
            for product in detailed_products:
                if product and product.get('title') and product.get('price') is not None:
                    price = product['price']
                    if min_price <= price <= max_price:
                        products.append(product)

            if products:
                print(f"✅ Found {len(products)} product(s):\n")
                display_results(products)
            else:
                print("⚠️ No product-style data found.")
                print("📄 Here's the markdown of the scraped content:\n")
                cleaned_text = clean_markdown_to_text(result.markdown)
                print(cleaned_text[:4000] + "..." if len(cleaned_text) > 2000 else cleaned_text)

        return products
    except Exception as e:
        print(f"❌ Scraping error: {str(e)}")
        return []

def split_markdown_to_product_blocks(markdown: str) -> List[str]:
    """Split markdown into potential product blocks using common patterns"""
    # Improved split on headings, bold items, or price lines
    blocks = re.split(r'(?m)^(?:#+\s.*?$|\*\*.*?\*\*|\d+\.\s.*?$|₹[\d,]+|Rs\.[\d,]+)', markdown)
    return [b.strip() for b in blocks if b.strip() and len(b) > 20]  # Filter short/irrelevant blocks

def clean_markdown_to_text(markdown: str) -> str:
    """Clean markdown and convert to readable text"""
    markdown = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', markdown)  # keep link text only
    markdown = re.sub(r'\*\*(.*?)\*\*', r'\1', markdown)  # bold
    markdown = re.sub(r'#+ ', '', markdown)  # headings
    markdown = re.sub(r'\s{2,}', ' ', markdown)  # excess whitespace
    return markdown.strip()

def sanitize_query(text: str) -> str:
    """Clean and sanitize search query"""
    text = re.sub(r'(under|above|over|below)\s+₹?\s*[\d,]+', '', text, flags=re.I)
    text = re.sub(r'\b(at|on|from)\s+(amazon|flipkart|croma|tatacliq)\b', '', text, flags=re.I)
    text = re.sub(r'₹|rs\.?|inr', '', text, flags=re.I)
    return re.sub(r'\s+', ' ', text).strip()

def display_results(products: List[Dict]) -> None:
    """Display scraped products in a formatted way"""
    if not products:
        print("📭 No products to display")
        return
    
    print(f"\n🛍️ Found {len(products)} products:")
    print("=" * 80)

    for i, item in enumerate(products, 1):
        print(f"\n{i}. 🛒 {item.get('title', 'No title')}")
        print(f"   💰 Price: ₹{item.get('price'):,}" if item.get('price') else "   💰 Price: Not available")
        print(f"   ⭐ Rating: {item.get('rating', 'N/A')}")
        print(f"   🏷️ Tags: {', '.join(item.get('tags') or [])}")
        print(f"   🎁 Offers: {item.get('offers', 'N/A')}")
        print(f"   🔻 Discounts: {item.get('discounts', 'N/A')}")
        print(f"   📦 Quantity: {item.get('quantity', 'N/A')}")
        print(f"   🔖 Category Properties:")
        for k, v in (item.get('category_properties') or {}).items():
            print(f"      - {k}: {v}")
        print("-" * 80)

def save_to_dataframe(products: List[Dict], filename: str = "scraped_products.csv") -> None:
    """Save products to a CSV file using pandas"""
    if not products:
        print("📭 No products to save")
        return
        
    try:
        df = pd.DataFrame(products)
        df.to_csv(filename, index=False)
        print(f"💾 Results saved to {filename}")
    except Exception as e:
        print(f"❌ Error saving to CSV: {str(e)}")

def save_to_excel(products: List[Dict], filename: str = "scraped_products.xlsx") -> None:
    """Save products to an Excel file using Pandas"""
    if not products:
        print("📭 No products to save")
        return
    if ".xlsx" not in filename:
        filename = filename + ".xlsx"
    
    try:
        df = pd.DataFrame(products)
        df.to_excel(filename, index=False)
        print(f"💾 Results saved to {filename}")
    except Exception as e:
        print(f"❌ Error saving to Excel: {str(e)}")

def main():
    """Main function with improved error handling"""
    print("🛒 Smart Product Scraper")
    print("=" * 50)
    
    while True:
        print("\n🔍 What would you like to scrape? (or type 'exit')")
        print("1. Simple URL scraping")
        print("2. Intelligent prompt-based scraping")
        
        user_input = input("\n→ Choose option (1/2) or 'exit': ").strip()
        
        if user_input.lower() == 'exit':
            print("👋 Goodbye!")
            break

        elif user_input == '1':
            url = input("\n🌐 Enter the URL to scrape: ").strip()
            if not url:
                print("❌ No URL provided")
                continue
                
            print(f"🔍 Scraping: {url}")
            products = asyncio.run(url_scraper(url))
            
            if products:
                save_option = input("\n💾 Save results to CSV? (y/n): ").strip().lower()
                if save_option == 'y':
                    save_to_dataframe(products)
            
        elif user_input == '2':
            user_prompt = input("\n🗣️ Enter your product search prompt: ").strip()
            if not user_prompt:
                print("❌ No prompt provided")
                continue

            print("🤖 Processing your request...")
            structured = query_llama(user_prompt)
            
            if not structured:
                print("❌ Could not parse your query. Please try again.")
                continue

            print("✅ Query parsed successfully!")
            
            questions = ask_follow_up_questions(user_prompt, structured)
            if questions:
                print("\n🤖 I have a few questions to refine your search:")
                user_answers = []
                for q in questions:
                    ans = input(f"→ {q} ").strip()
                    user_answers.append(ans)
                structured = refine_structured_query_with_answers(user_prompt, user_answers, structured)
                print("✅ Query refined with your answers!")

            structured["query"] = sanitize_query(structured.get("query", user_prompt))

            print("\n📋 Final Search Configuration:")
            print(json.dumps(structured, indent=2))

            print("\n🚀 Starting scraping process...")
            results = asyncio.run(run_crawl4ai_scraper(structured))
            
            if not results:
                print("\n⚠️ No products found matching your criteria.")
                continue

            display_results(results)
            
            save_option = input("\n💾 Save results? (csv/xlsx/none): ").strip().lower()
            if save_option == 'csv':
                filename = input("\n What would you like to name the file? ").strip().lower()
                save_to_dataframe(results, filename)
            elif save_option == 'xlsx':
                filename = input("\n What would you like to name the file? ").strip().lower()
                save_to_excel(results, filename)
        else:
            print("❌ Invalid option. Please choose 1 or 2.")

if __name__ == "__main__":
    main()