import re
import urllib.parse
import json
import subprocess
from crawl4ai import *
from typing import List, Dict, Any
import requests
import asyncio
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs

# ========================
# Dynamic URL Generation Core
# ========================

class URLGenerator:
    def __init__(self):
        self.site_patterns = {}  # {domain: List[Pattern]}
        self.param_rules = {
            'search': ['q', 'k', 'search'],
            'price': ['min_price', 'max_price', 'price'],
            'category': ['cat', 'category']
        }
        self.param_order = ['search', 'price', 'category']

    def analyze_urls(self, domain: str, urls: List[str]) -> None:
        """Extract domain-specific URL patterns using regex"""
        patterns = []
        for url in urls:
            parsed = urlparse(url)
            path = parsed.path.split('/')
            params = parse_qs(parsed.query)
            
            # Simple pattern extraction (enhance with ML)
            path_pattern = re.sub(r'\d+', '{id}', '/'.join(path))
            query_pattern = re.sub(r'[\d_]+', '{value}', parsed.query)
            
            patterns.append(f"{path_pattern}?{query_pattern}" if query_pattern else path_pattern)
        
        self.site_patterns[domain] = list(set(patterns))

    def generate_url(self, domain: str, query: str, params: Dict[str, str]) -> str:
        """Construct URL using learned patterns and parameter rules"""
        base_url = f"https://{domain}"
        patterns = self.site_patterns.get(domain, [])
        
        search_query = urllib.parse.quote_plus(query)
        params_str = '&'.join([f"{k}={urllib.parse.quote_plus(v)}" for k, v in params.items()])

        return f"{base_url}/s?k={search_query}&{params_str}".strip('&')

    def apply_params(self, pattern: str, params: Dict[str, str]) -> str:
        """Apply parameters to URL pattern"""
        # Replace {id}, {value} placeholders
        for key, val in params.items():
            placeholder = self.get_param_placeholder(key)
            pattern = pattern.replace(placeholder, self.normalize_param(key, val))
        return pattern

    def get_param_placeholder(self, key: str) -> str:
        """Determine parameter placeholder syntax"""
        return '{' + self.param_rules.get(key, [key])[0] + '}'

    def normalize_param(self, key: str, value: str) -> str:
        """Normalize parameter syntax"""
        param_key = self.param_rules.get(key, [key])[0]
        return f"{param_key}={urllib.parse.quote_plus(value)}"

    def fallback_url(self, domain: str, query: str, params: Dict[str, str]) -> str:
        """Basic search URL construction"""
        base = f"https://{domain}/"
        query_str = urllib.parse.quote_plus(query)
        params_str = '&'.join([f"{k}={urllib.parse.quote_plus(v)}" for k, v in params.items()])
        return f"{base}search?q={query_str}&{params_str}".strip('&')

# ========================
# Integration with Existing System
# ========================

class EnhancedScraper:
    def __init__(self):
        self.url_generator = URLGenerator()
        self.load_patterns()  # Load pre-trained patterns

    def load_patterns(self) -> None:
        """Load initial URL patterns (replace with ML training)"""
        self.url_generator.site_patterns = {
            "amazon.in": ["s?k={}", "dp/{id}?th=1&psc=1"],
            "flipkart.com": ["search?q={}", "p/{id}"]
        }

    def build_source_url(self, domain: str, query: str, params: Dict[str, str] = {}) -> str:
        """Generate domain-specific URL"""
        if domain == 'amazon' and 'amazon' not in domain:
            domain == 'amazon.in'

        if domain == 'flipkart' and 'flipkart' not in domain:
            domain == 'flipkart.com'
        return self.url_generator.generate_url(domain, query, params)

    def sanitize_query(self, text: str) -> str:
        """Enhanced query sanitization"""
        text = re.sub(r'(under|above|over|below)\s+₹?\s*[\d,]+', '', text, flags=re.I)
        text = re.sub(r'\b(at|on|from)\s+(amazon|flipkart|croma|tatacliq)\b', '', text, flags=re.I)
        text = re.sub(r'₹|rs\.?|inr', '', text, flags=re.I)
        return re.sub(r'\s+', ' ', text).strip()

    def validate_url(self, domain: str, url: str) -> bool:
        """Basic URL validation"""
        try:
            parsed = urlparse(url)
            return parsed.netloc.endswith(domain) and parsed.scheme == 'https'
        except:
            return False

# ========================
# Enhanced Scraper Implementation
# ========================

class EnhancedProductScraper:
    def __init__(self):
        self.scraper = EnhancedScraper()
        self.browser_config = BrowserConfig(
            headless=False,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        )
        self.run_config = CrawlerRunConfig(
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

    async def run_crawl4ai_scraper(self, structured: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Enhanced scraping with dynamic URL generation"""
        domain = structured.get("site", "duckduckgo").lower()
        source_url = self.scraper.build_source_url(domain, structured['query'], structured.get('params', {}))
        
        try:
            async with AsyncWebCrawler(config=self.browser_config) as crawler:
                result = await crawler.arun(url=source_url, config=self.run_config)
            
            if not result.success:
                print(f"❌ Crawling failed: {result.error_message}")
                return []
            
            return self.parse_products_from_markdown(
                result.markdown, 
                structured.get("min_price", 0),
                structured.get("max_price", 999999)
            )
        except Exception as e:
            print(f"⚠️ Scraping error: {str(e)}")
            return []

    def parse_products_from_markdown(self, markdown: str, min_price: int, max_price: int) -> List[Dict[str, Any]]:
        """Enhanced product parsing with validation"""
        products = []
        product_block_pattern = re.compile(
            r'(?:^|\n)(?P<title>(?:#+\s*|\d+\.\s+|\*{2})\s*(.*?))\s*\n' 
            r'(?:.*?)(?P<price>₹\s*[\d,]+|Rs\.\s*[\d,]+|INR\s*[\d,]+)'  
            r'(?:.*?)(?P<link>\[[^\]]*\]\(https?:\/\/[^\)]+\))?'  
            r'(?:.*?)(?P<image>!\[[^\]]*\]\(https?:\/\/[^\)]+\))?', 
            re.DOTALL
        )
        
        for match in product_block_pattern.finditer(markdown):
            title = re.sub(r'^[#\d\.\*\s]+', '', match.group(1)).strip()
            price_str = re.search(r'[\d,]+', match.group('price')).group().replace(',', '')
            price = int(price_str) if price_str else 0
            
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

# ========================
# Main Execution
# ========================
    
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

        if json_match:
            try:
              result = json.loads(json_match.group(0))
              return result
            except json.JSONDecodeError as e:
                print(f"JSON Parse error: {str(e)}")
        return previous_query
    except Exception as e:
        print(f"Failed to refine structured query: {e}")
        return previous_query

def query_llama(user_input: str) -> Dict[str, Any]:
    """Ollama integration for structured query extraction"""
    try:
        process = subprocess.run(
            ["ollama", "run", "query-llama"],
            input=user_input,
            text=True,
            capture_output=True,
            timeout=30
        )
        stdout = process.stdout
        
        json_match = re.search(r'\{[\s\S]*\}', stdout)
        if not json_match:
            raise ValueError("No JSON found in LLM output")
            
        result = json.loads(json_match.group(0))
        result['max_price'] = result.get('max_price', 99999)
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

def main():
    print("🛒 Enhanced Smart Product Scraper")
    scraper = EnhancedProductScraper()
    
    while True:
        user_input = input("\n🔍 What would you like to scrape? (or type 'exit')\n→ ")
        if user_input.lower() == 'exit':
            print("Bye bye! ^_^")
            break
            
        structured = query_llama(user_input)
        if not structured:
            print("❌ Could not parse your query. Please try again.")
            continue
        
        # Enhanced flow: Add parameter handling
        questions = ask_follow_up_questions(user_input, structured)
        if questions:
            print("\n I have a few questions to refine your search...")
            user_answers = []
            for q in questions:
                ans = input(f"→ {q} ")
                user_answers.append(ans.strip())
            
            structured = refine_structured_query_with_answers(user_input, user_answers, structured)
        
        structured["query"] = scraper.scraper.sanitize_query(structured["query"])
        structured["site"] = structured.get("site", "amazon")

        print("\n📋 Final Structured Query:")
        print(json.dumps(structured, indent=2))
        
        results = asyncio.run(scraper.run_crawl4ai_scraper(structured))
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
