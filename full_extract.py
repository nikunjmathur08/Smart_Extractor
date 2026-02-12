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
from concurrent.futures import ThreadPoolExecutor

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
    print(f"\nDEBUG: Calling model '{model}' with prompt length: {len(prompt)}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=120) as response:
                print(f"\nDEBUG: HTTP status: {response.status}")
                response.raise_for_status()
                if stream:
                    output = ""
                    async for line in response.content.iter_any():
                        if line:
                            chunk = json.loads(line.decode("utf-8"))
                            output += chunk.get("response", "")
                    print(f"\nDEBUG: Stream response length: {len(output)}")
                    return output
                else:
                    data = await response.json()
                    response_text = data.get('response', '')
                    print(f"\nDEBUG: Response length: {len(response_text)}")
                    print(f"\nDEBUG: Response preview: {response_text[:200]}...\n")
                    return response_text
    except Exception as e:
        print(f"Error calling Ollama for model {model}: {str(e)}")
        return ""

async def extract_detailed_product_info(blocks: List[str], keywords: list) -> List[Dict]:
    """Extract products using LLM and regex as fallback"""
    try:
        print("\nDEBUG: Sending data to LLM...")
        print("\nDEBUG: Please wait...")

        chunks = dynamic_chunk(blocks, max_chars=6000)
        print(f"\nDEBUG: Created {len(chunks)} chunks using dynamic_chunk()")

        tasks = []
        for i, chunk in enumerate(chunks, 1):
            print(f"\nDEBUG: Queuing chunk {i}/{len(chunks)} with {len(chunk)} blocks")
            task = extract_with_llm(chunk, keywords)
            tasks.append(task)
        
        chunk_results = await asyncio.gather(*tasks, return_exceptions=True)

        all_llm_products = []

        for i, result in enumerate(chunk_results, 1):
            if isinstance(result, Exception):
                print(f"\nDEBUG: Chunk {i} failed: {str(result)}")
                continue
            if result:
                all_llm_products.extend(result)
                print(f"\nDEBUG: Chunk {i} yielded {len(result)} products")
        
        if all_llm_products:
            print("\n DEBUG: LLM extraction successful!")
            return all_llm_products
    except Exception as e:
        print(f"\n DEBUG: LLM extraction failed {str(e)}, using regex instead")
    
    markdown = "\n\n".join(blocks)
    regex_products = extract_products_from_markdown(markdown, keywords)
    
    print(f"DEBUG: Regex extracted {len(regex_products)} products")
    for product in regex_products:
        print(f"DEBUG: {product['title']} - ₹{product['price']:,}")
    
    return regex_products

async def extract_with_llm(markdown: str, keywords: list) -> List[Dict]:
    """Try extraction with LLM"""
    joined = "\n\n---\n\n".join(markdown)
    prompt = f"""
    You are a precise product data extraction expert.
    Carefully analyze the product blocks below separated by '---'.
    Extract for each product: title, price (numeric), rating, tags (list), offers, discounts, quantity, category_properties.
    Output ONLY a JSON array of products.
    Filter products related to keywords: {', '.join(keywords)}.

    Blocks:
    {joined[:4000]}
    """

    response = await ask_ollama("extract-details", prompt)
    if not response.strip():
        raise ValueError("Empty LLM response")
    
    try:
        json_start = -1
        for i, char in enumerate(response):
            if char in '[{':
                json_start = i
                break
        
        if json_start == -1:
            raise ValueError("No JSON structure found in response")
        
        json_text = response[json_start:].strip()

        data = json.loads(json_text)
        if not isinstance(data, list):
            raise ValueError("Not a JSON array")
        
        for product in data:
            price = product.get('price')
            if isinstance(price, (int, float)):
                product['price'] = int(price)
                continue
            if isinstance(price, str):
                price = re.sub(r'[^\\d]', '', price)
                try:
                    product['price'] = int(price)
                except ValueError:
                    product['price'] = None
            else:
                product['price'] = None

        filtered = [
            p for p in data
            if p.get('title') and (not keywords or any(k.lower() in p.get('title', '').lower() for k in keywords))
        ]

        return filtered
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"Invalid LLM response: {str(e)}")

def dynamic_chunk(blocks, max_chars = 8000):
    chunks = []
    current_chunk = []
    current_len = 0
    for block in blocks:
        if not looks_like_product_block(block):
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

def block_has_price(block: str) -> bool:
    """Detect common price formats in scraped text."""
    return bool(re.search(
        r'(?:₹|Rs\.?|INR|\$)\s*[\d,]+(?:\.\d+)?|(?:price|deal|offer)\s*[:\-]?\s*[\d,]+',
        block,
        re.IGNORECASE,
    ))

def looks_like_product_block(block: str, query_keywords: list = None) -> bool:
    """Allow product-like blocks even when price is missing in markdown."""
    if query_keywords is None:
        query_keywords = []

    text = block.strip()
    if len(text) < 120:
        return False

    text_lower = text.lower()
    has_query_keyword = bool(query_keywords and any(kw in text_lower for kw in query_keywords if len(kw) > 2))
    has_product_words = bool(re.search(
        r'\b(?:tv|television|inch|cm|uhd|fhd|oled|qled|smart|buy|price|offer|discount|deal|product|model|brand|ratings?|reviews?)\b',
        text_lower,
    ))
    has_product_link = bool(re.search(r'https?://[^\s\)]*(?:/dp/|/gp/aw/d/|/gp/product/|/s\?)', text))
    has_rating = bool(re.search(r'out of 5 stars|ratings?\b|reviews?\b', text_lower))
    has_price = block_has_price(text)

    if has_price:
        return True
    return (has_product_words or has_query_keyword) and (has_product_link or has_rating or len(text) >= 220)

def cleaned_markdown(markdown: str) -> str:
    """Removes noise from data scraped without erasing products.
    Only removes specific known-noise sections. Preserves paragraph/line structure
    so split_markdown_to_product_blocks can still split on blank lines."""
    noise_line_patterns = [
        r'^#*\s*Skip to\b',
        r'^#*\s*Keyboard shortcuts?\b',
        r'^\s*To move between items\b',
        r'^\s*Select the department you want to search in\b',
        r'^\s*Search Amazon\.in\s*$',
        r'^\s*(Need help\??|More results?|Show more|See all results?)\s*$',
        r'^\s*-?\d+\s+of\s+\d+\s+results?\s+for\s+.*$',
        r'^\s*©\s*1996-\d{4},\s*Amazon\.com.*$',
    ]

    cleaned_lines = []
    for line in markdown.splitlines():
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in noise_line_patterns):
            continue
        cleaned_lines.append(line.rstrip())

    cleaned = "\n".join(cleaned_lines)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()

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

    async def scrape_single_page(crawler, url, page_num):
        """Scrape single page asynchronously"""
        try:
            print(f"Scraping page {page_num}: {url}")
            result = await crawler.arun(url=url, config=run_conf)

            if not result or not result.success:
                print(f"Failed to scrape page {page_num}")
                return []
            
            asyncio.create_task(write_debug_file(f"debug_page_{page_num}.md", result.markdown))

            # Clean the markdown first to remove navigation and noise
            clean_md = cleaned_markdown(result.markdown)
            
            keywords = structured.get('query', '').lower().split()
            product_blocks = split_markdown_to_product_blocks(clean_md, keywords)

            if not product_blocks:
                print(f"No product blocks found from page {page_num}")
                return []
            
            asyncio.create_task(write_debug_file(f"product_block_{page_num}.md", "\n\n---\n\n".join(product_blocks)))

            detailed_products = await extract_detailed_product_info(product_blocks, keywords)

            page_products = []
            for product in detailed_products:
                if product and product.get('title'):
                    title_lower = product['title'].lower()
                    if any(kw in title_lower for kw in keywords):
                        price = product.get('price')
                        min_price = structured.get('min_price', 0)
                        max_price = structured.get('max_price', 999999)
                        if price is None and min_price <= 0:
                            page_products.append(product)
                        elif isinstance(price, (int, float)) and min_price <= price <= max_price:
                            page_products.append(product)
            
            # Apply post-processing filter to remove navigation/UI elements
            page_products = filter_valid_products(page_products)
            
            print(f"✅ Found {len(page_products)} valid products on page {page_num}")
            return page_products
        except Exception as e:
            print(f"Error scraping page {page_num}: {e}")
            return []

    try:
        async with AsyncWebCrawler(config=browser_conf) as crawler:
            tasks = []
            for i, url in enumerate(paginated_urls, start=1):
                task = scrape_single_page(crawler, url, i)
                tasks.append(task)
            
            page_results = await asyncio.gather(*tasks, return_exceptions=True)

            all_products = []
            for i, result in enumerate(page_results, 1):
                if isinstance(result, Exception):
                    print(f"Page {i} failed: {result}")
                    continue
                if result:
                    all_products.extend(result)
            
            print(f"Total products found: {len(all_products)}")
            return all_products
    except Exception as e:
        print(f"⚠️ Scraping error: {str(e)}")
        return []

async def write_debug_file(filename: str, content: str):
    """Async file writing to avoid blocking"""
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content or '')
    except Exception as e:
        print(f"\nDEBUG: Failed to write {filename}: {e}")

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
            detailed_products = await extract_detailed_product_info(product_blocks, [])
            products = []
            for product in detailed_products:
                if product and product.get('title'):
                    price = product.get('price')
                    if price is None and min_price <= 0:
                        products.append(product)
                    elif isinstance(price, (int, float)) and min_price <= price <= max_price:
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
        r'results? for', r'advertisement', r'cookies',
        r'privacy policy', r'terms of service', r'copyright', r'©.*\d{4}',
        r'update location', r'delivering to', r'change address',
        r'^\d+\s*of\s*\d+\s*results?', r'^-?\d+\s*of\s*\d+\s*results?',  # "16 of 75 results"
        r'^more results?$', r'^need help\??$', r'^customer reviews?$',
        r'^show more$', r'^see all$', r'^view all$',
        r'^page \d+', r'^\d+\s*-\s*\d+\s*of\s*\d+',  # Pagination
        r'^home\s*›', r'^›', r'breadcrumb',  # Navigation breadcrumbs
        r'^sign in$', r'^cart$', r'^checkout$',
        r'^let us know$', r'^sponsored\s*sponsored$'
    ]

    for block in blocks:
        block = block.strip()
        # Increased minimum length from 30 to 80 characters
        if len(block) < 80:
            continue

        is_noise = any(re.search(pattern, block, re.IGNORECASE) for pattern in noise_patterns)
        if is_noise:
            continue

        has_price = block_has_price(block)
        has_product_words = bool(re.search(r'\b(?:buy|price|offer|discount|sale|deal|product|item|model|brand|available|stock|delivery|shipping|stars?|ratings?|reviews?)\b', block, re.IGNORECASE))
        has_query_keyword = bool(query_keywords and any(kw in block.lower() for kw in query_keywords))
        has_product_shape = looks_like_product_block(block, query_keywords)

        if has_price and (len(block) >= 180 or has_product_words or has_query_keyword):
            filtered_blocks.append(block)
        elif has_product_shape:
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
        r'\[([^\]]{25,120})\]\(https?://[^\)]+\)',      # [Product Title](https://...) - increased from 15 to 25
        
        # Text near prices (common pattern)
        r'([A-Z][^₹\n\[\]]{25,120})\s*[₹$]\s*[\d,]+',   # "Product Name ₹1,234" - increased from 15 to 25
        r'[₹$]\s*[\d,]+\s*([A-Z][^₹\n\[\]]{25,120})',   # "₹1,234 Product Name" - increased from 15 to 25
        
        # Sentences that look like product descriptions
        r'([A-Z][^.\n]{25,120}(?:with|featuring|equipped|includes)[^.\n]{5,50})', # Descriptive titles
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
            
            # Require minimum length of 25 chars (stricter than before)
            if len(candidate) < 25:
                continue
            
            # Require at least 3 words
            words = [w for w in candidate.split() if len(w) > 1]
            if len(words) < 3:
                continue
            
            # Score the candidate based on how "product-like" it is
            score = 0
            
            # Length bonus (not too short, not too long)
            if 25 <= len(candidate) <= 100:
                score += 3  # Increased from 2
            
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
            
            # Penalize navigation/generic text (stricter penalties)
            bad_indicators = [
                'select', 'department', 'category', 'filter', 'sort', 'results',
                'your lists', 'account', 'cart', 'checkout', 'sign in', 'skip',
                'more', 'need help', 'customer review'
            ]
            penalty = sum(3 for bad in bad_indicators if bad in candidate.lower())  # Increased penalty from 2 to 3
            score -= penalty
            
            # Additional penalty for very generic/short phrases
            if len(words) < 5:
                score -= 1
            
            # Choose the best title (increased threshold from 0 to 2)
            if score > best_score and score > 2:
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
            print(f"   🏷️  Discount: {item['discount']}")
        if item.get("offers"):
            print(f"   🎁 Offers: {item['offers']}")
        if item.get("availability"):
            print(f"   📦 Availability: {item['availability']}")
        if item.get("link"):
            print(f"   🔗 Link: {item['link']}")
        
        print("-" * 80)

def filter_valid_products(products: List[Dict]) -> List[Dict]:
    """Post-processing filter to remove obvious non-products and navigation elements"""
    if not products:
        return []
    
    valid_products = []
    
    # UI/Navigation patterns that should never appear as product titles
    invalid_title_patterns = [
        r'^skip\s+to',
        r'^more\s+results?$',
        r'^need\s+help\??$',
        r'^\d+\s*of\s*\d+\s*results?',  # "16 of 75 results"
        r'^-?\d+\s*of\s*\d+\s*results?',  # "-16 of 75 results"
        r'^customer\s+reviews?$',
        r'^show\s+more$',
        r'^see\s+all$',
        r'^view\s+all$',
        r'^page\s+\d+',
        r'^sign\s+in$',
        r'^cart$',
        r'^checkout$',
        r'^home\s*›',
        r'^›',
        r'^\[.*›.*›.*\]',  # Breadcrumb links
    ]
    
    for product in products:
        title = product.get('title', '').strip()
        price = product.get('price')
        
        # Validation checks
        if not title or len(title) < 25:
            continue
        
        # Title must have at least 3 words
        word_count = len([w for w in title.split() if len(w) > 1])
        if word_count < 3:
            continue
        
        # Check against invalid patterns
        is_invalid = any(re.search(pattern, title, re.IGNORECASE) for pattern in invalid_title_patterns)
        if is_invalid:
            continue
        
        # If price exists, ensure it is reasonable. Missing price is allowed.
        if price is not None:
            if not isinstance(price, (int, float)):
                continue
            if price < 50 or price > 10000000:  # ₹50 to ₹1 crore
                continue
        
        # Title should contain at least one product-type word
        product_type_words = [
            'laptop', 'phone', 'tablet', 'watch', 'camera', 'speaker', 'headphone',
            'machine', 'cleaner', 'washer', 'dryer', 'refrigerator', 'tv', 'monitor',
            'mouse', 'keyboard', 'router', 'modem', 'charger', 'cable', 'adapter',
            'bag', 'case', 'cover', 'stand', 'holder', 'mount', 'kit', 'set',
            'apple', 'samsung', 'lg', 'dell', 'hp', 'lenovo', 'asus', 'sony',
            'pro', 'plus', 'max', 'ultra', 'premium', 'edition', 'series', 'model',
            'gb', 'tb', 'inch', 'core', 'gen', '5g', '4g', 'wireless', 'bluetooth'
        ]
        
        title_lower = title.lower()
        has_product_indicator = any(word in title_lower for word in product_type_words)
        
        if not has_product_indicator:
            # If no product indicator, be more strict with length
            if len(title) < 40:
                continue
        
        valid_products.append(product)
    
    print(f"Filtered {len(products)} -> {len(valid_products)} valid products")
    return valid_products

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
