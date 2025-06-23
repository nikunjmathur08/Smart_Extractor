import re
import asyncio
from crawl4ai import *
from urllib.parse import urlparse
import subprocess
import json
import urllib.parse

# Remove the conflicting SITE_URL_BUILDERS that uses amazon_scraper
SITE_URL_BUILDERS = {
    "amazon": lambda query: f"https://www.amazon.in/s?k={urllib.parse.quote_plus(query)}",
    "flipkart": lambda query: f"https://www.flipkart.com/search?q={urllib.parse.quote_plus(query)}",
    "croma": lambda query: f"https://www.croma.com/searchB?q={urllib.parse.quote_plus(query)}",
    "tatacliq": lambda query: f"https://www.tatacliq.com/search/?searchCategory={urllib.parse.quote_plus(query)}",
    "duckduckgo": lambda query: f"https://duckduckgo.com/?q={urllib.parse.quote_plus(query)}",
}

DEFAULT_SITE = "duckduckgo"

def extract_search_terms(structured_query):
    """Extract clean search terms from structured query"""
    product_type = structured_query.get('product_type', '')
    additional_filters = structured_query.get('additional_filters', [])
    
    # Start with product type
    search_terms = []
    if product_type:
        search_terms.append(product_type)
    
    # Add relevant filters
    for filter_term in additional_filters:
        if filter_term not in ['premium', 'budget', 'cheap', 'expensive']:
            search_terms.append(filter_term)
    
    # If no good terms found, use original query but clean it
    if not search_terms:
        original = structured_query.get('query', '')
        # Remove site mentions and price mentions
        cleaned = re.sub(r'\b(on|from)\s+(amazon|flipkart|croma|tatacliq)\b', '', original, flags=re.IGNORECASE)
        cleaned = re.sub(r'\b(under|below|above|over)\s+\d+\b', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\b(₹|rs\.?|inr)\s*\d+\b', '', cleaned, flags=re.IGNORECASE)
        search_terms.append(cleaned.strip())
    
    return ' '.join(search_terms).strip()

def query_llama(user_input):
    """Uses Ollama to run a system prompt and extract structured info"""
    prompt = f"""
    You are a highly accurate information extractor for free-form shopping and search queries.

    Your task is to **parse natural language input** and analyze user queries about product searches and return structured JSON data with the following keys ONLY.

    ## Required JSON Structure
    {{
        "site": "string",
        "product_type": "string", 
        "min_price": number,
        "max_price": number,
        "sort_order": "string",
        "additional_filters": ["array", "of", "strings"],
        "goal": "string",
        "query": "string"
    }}

    ## Field Extraction Guidelines

    ### site
    - Values: "amazon", "flipkart", or "duckduckgo" (default)
    - Keywords to detect: 
        - Flipkart: "flipkart", "flip kart", "FK"
        - Amazon: "amazon", "amzn"
        - DuckDuckGo: when no site is mentioned
    - **Examples**: "buy on flipkart" → "flipkart", "amazon deals" → "amazon", "find laptop" → "duckduckgo"

    ### product_type
    - Normalize to standard categories: "smartphones", "laptops", "books", "groceries", "furniture", "appliances", "clothing", "toys", "electronics", "beauty", "sports", "automotive", "home", "kitchen"
    - Handle variations: 
        - "phone/mobile/cell phone" → "smartphones"
        - "computer/notebook" → "laptops" 
        - "clothes/apparel/fashion" → "clothing"
        - "food/snacks" → "groceries"
        - "earphones/headphones/earbuds" → "electronics"
        - "tv/television/smart tv" → "televisions"
    - **Extract from context**: Look for brand names, model numbers, or descriptive terms

    ### min_price and max_price
    - Default values: min_price: 0, max_price: 999999
    - Keywords to detect:
        - "under X", "below X", "less than X" → max_price: X, min_price: 0
        - "above X", "over X", "more than X" → min_price: X, max_price: 999999
        - "between X and Y", "X to Y range" → min_price: X, max_price: Y
        - "around X", "approximately X" → min_price: X*0.8, max_price: X*1.2
    - Handle currency: Remove currency symbols (₹, $, Rs, INR, USD)
    - Handle formats: "5k" → 5000, "2.5L" → 250000, "1 lakh" → 100000

    ### sort_order
    - Values: "asc" (cheapest first) or "desc" (expensive first)
    - Keywords for "asc": "cheapest", "lowest price", "budget", "affordable", "cheap", "economical"
    - Keywords for "desc": "expensive", "premium", "high-end", "luxury", "best quality", "top rated", "most expensive"
    - Default: null if no sorting preference detected

    ### additional_filters
    - Extract relevant modifiers and features:
        - Technical specs: "gaming", "wireless", "bluetooth", "waterproof", "fast charging", "smart", "4K", "LED", "OLED"
        - Quality indicators: "premium", "eco-friendly", "organic", "branded"
        - Size/capacity: "large", "compact", "portable", "1TB", "32GB", "55 inch", "65 inch"
        - Colors: "black", "white", "red" (only if specifically mentioned)
        - Conditions: "new", "refurbished", "used"
        - Exclude: Generic words like "good", "nice", "quality" unless specific (e.g., "high quality")

    ### goal
    - Summarize user intent in 5-10 words
    - **Examples**: 
        - "find affordable gaming laptop" 
        - "buy wireless headphones under budget"
        - "compare premium smartphones"
    - Focus on action + product + key constraint

    ### query
    - Return the original user input exactly as provided
    - Preserve all punctuation, capitalization, and formatting

    ## Example Extractions

    **Input**: "I want to buy a gaming laptop under 80000 on flipkart"
    {{
        "site": "flipkart",
        "product_type": "laptops",
        "min_price": 0,
        "max_price": 80000,
        "sort_order": "asc",
        "additional_filters": ["gaming"],
        "goal": "buy gaming laptop under 80000 flipkart",
        "query": "I want to buy a gaming laptop under 80000 on flipkart"
    }}

    **Input**: "show me premium wireless headphones, most expensive first"
    {{
        "site": "duckduckgo",
        "product_type": "electronics",
        "min_price": 0,
        "max_price": 999999,
        "sort_order": "desc",
        "additional_filters": ["premium", "wireless"],
        "goal": "buy premium wireless headphones",
        "query": "show me premium wireless headphones, most expensive first"
    }}

    **Input**: "show me iPhones on Amazon"
    {{
        "site": "amazon",
        "product_type": "electronics",
        "min_price": 0,
        "max_price": 999999,
        "sort_order": "asc",
        "additional_filters": ["iPhone"],
        "goal": "buy iPhone",
        "query": "show me iPhones on Amazon"
    }}

    **Input**: "tvs under 80000 on flipkart"
    {{
        "site": "flipkart",
        "product-type": "televisions",
        "min_price": 0,
        "max_price": 80000,
        "sort_order": "asc",
        "additional_filters": ["televisions"],
        "goal": "buy tv under 80000",
        "query": "tvs under 80000 on flipkart"
    }}

    ## Important Notes
    - Always return valid JSON only, no additional text
    - Use null for optional fields when no relevant information is found
    - Be conservative with additional_filters - only include clearly relevant terms
    - When in doubt about product_type, choose the most general applicable category
    - Price extraction should handle Indian numbering (lakh, crore) and common abbreviations (k, L)

    ### USER INPUT:
    {user_input}

    ### RESPONSE (JSON ONLY):
    """
    
    process = subprocess.Popen(
        ["ollama", "run", "llama3:8b-instruct-q8_0"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    stdout, stderr = process.communicate(input=prompt)

    try:
        match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', stdout, re.DOTALL)
        if not match:
            raise ValueError("No JSON found in LLM output.")
        extracted_json = match.group(0)
        
        extracted_json = extracted_json.strip()
        
        return json.loads(extracted_json)
    except Exception as e:
        print("Error parsing LLM response:", e)
        print("LLM Output:\n", stdout)
        return None

def build_source_url(site_key: str, query: str) -> str:
    """Generates a URL based on the site and query"""
    builder = SITE_URL_BUILDERS.get(site_key.lower(), SITE_URL_BUILDERS[DEFAULT_SITE])
    return builder(query)

async def run_crawl4ai_scraper(structured):
    query = structured['query']
    goal = structured['goal']
    site_key = structured.get("site", DEFAULT_SITE).lower()
    
    if site_key not in SITE_URL_BUILDERS:
        site_key = DEFAULT_SITE
    
    source_url = build_source_url(site_key, query)

    print("🔍 Scraping from:", source_url)
    print("🎯 Goal:", goal)

    browser_conf = BrowserConfig(
        headless=False,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    run_conf = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        wait_for_images=True,
        delay_before_return_html=3,  # Wait for page to load
        js_code=[
            "window.scrollTo(0, document.body.scrollHeight/2);",  # Scroll to load more content
            "await new Promise(resolve => setTimeout(resolve, 2000));"  # Additional wait
        ]
    )

    async with AsyncWebCrawler(config=browser_conf) as crawler:
        result = await crawler.arun(url=source_url, config=run_conf)

    if not result.success:
        print(f" Crawling failed: {result.error_message}")
        return []

    markdown = result.markdown
    print(f" Markdown length: {len(markdown)} characters")
    
    # Debug: Print first 1000 chars of markdown
    print(" Markdown preview:")
    print(markdown[:1000])
    print("=" * 50)
    
    lines = markdown.split("\n")

    min_price = structured.get("min_price", 0)
    max_price = structured.get("max_price", 999999)

    products = []
    current = {}

    # Enhanced product parsing for different formats
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
            
        # Look for product titles (various patterns)
        title_patterns = [
            r"^\d+\.\s*(.+)",  # Numbered list
            r"^\*\*(.+?)\*\*",  # Bold text
            r"^#+\s*(.+)",      # Headers
            r"^\[(.+?)\]",      # Links
        ]
        
        for pattern in title_patterns:
            match = re.match(pattern, line)
            if match:
                # Save previous product if complete
                if current.get("title") and current.get("price") is not None:
                    if min_price <= current["price"] <= max_price:
                        products.append(current.copy())
                
                current = {
                    "title": match.group(1).strip(),
                    "price": None,
                    "link": None,
                    "image": None
                }
                break

        # Enhanced price detection
        price_patterns = [
            r"₹\s*([\d,]+)",
            r"Rs\.?\s*([\d,]+)",
            r"INR\s*([\d,]+)",
            r"\$\s*([\d,]+)",
            r"Price:\s*₹?\s*([\d,]+)",
        ]
        
        for pattern in price_patterns:
            price_match = re.search(pattern, line, re.IGNORECASE)
            if price_match:
                try:
                    price = int(price_match.group(1).replace(",", ""))
                    current["price"] = price
                    break
                except ValueError:
                    continue

        # Find links
        link_match = re.search(r"\[.*?\]\((https?://[^\)]+)\)", line)
        if link_match and current.get("title"):
            current["link"] = link_match.group(1)

        # Find images
        img_match = re.search(r"!\[.*?\]\((https?://[^\)]+)\)", line)
        if img_match and current.get("title"):
            current["image"] = img_match.group(1)

    # Don't forget the last product
    if current.get("title") and current.get("price") is not None:
        if min_price <= current["price"] <= max_price:
            products.append(current)

    print(f" Found {len(products)} products after filtering")
    return products

def main():
    print(" Smart Terminal Scraper ^_^")
    user_input = input(" What would you like to scrape? \n→ ")

    structured = query_llama(user_input)
    if not structured:
        print(" Could not parse your query. Try again.")
        return

    print("\n🤖 Structured Query:\n", json.dumps(structured, indent=2))

    try:
        results = asyncio.run(run_crawl4ai_scraper(structured))
        if not results:
            print(" No products matched your filters.")
            return

        print(f"\n Showing {len(results)} product(s):\n")
        for i, item in enumerate(results, 1):
            print(f"{i}. {item['title']}")
            if item['price']:
                print(f"   ₹{item['price']:,}")
            print(f"    {item.get('link', 'No link found')}")
            if item.get("image"):
                print(f"    {item['image']}")
            print("-" * 120)
    except Exception as e:
        print("Scraping failed:", str(e))
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()