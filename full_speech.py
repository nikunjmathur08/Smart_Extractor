import re
import asyncio
import json
import subprocess
import urllib.parse
from crawl4ai import *
from typing import List, Dict, Optional
import urllib.parse
import pandas as pd
import requests
import speech_recognition as sr

def speak(text):
    subprocess.run(['say', '-v', 'Samantha', text])

def get_voice_input(prompt="🎤 Please speak your query: ") -> str:
    recognizer = sr.Recognizer()
    mic = sr.Microphone()

    speak(prompt)
    print("🎤 Listening...")

    with mic as source:
        recognizer.adjust_for_ambient_noise(source)
        audio = recognizer.listen(source)
    
    try:
        query = recognizer.recognize_google(audio)
        print(f"You said: {query}")
        return query
    except sr.UnknownValueError:
        print("Could not understand audio.")
        speak("Could not understand audio.")
        return ""
    except sr.RequestError as e:
        print(f"Could not request results; {e}")
        speak("Sorry I am having trouble reaching the speech service.")
        return ""

def listen(prompt: str = None) -> str:
    r = sr.Recognizer()
    with sr.Microphone() as source:
        if prompt:
            speak(prompt)
        print("🎤 Listening...")
        audio = r.listen(source, timeout=5, phrase_time_limit=12)
    try:
        query = r.recognize_google(audio)
        print(f"You said: {query}")
        return query
    except sr.UnknownValueError:
        speak("Sorry, I didn't quite catch that.")
        return ""
    except sr.RequestError:
        speak("Speech recognition is unavailable.")
        return ""

SITE_URL_BUILDERS = {
    "amazon": lambda query: f"https://www.amazon.in/s?k={urllib.parse.quote_plus(query)}",
    "flipkart": lambda query: f"https://www.flipkart.com/search?q={urllib.parse.quote(query, safe='')}",
    "walmart": lambda query: f"https://www.walmart.com/search?q={urllib.parse.quote(query, safe='')}",
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

                page_products = parse_products_from_markdown(
                    result.markdown,
                    structured.get("min_price", 0),
                    structured.get("max_price", 999999)
                )

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
            
            products = parse_products_from_markdown(
                result.markdown,
                min_price=min_price,
                max_price=max_price
            )

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

def clean_markdown_to_text(markdown: str) -> str:
    """Clean markdown and convert to readable text"""
    markdown = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', markdown)  # keep link text only
    markdown = re.sub(r'\*\*(.*?)\*\*', r'\1', markdown)  # bold
    markdown = re.sub(r'#+ ', '', markdown)  # headings
    markdown = re.sub(r'\s{2,}', ' ', markdown)  # excess whitespace
    return markdown.strip()

def parse_products_from_markdown(markdown: str, min_price: int, max_price: int) -> List[Dict]:
    """Robust product parsing with improved pattern matching"""
    products = []
    
    # Combined pattern for product blocks
    product_block_pattern = re.compile(
        r'(?:^|\n)(?P<title>(?:#+\s*|\d+\.\s+|\*{2})\s*(.*?))\s*\n' # Capture full title line
        r'(?:.*?)(?P<price>₹\s*[\d,]+|Rs\.\s*[\d,]+|INR\s*[\d,]+)'  # Price capture
        r'(?:.*?)(?P<link>\[[^\]]*\]\(https?:\/\/[^\)]+\))?'        # Optional link
        r'(?:.*?)(?P<image>!\[[^\]]*\]\(https?:\/\/[^\)]+\))?',     # Optional image
        re.DOTALL
    )
    
    for match in product_block_pattern.finditer(markdown):
        title = re.sub(r'^[#\d\.\*\s]+', '', match.group(1)).strip()
        
        try:
            price_str = re.search(r'[\d,]+', match.group('price')).group().replace(',', '')
            price = int(price_str)
        except (AttributeError, ValueError):
            continue
            
        if not (min_price <= price <= max_price):
            continue
            
        link_match = re.search(r'\((https?://[^\)]+)\)', match.group('link') or '')
        image_match = re.search(r'\((https?://[^\)]+)\)', match.group('image') or '')
        
        products.append({
            "title": title,
            "price": price,
            "link": link_match.group(1) if link_match else None,
            "image": image_match.group(1) if image_match else None
        })
    
    return products

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
        title = item.get("title", "No title")
        price = f"₹{item['price']:,}" if item.get("price") else "Price not available"
        link = item.get("link", "")
        image = item.get("image", "")

        parts = title.split(" | ", 1)
        main_title = parts[0].strip()
        description = parts[1].strip() if len(parts) > 1 else ""

        print(f"\n{i}. 🛒 {main_title}")
        print(f"   💰 Price: {price}")
        if link:
            print(f"   🔗 Link: {link}")
        if image:
            print(f"   🖼️ Image: {image}")
        if description:
            print(f"   📦 Details: {description}")
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
        print(f"❌ Error saving to CSV: {str(e)}")

def main():
    """Main function with improved error handling"""
    print("🛒 Smart Product Scraper (Voice Enabled)")
    print("=" * 50)
    
    while True:
        user_input = get_voice_input("What would you like to do? Say '1' for URL scraping, '2' for prompt scraping, or 'exit':").strip().lower()
        
        if "exit" in user_input:
            speak("Goodbye!")
            print("Goodbye!")
            break

        elif '1' in user_input or 'one' in user_input:
            speak("Please type the URL you want to scrape.")
            url = input("Enter the URL: ").strip()
            if not url:
                speak("No URL received.")
                print("No URL received.")
                continue

            speak(f"Scraping the page you requested.")
            print(f"Scraping {url}")
            products = asyncio.run(url_scraper(url))

            if products:
                save_option = get_voice_input("Scraping complete! Say yes to save results or no to skip: ").strip().lower()
                if 'yes' in save_option:
                    save_to_dataframe(products)
                else:
                    speak("No products found.")
        
        elif "2" in user_input or "two" in user_input:
            user_prompt = get_voice_input("What would you like to search for?").strip()
            if not user_prompt:
                speak("No prompt detected. Please try again.")
                print("No prompt detected. Please try again.")
                continue
            
            speak("Processing your request.")
            print("Processing your request...")
            structured = query_llama(user_prompt)

            if not structured:
                speak("Sorry, I couldn't understand. Please try again.")
                print("Sorry, I couldn't understand. Please try again.")
                continue

            questions = ask_follow_up_questions(user_prompt, structured)

            if questions:
                speak("I have a few questions to refine your search.")
                user_answers = []
                for q in questions:
                    ans = get_voice_input(f"🎤 {q}").strip()
                    user_answers.append(ans)
                structured = refine_structured_query_with_answers(user_prompt, user_answers, structured)
                speak("Search refined!")
                print("Search refined!")

            structured["query"] = sanitize_query(structured.get("query", user_prompt))

            print("Final configuration: ")
            print(json.dumps(structured, indent=2))

            speak("Starting the scraping process.")
            results =  asyncio.run(run_crawl4ai_scraper(structured))

            if not results:
                speak("No results found.")
                speak("No results found.")
                continue

            display_results(results)

            speak("Would you like to save the results as CSV or Excel?")
            save_option = get_voice_input("🎤 Say 'CSV', 'Excel', or 'None': ").strip().lower()

            if "csv" in save_option:
                speak("Please say the file name.")
                filename = get_voice_input("🎤 Say the file name for CSV: ").strip()
                save_to_dataframe(results, filename)
            elif "excel" in save_option or "xlsx" in save_option:
                speak("Please say the file name.")
                filename = get_voice_input("🎤 Say the file name for Excel: ").strip()
                save_to_excel(results, filename)

        else:
            speak("Sorry, I didn't get that. Please say one, two or exit.")
            print("Sorry, I didn't get that. Please say one, two or exit.")

if __name__ == "__main__":
    main()