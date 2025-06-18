import subprocess
import re
import json
from scrapegraphai import telemetry
from scrapegraphai.graphs import SmartScraperGraph, SearchGraph

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
    - Values: "amazon", "flipkart", or "google" (default)
    - Keywords to detect: 
        - Flipkart: "flipkart", "flip kart", "FK"
        - Amazon: "amazon", "amzn"
        - Google: when no site is mentioned
    - **Examples**: "buy on flipkart" → "flipkart", "amazon deals" → "amazon", "find laptop" → "google"

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
        "site": "google.com/search?q=premium+wireless+headphones",
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
        "site": "amazon.com/s?k=buy+iphone",
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

def run_scaper (goal, source_url):
    config = {
        "llm": {
            "model": "ollama/llama3:8b-instruct-q8_0",
            "temperature": 0,
            "format": "json",
            "base_url": "http://localhost:11434",
            "model_tokens": 4000
        },
        # "loader_kwargs": {
        #     "proxy": {
        #         "server": "broker",
        #         "criteria" : {
        #             "anonymous": True,
        #             "secure": True,
        #             "countryset": {"IT"},
        #             "timeout": 10.0,
        #             "max_shape": 3
        #         }
        #     }
        # },
        "verbose": True,
        "headless": False,
    }

    graph = SmartScraperGraph(prompt=goal, source=source_url, config=config)
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
    query = structured.get("query")
    goal = structured.get("goal")

    if not goal:
        print("Goal could not be found :<")
        return
    
    print(site)
    source_url = f"https://{site}.com"
    
    print("Scraping from:", source_url)
    print("Goal:", goal)

    try:
        result = run_scaper(goal, source_url)
        print("Extracted data: \n", result)
    except Exception as e:
        print("Scraping failed :< ", str(e))

if __name__ == "__main__":
    main()