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
import aiohttp

SITE_URL_BUILDERS = {
    "amazon": lambda query: f"https://www.amazon.in/s?k={urllib.parse.quote_plus(query)}",
    "flipkart": lambda query: f"https://www.flipkart.com/search?q={urllib.parse.quote(query, safe='')}",
    "croma": lambda query: f"https://www.croma.com/searchB?q={urllib.parse.quote(query, safe='')}%3Arelevance&text={urllib.parse.quote(query, safe='')}",
    "tatacliq": lambda query: f"https://www.tatacliq.com/search/?searchCategory={urllib.parse.quote_plus(query)}",
    "duckduckgo": lambda query: f"https://duckduckgo.com/?q={urllib.parse.quote_plus(query)}",
}

DEFAULT_SITE = "duckduckgo"

async def ask_ollama (model: str, prompt: str, stream=False) -> str:
    url = "http://localhost:11434/api/generate"
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": stream,
        "options": {
            "num_ctx": 4096,
            "temperature": 0
        }
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=120) as response:
                response.raise_for_status()
                if stream:
                    output = ""
                    async for line in response.content.iter_any():
                        if line:
                            chunk = json.loads(line.decode("utf-8"))
                            output += chunk.get("response", "")
                    return output
                else:
                    data = await response.json()
                    return data.get("response", "")
    except Exception as e:
        print(f"Error calling Ollama for model {model}: {str(e)}")
        return ""

async def extract_detailed_product_info(blocks: List[str], keywords: list) -> List[Dict]:
    """Regex-based product extraction - fast and reliable"""
    markdown = "\n\n".join(blocks)
    products = extract_products_from_markdown(markdown, keywords)
    
    print(f"DEBUG: Regex extracted {len(products)} products")
    for product in products:
        print(f"DEBUG: {product['title']} - ₹{product['price']:,}")
    
    return products

def dynamic_chunk(blocks, max_chars = 8000):
    chunks = []
    current_chunk = []
    current_len = 0
    for block in blocks:
        if len(block) < 100 or '₹' not in block:  # Pre-filter: Skip short/no-price blocks to reduce LLM load
            continue
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

def cleaned_markdown(markdown: str) -> str:
    """Removes noise from data scraped without erasing products"""
    # More targeted removals
    markdown = re.sub(r'## Skip to.*Keyboard shortcuts.*To move between items.*', '', markdown, flags=re.DOTALL | re.IGNORECASE)  # Remove specific header
    markdown = re.sub(r'Your Lists.*Your Account.*', '', markdown, flags=re.DOTALL)  # Account section
    markdown = re.sub(r'Sort by:.*Newest Arrivals.*', '', markdown, flags=re.DOTALL)  # Sort bar
    markdown = re.sub(r'\[SponsoredSponsored \].*?\[Let us know \].*?', '', markdown, flags=re.DOTALL)  # Sponsored, limited scope
    markdown = re.sub(r'!\[.*?\]\(.*?\)', '', markdown)  # Images
    markdown = re.sub(r'\[.*?\]\(.*?\)', lambda m: m.group(1) if 'http' not in m.group(0) else '', markdown)  # Links
    markdown = re.sub(r'© 1996-2025, Amazon.com.*', '', markdown)  # Footer

    lines = markdown.split('\n')
    preserved = [line for line in lines if re.search(r'₹[\d,]+|\*\*.*\*\*', line, re.IGNORECASE)]  # Keep relevant
    return '\n'.join(preserved).strip()

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

async def query_llama(user_input: str) -> Optional[Dict]:
    """Uses Ollama to extract structured info with robust JSON parsing"""
    try:
        response_text = await ask_ollama("query-llama", user_input)
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

async def ask_follow_up_questions(user_input: str, structured_query: Dict) -> List[str]:
    """Ask follow-up questions based on the input using LLM"""
    prompt = f"""
    **User Input**: {user_input}
    **Structured Query**: {json.dumps(structured_query, indent=2)}
    """
    try:
        response_text = await ask_ollama("follow-ups", prompt)
        json_match = re.search(r'\[[\s\S]*\]', response_text)
        return json.loads(json_match.group(0)) if json_match else []
    except Exception as e:
        print(f"⚠️ Could not generate questions: {str(e)}")
        return []
    
async def refine_structured_query_with_answers(original_input: str, answers: List[str], previous_query: Dict) -> Dict:
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
        response_text = await ask_ollama("refine-query", prompt)
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

def generate_paginated_urls(base_url: str, site_key: str, pages: int = 2) -> List[str]:
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
    paginated_urls = generate_paginated_urls(source_url, site_key, pages=2)
    
    browser_conf = BrowserConfig(
        headless=False,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    )
    
    run_conf = CrawlerRunConfig(
        cache_mode=CacheMode.READ_ONLY,
        wait_for_images=True,
        magic=True,
        simulate_user=True,
        override_navigator=True,
        scan_full_page=True,
        delay_before_return_html=4,
        js_code=[
            "window.scrollTo(0, document.body.scrollHeight/2);",
            "await new Promise(resolve => setTimeout(resolve, 2000));"
        ]
    )

    all_products = []

    try:
        async with AsyncWebCrawler(config=browser_conf) as crawler:
            for i, url in enumerate(paginated_urls, start=1):
                try:
                    print(f"🔍 Scraping page {i}: {url}")
                    result = await crawler.arun(url=url, config=run_conf)

                    if not result or not result.success:
                        print(f"❌ Failed to scrape page {i}: {getattr(result, 'error_message', 'No result')}")
                        continue

                    # Save the raw markdown for debug purposes, but DO NOT break!
                    print("Saving data to markdown file...")
                    with open(f"debug_page_{i}.md", "w", encoding="utf-8") as f:
                        f.write(result.markdown or '')

                    keywords = structured.get('query', '').lower().split()
                    print(f"DEBUG: Using keywords for filtering: {keywords}")
                    product_blocks = split_markdown_to_product_blocks(result.markdown, keywords)

                    if product_blocks:
                        with open(f"product_block_{i}.md", "w", encoding="utf-8") as p:
                            p.write("\n---\n".join(product_blocks))
                        print(f"Saved {len(product_blocks)} blocks to product_block_{i}.md")

                    else:
                        print(f"DEBUG: No blocks saved for page {i}")
                    if not product_blocks:
                        print(f"No product blocks found from page {i} (markdown length: {len(result.markdown)})")
                        continue

                    # Extract detailed info using LLM for each block
                    detailed_products = await extract_detailed_product_info(product_blocks, keywords)
                    page_products = []
                    for product in detailed_products:
                        print(f"DEBUG: Extracted product: {json.dumps(product)}")
                        if product and product.get('title') and product.get('price') is not None:
                            title_lower = product['title'].lower()
                            if any(kw in title_lower for kw in keywords):
                                price = product['price']
                                min_price = structured.get('min_price', 0)
                                max_price = structured.get('max_price', 999999)
                                if min_price <= price <= max_price:
                                    page_products.append(product)
                                    print(f"DEBUG: Added product (passed filter): {json.dumps({'title': product['title']})}")

                    all_products.extend(page_products)
                    print(f"✅ Found {len(page_products)} products on page {i}")

                    await asyncio.sleep(2)

                except Exception as e:
                    print(f"Error scraping using run_crawl4ai_scraper: {e}")

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
            detailed_products = await extract_detailed_product_info(product_blocks)
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

def split_markdown_to_product_blocks(markdown: str, query_keywords: list = None) -> list:
    if query_keywords is None:
        query_keywords = []
    
    blocks = re.split(r'(?:\n\s*\n+|^#+\s|\n#+\s|^---+|^\*\*\*+)', markdown, flags=re.MULTILINE)

    filtered_blocks = []
    noise_patterns = [
        r'skip to', r'keyboard shortcuts', r'your lists', r'your account',
        r'select.*department', r'all categories', r'sort by', r'filter',
        r'results? for', r'sponsored', r'advertisement', r'cookies',
        r'privacy policy', r'terms of service', r'copyright', r'©.*\d{4}',
        r'update location', r'delivering to', r'change address'
    ]

    for block in blocks:
        block = block.strip()
        if len(block) < 30:
            continue

        is_noise = any(re.search(pattern, block, re.IGNORECASE) for pattern in noise_patterns)
        if is_noise:
            continue

        has_price = bool(re.search(r'[₹$]\s*[\d,]+', block))
        has_product_words = bool(re.search(r'\b(?:buy|price|offer|discount|sale|deal|product|item|model|brand|available|stock|delivery|shipping)\b', block, re.IGNORECASE))

        if has_price or has_product_words:
            filtered_blocks.append(block)
    
    print(f"Total raw blocks: {len(blocks)}")
    print(f"Total filtered blocks: {len(filtered_blocks)}")
    return filtered_blocks

def extract_products_from_markdown (markdown: str, keywords: list = None, min_price: int = 0, max_price: int = 99999) -> List[Dict]:
    """Enhanced regex-based product extraction"""
    products = []

    blocks = re.split(r'\n\s*\n+', markdown)

    for block in blocks:
        if len(block) < 50 or '₹' not in block:
            continue

        product = extract_product_from_block(block, keywords)
        if product and min_price <= product.get('price', 0) <= max_price:
            products.append(product)
    
    unique_products = []
    seen = set()
    for product in products:
        key = (product['title'], product['price'])
        if key not in seen:
            seen.add(key)
            unique_products.append(product)
    
    return unique_products

def extract_product_from_block(block: str, keywords: list = None) -> Dict:
    """Generic product extraction that works for any product type"""
    if keywords is None:
        keywords = []
    
    # Skip obvious navigation/system blocks
    skip_patterns = [
        r'Select the department',
        r'Skip to.*content',
        r'Your Lists.*Your Account',
        r'Sort by:',
        r'Results for.*in',
        r'Sponsored.*Let us know',
        r'Price range.*Go',
        r'^All\s+Categories',
        r'Update location'
    ]
    
    for pattern in skip_patterns:
        if re.search(pattern, block, re.IGNORECASE | re.DOTALL):
            return None
    
    # 1. UNIVERSAL PRICE EXTRACTION
    price_patterns = [
        r'₹\s*([\d,]+)',                    # ₹1,23,456
        r'Rs\.?\s*([\d,]+)',                # Rs. 1,23,456
        r'INR\s*([\d,]+)',                  # INR 123456
        r'\$\s*([\d,]+)',                   # $1,234
        r'Price:?\s*[₹$]\s*([\d,]+)',       # Price: ₹1,234
    ]
    
    prices = []
    for pattern in price_patterns:
        matches = re.findall(pattern, block, re.IGNORECASE)
        for match in matches:
            try:
                price_val = int(match.replace(',', ''))
                if price_val > 10:  # Filter out obviously wrong prices
                    prices.append(price_val)
            except ValueError:
                continue
    
    if not prices:
        return None
    
    # Use the most reasonable price (not too low, not extremely high)
    main_price = max(p for p in prices if 10 <= p <= 10000000)  # Between ₹10 and ₹1 crore
    
    # 2. UNIVERSAL TITLE EXTRACTION
    title_patterns = [
        # Markdown/HTML headings
        r'##\s*\[([^\]]{15,120})\]',                    # ## [Product Title](link)
        r'##\s+([^\n]{15,120})',                        # ## Product Title
        r'###\s*([^\n]{15,120})',                       # ### Product Title
        
        # Bold/emphasized text (common for product names)
        r'\*\*([^\*\n]{15,120})\*\*',                   # **Product Title**
        r'__([^_\n]{15,120})__',                        # __Product Title__
        
        # Numbered/bulleted lists
        r'^\d+\.\s+([^\n]{15,120})',                    # 1. Product Title
        r'^\*\s+([^\n]{15,120})',                       # * Product Title
        r'^\-\s+([^\n]{15,120})',                       # - Product Title
        
        # Lines that look like product titles (start with capital, reasonable length)
        r'^([A-Z][^\n₹\[\]]{15,120})(?=.*₹)',          # Capitalized line with price nearby
        r'([A-Z][^\n₹\[\]]{15,120})\s*₹',              # Title directly before price
        
        # Link text (often contains product names)
        r'\[([^\]]{15,120})\]\(https?://[^\)]+\)',      # [Product Title](https://...)
        
        # Text near prices (common pattern)
        r'([A-Z][^₹\n\[\]]{15,120})\s*[₹$]\s*[\d,]+',   # "Product Name ₹1,234"
        r'[₹$]\s*[\d,]+\s*([A-Z][^₹\n\[\]]{15,120})',   # "₹1,234 Product Name"
        
        # Sentences that look like product descriptions
        r'([A-Z][^.\n]{20,120}(?:with|featuring|equipped|includes)[^.\n]{5,50})', # Descriptive titles
    ]
    
    title = None
    best_score = 0
    
    for pattern in title_patterns:
        matches = re.findall(pattern, block, re.MULTILINE | re.IGNORECASE)
        for match in matches:
            candidate = match.strip()
            
            # Clean up candidate
            candidate = re.sub(r'^\W+|\W+$', '', candidate)
            candidate = re.sub(r'\s+', ' ', candidate)
            candidate = re.sub(r'\([^)]*\)', '', candidate)  # Remove parentheses
            
            # Score the candidate based on how "product-like" it is
            score = 0
            
            # Length bonus (not too short, not too long)
            if 20 <= len(candidate) <= 100:
                score += 2
            
            # Keyword bonus (if keywords provided)
            if keywords:
                keyword_matches = sum(1 for kw in keywords if kw.lower() in candidate.lower())
                score += keyword_matches * 3
            else:
                score += 1  # Default bonus if no keywords
            
            # Common product indicators
            product_indicators = [
                'pro', 'plus', 'max', 'mini', 'air', 'ultra', 'premium', 'standard',
                'gb', 'tb', 'inch', 'core', 'gen', 'edition', 'model', 'series',
                'laptop', 'phone', 'tablet', 'watch', 'speaker', 'camera',
                'wireless', 'bluetooth', 'smart', 'digital', 'portable'
            ]
            indicator_bonus = sum(1 for indicator in product_indicators if indicator in candidate.lower())
            score += indicator_bonus
            
            # Penalize navigation/generic text
            bad_indicators = [
                'select', 'department', 'category', 'filter', 'sort', 'results',
                'your lists', 'account', 'cart', 'checkout', 'sign in'
            ]
            penalty = sum(2 for bad in bad_indicators if bad in candidate.lower())
            score -= penalty
            
            # Choose the best title
            if score > best_score and score > 0:
                best_score = score
                title = candidate[:100]  # Limit length
    
    if not title:
        return None
    
    # 3. Build the product object
    product = {
        "title": title,
        "price": main_price,
        "rating": extract_rating(block),
        "discount": extract_discount(block),
        "offers": extract_offers(block),
        "link": extract_link(block),
        "image": extract_image(block),
        "availability": extract_availability(block)
    }
    
    return product

def extract_rating(block: str) -> str:
    """Extract product rating"""
    rating_patterns = [
         r'(\d+\.?\d*)\s*out\s*of\s*\d+',      # 4.5 out of 5
        r'(\d+\.?\d*)\s*stars?',               # 4.5 stars
        r'(\d+\.?\d*)\s*/\s*\d+',             # 4.5/5
        r'Rating:?\s*(\d+\.?\d*)',             # Rating: 4.5
        r'⭐+\s*(\d+\.?\d*)',                   # ⭐⭐⭐⭐⭐ 4.5
        r'(\d+\.?\d*)\s*⭐',                    # 4.5 ⭐
    ]
    
    for pattern in rating_patterns:
        match = re.search(pattern, block, re.IGNORECASE)
        if match:
            rating_val = float(match.group(1))
            if 0 <= rating_val <= 5:
                return f"{rating_val} stars"
    return None

def extract_discount(block: str) -> str:
    """Extract discount information"""
    discount_patterns = [
        r'(\d+%\s*off)',                       # 20% off
        r'Save\s*[₹$]\s*([\d,]+)',            # Save ₹5000
        r'(\d+%\s*discount)',                  # 20% discount
        r'Was\s*[₹$]([\d,]+)',                # Was ₹10000 (implies discount)
        r'M\.R\.P:?\s*[₹$]([\d,]+)',          # M.R.P: ₹10000
        r'List\s*Price:?\s*[₹$]([\d,]+)',     # List Price: $100
    ]
    
    for pattern in discount_patterns:
        match = re.search(pattern, block, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return None

def extract_offers(block: str) -> str:
    """Extract special offers"""
    offer_patterns = [
        r'(Buy\s+\d+\s+Get\s+\d+[^.\n]*)',          # Buy 1 Get 1
        r'(Free\s+[^.\n]{5,30})',                   # Free shipping, Free delivery
        r'(No\s+Cost\s+EMI[^.\n]*)',                # No Cost EMI
        r'(Express\s+delivery[^.\n]*)',             # Express delivery
        r'(Same\s+day\s+delivery[^.\n]*)',          # Same day delivery
        r'(Prime\s+eligible[^.\n]*)',               # Prime eligible
        r'(Limited\s+time\s+offer[^.\n]*)',         # Limited time offer
        r'(Special\s+price[^.\n]*)',                # Special price
    ]
    
    offers = []
    for pattern in offer_patterns:
        matches = re.findall(pattern, block, re.IGNORECASE)
        offers.extend([match.strip() for match in matches])
    
    return '; '.join(offers[:3]) if offers else None

def extract_link(block: str) -> str:
    """Extract product link"""
    link_pattern = r'\[([^\]]*)\]\((https?://[^\)]+)\)'
    match = re.search(link_pattern, block)
    return match.group(2) if match else None

def extract_image(block: str) -> str:
    """Extract product image"""
    image_pattern = r'!\[([^\]]*)\]\((https?://[^\)]+)\)'
    match = re.search(image_pattern, block)
    return match.group(2) if match else None

def extract_availability(block: str) -> str:
    """Extract availability status"""
    availability_patterns = [
        r'(In\s+stock)',
        r'(Out\s+of\s+stock)',
        r'(\d+\s+left\s+in\s+stock)',
        r'(Currently\s+unavailable)',
        r'(Available\s+now)',
        r'(Ships\s+in\s+\d+[^.\n]*)',
        r'(Delivery\s+by\s+[^.\n]*)',
        r'(Available\s+for\s+delivery)',
    ]
    
    for pattern in availability_patterns:
        match = re.search(pattern, block, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None

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
        title = item.get("title", "No title")
        price = f"₹{item['price']:,}" if item.get("price") else "Price not available"
        
        print(f"\n{i}. 🛒 {title}")
        print(f"   💰 Price: {price}")
        
        if item.get("rating"):
            print(f"   ⭐ Rating: {item['rating']}")
        if item.get("discount"):
            print(f"   🏷️ Discount: {item['discount']}")
        if item.get("offers"):
            print(f"   🎁 Offers: {item['offers']}")
        if item.get("availability"):
            print(f"   📦 Availability: {item['availability']}")
        if item.get("link"):
            print(f"   🔗 Link: {item['link']}")
        
        print("-" * 80)
def save_to_dataframe(products: List[Dict], filename: str = "scraped_products.csv") -> None:
    """Save products to a CSV file using pandas"""
    if not products:
        print("📭 No products to save")
        return
        
    try:
        if ".csv" not in filename:
            filename = filename+".csv"
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

async def main():
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
            products = await url_scraper(url)
            
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
            structured = await query_llama(user_prompt)
            
            if not structured:
                print("❌ Could not parse your query. Please try again.")
                continue

            print("✅ Query parsed successfully!")
            
            questions = await ask_follow_up_questions(user_prompt, structured)
            if questions:
                print("\n🤖 I have a few questions to refine your search:")
                user_answers = []
                for q in questions:
                    ans = input(f"→ {q} ").strip()
                    user_answers.append(ans)
                structured = await refine_structured_query_with_answers(user_prompt, user_answers, structured)
                print("✅ Query refined with your answers!")

            structured["query"] = sanitize_query(structured.get("query", user_prompt))

            print("\n📋 Final Search Configuration:")
            print(json.dumps(structured, indent=2))

            print("\n🚀 Starting scraping process...")
            results = await run_crawl4ai_scraper(structured)
            
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
    asyncio.run(main())