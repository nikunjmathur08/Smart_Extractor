import subprocess
import re
import json
import random
import urllib.parse
from amazon_scraper import get_amazon_results as amzn
from custom_loader import CustomChromiumLoader
from scrapegraphai import telemetry
from scrapegraphai.graphs import SmartScraperGraph, SearchGraph, markdownify_graph

SITE_URL_BUILDERS = {
    "amazon": lambda query: amzn(query, proxy=None),
    "flipkart": lambda query: f"https://www.flipkart.com/search?q={urllib.parse.quote_plus(query)}",
    "croma": lambda query: f"https://www.croma.com/searchB?q={urllib.parse.quote_plus(query)}",
    "tatacliq": lambda query: f"https://www.tatacliq.com/search/?searchCategory={urllib.parse.quote_plus(query)}",
    "duckduckgo": lambda query: f"https://duckduckgo.com/?q={urllib.parse.quote_plus(query)}",
}

DEFAULT_SITE = "duckduckgo"

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
    - **Examples**: "buy on flipkart" → "flipkart", "amazon deals" → "amazon", "find laptop" → "ducduckgo"

    ### product_type
    - Normalize to standard categories: "smartphones", "laptops", "books", "groceries", "furniture", "appliances", "clothing", "toys", "electronics", "beauty", "sports", "automotive", "home", "kitchen"
    - Handle variations: 
        - "phone/mobile/cell phone" → "smartphones"
        - "computer/notebook" → "laptops" 
        - "clothes/apparel/fashion" → "clothing"
        - "food/snacks" → "groceries"
        - "earphones/headphones/earbuds" → "electronics"
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
        - Technical specs: "gaming", "wireless", "bluetooth", "waterproof", "fast charging"
        - Quality indicators: "premium", "eco-friendly", "organic", "branded"
        - Size/capacity: "large", "compact", "portable", "1TB", "32GB"
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

    ## Extraction Process
    1. Read the entire query carefully
    2. Identify explicit mentions first (direct product names, prices, sites)
    3. Infer missing information from context (brand mentions suggest product type)
    4. Apply defaults for unspecified fields
    5. Normalize and standardize values
    6. Return only valid JSON with all required fields

    ## Example Extractions

    **Input**: "I want to buy a gaming laptop under 80000 on flipkart"
    {{
        "site": "https://flipkart.com/search?q=buy%20gaming%20laptop%20under%2080000",
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
        "site": "https://duckduckgo.com/?q=premium+wireless+headphones",
        "product_type": "electronics",
        "min_price": 0,
        "max_price": 999999,
        "sort_order": "desc",
        "additional_filters": ["premium", "wireless"],
        "goal": "premium wireless headphones",
        "query": "show me premium wireless headphones, most expensive first"
    }}

    **Input**: "show me iPhones on Amazon"
    {{
        "site": "https://amazon.in/s?k=buy+iphone",
        "product_type": "electronics",
        "min_price": 0,
        "max_price": 999999,
        "sort_order": "desc",
        "additional_filters": ["premium", "wireless"],
        "goal": "buy iPhone",
        "query": "show me premium wireless headphones, most expensive first"
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
    
def build_source_url (site_key: str, query: str) -> str:
    """Generates a URL based on the site and query"""
    builder = SITE_URL_BUILDERS.get(site_key.lower(), SITE_URL_BUILDERS[DEFAULT_SITE])
    return builder(query)

def run_scaper (goal, source_url):

    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 9_0_8) Gecko/20100101 Firefox/59.7",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 11_9_2; like Mac OS X) AppleWebKit/534.23 (KHTML, like Gecko)  Chrome/55.0.3939.364 Mobile Safari/535.9",
        "Mozilla/5.0 (Linux; Android 5.0.2; SM-A700I Build/LMY47X) AppleWebKit/534.3 (KHTML, like Gecko)  Chrome/49.0.3625.166 Mobile Safari/534.9",
        "Mozilla/5.0 (Windows; U; Windows NT 6.2; x64) Gecko/20100101 Firefox/64.7",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_8_0) Gecko/20100101 Firefox/55.4",
        "Mozilla/5.0 (Linux; Android 10; GM1917) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/77.0.3865.116 Mobile Safari/537.36 EdgA/45.12.4.5121",
    ]

    config = {
        "llm": {
            "model": "ollama/llama3:8b-instruct-q8_0",
            "temperature": 0,
            "format": "json",
            "base_url": "http://localhost:11434",
            "model_tokens": 4000
        },
        "chromium_loader": True,
        "loader_cls": CustomChromiumLoader,
        "verbose": True,
        # "headless": True,
    }

    graph = SearchGraph(prompt=goal, config=config)
    return graph.run()

def main() :
    telemetry.disable_telemetry()
    print("Smart Terminal Scraper ^_^")
    user_input = input("What would you like to scrape? (e.g. 'Find best phones under ₹30000 on Amazon): \n")

    structured = query_llama(user_input)
    if not structured:
        print("Could not understand input. Try again...")
        return
    
    site = structured.get("site")
    site_key = structured.get("site", DEFAULT_SITE).lower().replace("https://", "").replace("www", "").split(".")[0]
    query = structured.get("query")
    goal = structured.get("goal")

    if not goal:
        print("Goal could not be found :<")
        return
    
    if site.lower() == "amazon":
        print("Using Amazon Scraper...")
        results = amzn(query)
        print("Extracted data...\n")
        for r in results:
            print(r)
    else:
        source_url = build_source_url(site_key, query)
        print("Scraping from...", source_url)
        print("Goal:", goal)

        try:
            result = run_scaper(goal, source_url)
            print("Extracted data: \n", result)
        except Exception as e:
            print("Scraping failed :< ", str(e))

if __name__ == "__main__":
    main()