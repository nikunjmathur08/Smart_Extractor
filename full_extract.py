import re
import asyncio
import json
import subprocess
import urllib.parse
from crawl4ai import *
from typing import List
import urllib.parse

SITE_URL_BUILDERS = {
    "amazon": lambda query: f"https://www.amazon.in/s?k={urllib.parse.quote_plus(query)}",
    "flipkart": lambda query: f"https://www.flipkart.com/search?q={urllib.parse.quote(query, safe='')}",
    "croma": lambda query: f"https://www.croma.com/searchB?q={urllib.parse.quote(query, safe='')}%3Arelevance&text={urllib.parse.quote(query, safe='')}",
    "tatacliq": lambda query: f"https://www.tatacliq.com/search/?searchCategory={urllib.parse.quote_plus(query)}",
    "duckduckgo": lambda query: f"https://duckduckgo.com/?q={urllib.parse.quote_plus(query)}",
}

DEFAULT_SITE = "duckduckgo"

def extract_search_terms(structured_query):
    """Extract clean search terms from structured query"""
    product_type = structured_query.get('product_type', '')
    additional_filters = structured_query.get('additional_filters', [])
    
    search_terms = [product_type] if product_type else []
    search_terms.extend(filter_term for filter_term in additional_filters 
                       if filter_term not in ['premium', 'budget', 'cheap', 'expensive'])
    
    if not search_terms:
        original = structured_query.get('query', '')
        cleaned = re.sub(r'\b(on|from)\s+(amazon|flipkart|croma|tatacliq)\b', '', original, flags=re.IGNORECASE)
        cleaned = re.sub(r'\b(under|below|above|over)\s+\d+\b', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\b(₹|rs\.?|inr)\s*\d+\b', '', cleaned, flags=re.IGNORECASE)
        search_terms.append(cleaned.strip())
    
    return ' '.join(search_terms).strip()

def query_llama(user_input):
    """Uses Ollama to extract structured info with robust JSON parsing"""
    
    try:
        process = subprocess.run(
            ["ollama", "run", "query-llama"],
            input=user_input,
            text=True,
            capture_output=True,
            timeout=30
        )
        stdout = process.stdout
        
        # Robust JSON extraction
        json_match = re.search(r'\{[\s\S]*\}', stdout)
        if not json_match:
            raise ValueError("No JSON found in LLM output")
            
        result = json.loads(json_match.group(0))

        if result.get('max_price') is None:
            result['max_price'] = 99999
        
        return result
    except (json.JSONDecodeError, ValueError, subprocess.TimeoutExpired) as e:
        print(f"LLM processing error: {str(e)}")
        return None

def ask_follow_up_questions(user_input, structured_query):
    """Ask follow-up questions based on the input using LLM"""

    prompt = f"""
    **User Input**: {user_input}
    **Structured Query**: {json.dumps(structured_query, indent=2)}
    """
    try:
        process = subprocess.run(
            ["ollama", "run", "follow-ups"],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=20
        )
        stdout = process.stdout
        json_match = re.search(r'\[[\s\S]*\]', stdout)
        return json.loads(json_match.group(0)) if json_match else []
    except Exception as e:
        print(f"Could not generate questions: {str(e)}")
        return []
    
def refine_structured_query_with_answers(original_input, answers, previous_query):
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
        process = subprocess.run(
            ["ollama", "run", "refine-query"],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=30
        )
        stdout = process.stdout
        json_match = re.search(r'\{[\s\S]*\}', stdout)

        result = json.loads(json_match.group(0)) if json_match else previous_query

        if result.get('max_price') is None:
            result['max_price'] = 99999

        return result
    except Exception as e:
        print(f"Failed to refine structured query: {e}")
        return previous_query

def build_source_url(site_key: str, query: str) -> str:
    builder = SITE_URL_BUILDERS.get(site_key.lower(), SITE_URL_BUILDERS[DEFAULT_SITE])
    print(f"Generated URL: {builder(query)}")
    return builder(query)

async def run_crawl4ai_scraper(structured):
    site_key = structured.get("site", DEFAULT_SITE).lower()
    source_url = build_source_url(site_key, structured['query'])
    
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

    try:
        async with AsyncWebCrawler(config=browser_conf) as crawler:
            result = await crawler.arun(url=source_url, config=run_conf)
            
        if not result.success:
            print(f"❌ Crawling failed: {result.error_message}")
            return []

        return parse_products_from_markdown(
            result.markdown, 
            structured.get("min_price", 0),
            structured.get("max_price", 999999)
        )
    except Exception as e:
        print(f"⚠️ Scraping error: {str(e)}")
        return []

def parse_products_from_markdown(markdown, min_price, max_price):
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
    text = re.sub(r'(under|above|over|below)\s+₹?\s*[\d,]+', '', text, flags=re.I)
    text = re.sub(r'\b(at|on|from)\s+(amazon|flipkart|croma|tatacliq)\b', '', text, flags=re.I)
    text = re.sub(r'₹|rs\.?|inr', '', text, flags=re.I)
    return re.sub(r'\s+', ' ', text).strip()

def main():
    print("🛒 Smart Product Scraper")
    
    while True:
        user_input = input("\n🔍 What would you like to scrape? (or type 'exit')\n→ ")
        if user_input.lower() == 'exit':
            print("Bye bye! ^_^")
            break
            
        structured = query_llama(user_input)
        if not structured:
            print("❌ Could not parse your query. Please try again.")
            continue
        
        questions = ask_follow_up_questions(user_input, structured)
        if questions:
            print("\n I have a few questions to refine your search...")
            user_answers = []
            for q in questions:
                ans = input(f"→ {q} ")
                user_answers.append(ans.strip())
            
            structured = refine_structured_query_with_answers(user_input, user_answers, structured)
        
        structured["query"] = sanitize_query(structured["query"])

        print("\n📋 Final Structured Query:")
        print(json.dumps(structured, indent=2))
        
        results = asyncio.run(run_crawl4ai_scraper(structured))
        if not results:
            print("\n⚠️ No products matched your filters.")
            continue
            
        print(f"\n🛍️ Found {len(results)} product(s):\n")
        for i, item in enumerate(results, 1):
            print(f"{i}. {item['title']}")
            print(f"   💰 ₹{item['price']:,}")
            if item['link']:
                print(f"   🔗 {item['link']}")
            if item.get('image'):
                print(f"   🖼️ {item['image']}")
            print("-" * 80)

if __name__ == "__main__":
    main()