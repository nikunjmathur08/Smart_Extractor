"""
Smart Web Extractor - Terminal Application
A tool that uses local LLM to extract live data from websites
"""

import requests
import json
import re
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import argparse
import sys
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class Product:
    name: str
    price: str
    price_numeric: int  # Add numeric price for sorting
    url: str
    rating: Optional[str] = None
    image_url: Optional[str] = None

class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.2:3b"):
        self.base_url = base_url
        self.model = model
        self.session = requests.Session()
    
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Generate response from Ollama"""
        try:
            url = f"{self.base_url}/api/generate"
            payload = {
                "model": self.model,
                "prompt": prompt,
                "system": system_prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "top_p": 0.9
                }
            }
            
            response = self.session.post(url, json=payload, timeout=60)
            if response.status_code == 200:
                return response.json()["response"]
            else:
                return f"Error: {response.status_code} - {response.text}"
        except Exception as e:
            return f"Error connecting to Ollama: {str(e)}"

class WebScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
    
    def clean_product_name(self, name: str) -> str:
        """Clean product name by extracting meaningful part"""
        if not name:
            return "N/A"
        
        # Remove extra whitespace and newlines
        name = ' '.join(name.split())
        
        # If there's a closing bracket, extract up to it
        if ')' in name:
            bracket_pos = name.find(')')
            cleaned_name = name[:bracket_pos + 1].strip()
            if len(cleaned_name) > 10:  # Only use if meaningful length
                return cleaned_name
        
        # Limit length to avoid very long names
        if len(name) > 100:
            name = name[:100] + "..."
            
        return name.strip()
    
    def extract_price_from_text(self, text: str) -> int:
        """Extract numeric price from text"""
        if not text:
            return 0
        
        # Remove currency symbols and commas
        price_text = re.sub(r'[₹,\s]', '', text)
        
        # Extract numbers
        numbers = re.findall(r'\d+', price_text)
        if numbers:
            # Take the first number found
            return int(numbers[0])
        return 0
    
    def scrape_amazon_products(self, search_term: str, min_price: int = 0, max_price: int = 100000, sort_order: str = "asc") -> List[Product]:
        """Scrape Amazon for products within price range"""
        products = []
        
        # Multiple search strategies
        search_urls = [
            f"https://www.amazon.in/s?k={search_term.replace(' ', '+')}&ref=sr_pg_1",
            f"https://www.amazon.in/s?k={search_term.replace(' ', '%20')}&sort=price-asc-rank" if sort_order == "asc" else f"https://www.amazon.in/s?k={search_term.replace(' ', '%20')}&sort=price-desc-rank"
        ]
        
        for search_url in search_urls:
            try:
                print(f"   Trying URL: {search_url}")
                response = self.session.get(search_url, timeout=15)
                
                if response.status_code != 200:
                    print(f"   HTTP {response.status_code}, trying next approach...")
                    continue
                    
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Multiple selectors for different Amazon layouts
                selectors = [
                    'div[data-component-type="s-search-result"]',
                    'div.s-result-item',
                    'div[data-index]',
                    'div.sg-col-inner'
                ]
                
                product_containers = []
                for selector in selectors:
                    containers = soup.select(selector)
                    if containers:
                        product_containers = containers
                        print(f"   Found {len(containers)} products using selector: {selector}")
                        break
                
                if not product_containers:
                    print("   No product containers found")
                    continue
                
                for container in product_containers:
                    try:
                        product = self.extract_product_info(container, search_term)
                        if product and min_price <= product.price_numeric <= max_price:
                            products.append(product)
                            
                    except Exception as e:
                        continue
                
                # If we found products, break out of URL loop
                if products:
                    break
                    
            except Exception as e:
                print(f"   Error with URL {search_url}: {str(e)}")
                continue
        
        # Remove duplicates based on name similarity
        products = self.remove_duplicates(products)
        
        # Sort products by price
        if sort_order == "desc":
            products.sort(key=lambda x: x.price_numeric, reverse=True)
        else:
            products.sort(key=lambda x: x.price_numeric)
        
        return products
    
    def extract_product_info(self, container, search_term: str) -> Optional[Product]:
        """Extract product information from a container element"""
        try:
            # Extract product name with multiple strategies
            name = self.extract_product_name(container)
            if not name or name == "N/A":
                return None
            
            # Extract price with multiple strategies
            price_numeric = self.extract_product_price(container)
            if price_numeric == 0:
                return None
            
            # Extract URL
            url = self.extract_product_url(container)
            
            # Extract rating
            rating = self.extract_product_rating(container)
            
            return Product(
                name=name,
                price=f"₹{price_numeric:,}",
                price_numeric=price_numeric,
                url=url,
                rating=rating
            )
            
        except Exception as e:
            return None
    
    def extract_product_name(self, container) -> str:
        """Extract product name using multiple strategies"""
        # Strategy 1: Common product title selectors
        name_selectors = [
            'a-size-medium',
        ]
        
        for selector in name_selectors:
            elements = container.select(selector)
            for element in elements:
                text = element.get_text().strip()
                if text and len(text) > 5:  # Meaningful name length
                    return self.clean_product_name(text)
        
        # Strategy 2: Look for any meaningful text in links
        links = container.find_all('a', href=True)
        for link in links:
            if '/dp/' in link.get('href', ''):
                text = link.get_text().strip()
                if text and len(text) > 10:
                    return self.clean_product_name(text)
        
        return "N/A"
    
    def extract_product_price(self, container) -> int:
        """Extract product price using multiple strategies"""
        # Strategy 1: Common price selectors
        price_selectors = [
            '.a-price-whole',
            '.a-price .a-offscreen',
            '.a-price-range .a-offscreen',
            '.a-price-symbol + .a-price-whole',
            'span.a-price-whole',
            '.s-price-range-separator',
            '.a-price'
        ]
        
        for selector in price_selectors:
            elements = container.select(selector)
            for element in elements:
                price_text = element.get_text().strip()
                price_num = self.extract_price_from_text(price_text)
                if price_num > 0:
                    return price_num
        
        # Strategy 2: Look for any text containing price patterns
        all_text = container.get_text()
        price_patterns = [
            r'₹\s*(\d{1,3}(?:,\d{3})*)',
            r'Rs\.?\s*(\d{1,3}(?:,\d{3})*)',
            r'INR\s*(\d{1,3}(?:,\d{3})*)'
        ]
        
        for pattern in price_patterns:
            matches = re.findall(pattern, all_text)
            for match in matches:
                price_num = int(match.replace(',', ''))
                if 100 <= price_num <= 1000000:  # Reasonable price range
                    return price_num
        
        return 0
    
    def extract_product_url(self, container) -> str:
        """Extract product URL"""
        # Look for product detail page links
        links = container.find_all('a', href=True)
        for link in links:
            href = link.get('href', '')
            if '/dp/' in href or '/gp/product/' in href:
                return urljoin("https://www.amazon.in", href)
        return "N/A"
    
    def extract_product_rating(self, container) -> str:
        """Extract product rating"""
        # Common rating selectors
        rating_selectors = [
            '.a-icon-alt',
            '.a-star-mini .a-icon-alt',
            'span[aria-label*="out of"]'
        ]
        
        for selector in rating_selectors:
            elements = container.select(selector)
            for element in elements:
                text = element.get('aria-label', '') or element.get_text()
                if 'out of' in text or 'stars' in text:
                    # Extract rating number
                    rating_match = re.search(r'(\d+\.?\d*)', text)
                    if rating_match:
                        return f"{rating_match.group(1)}/5"
        
        return "N/A"
    
    def remove_duplicates(self, products: List[Product]) -> List[Product]:
        """Remove duplicate products based on name similarity"""
        if not products:
            return products
        
        unique_products = []
        seen_names = set()
        
        for product in products:
            # Create a normalized name for comparison
            normalized_name = re.sub(r'[^\w\s]', '', product.name.lower())
            normalized_name = ' '.join(normalized_name.split()[:5])  # First 5 words
            
            if normalized_name not in seen_names:
                seen_names.add(normalized_name)
                unique_products.append(product)
        
        return unique_products

class SmartExtractor:
    def __init__(self, model_name: str = "llama3:8b-instruct-q8_0"):
        self.llm = OllamaClient(model=model_name)
        self.scraper = WebScraper()
    
    def parse_query(self, user_query: str) -> Dict:
        """Parse user query to extract intent, platform, product, price range, and sort order"""
        system_prompt = """You are an expert e-commerce query parser. Extract structured information from natural language shopping queries.

        Extract these fields: platform, product_type, min_price, max_price, sort_order, additional_filters

        RULES:
        1. Convert 'k' notation to full numbers (20k = 20000)
        2. Use default price ranges if not specified
        3. Normalize product types
        4. Detect sort order from phrases like "most expensive", "highest price", "cheapest", "lowest price"
        5. Return ONLY valid JSON

        PLATFORM MAPPING:
        - amazon/amazon.in → "amazon"
        - flipkart → "flipkart" 
        - Default → "amazon"

        PRODUCT CATEGORIES:
        - phones/smartphones/mobile → "smartphones"
        - laptops/computers → "laptops"
        - earbuds/headphones → "audio"
        - Default → "products"

        SORT ORDER:
        - "most expensive", "highest price", "starting from expensive" → "desc"
        - "cheapest", "lowest price", "starting from cheap" → "asc"
        - Default → "asc"

        EXAMPLES:
        Input: "Give me all phones under 100000 on amazon starting from the most expensive ones"
        Output: {"platform": "amazon", "product_type": "smartphones", "min_price": 0, "max_price": 100000, "sort_order": "desc", "additional_filters": []}

        Input: "Show cheapest gaming laptops under 80000"
        Output: {"platform": "amazon", "product_type": "laptops", "min_price": 0, "max_price": 80000, "sort_order": "asc", "additional_filters": ["gaming"]}"""
        
        response = self.llm.generate(user_query, system_prompt)
        
        try:
            # Clean and extract JSON from response
            cleaned_response = response.strip()
            
            # Remove any leading/trailing text around JSON
            json_start = cleaned_response.find('{')
            json_end = cleaned_response.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                json_str = cleaned_response[json_start:json_end]
                parsed_result = json.loads(json_str)
                
                # Validate required fields
                required_fields = ["platform", "product_type", "min_price", "max_price"]
                if all(field in parsed_result for field in required_fields):
                    # Ensure sort_order field exists
                    if "sort_order" not in parsed_result:
                        parsed_result["sort_order"] = "asc"
                    return parsed_result
            
            # If JSON parsing fails, try the fallback
            return self._fallback_parse(user_query)
            
        except json.JSONDecodeError as e:
            print(f"JSON parsing failed: {e}")
            return self._fallback_parse(user_query)
        except Exception as e:
            print(f"Unexpected error in query parsing: {e}")
            return self._fallback_parse(user_query)
    
    def _fallback_parse(self, query: str) -> Dict:
        """Fallback parsing when LLM fails"""
        result = {
            "platform": "amazon",
            "product_type": "products",
            "min_price": 0,
            "max_price": 100000,
            "sort_order": "asc"
        }
        
        # Detect sort order
        query_lower = query.lower()
        if any(phrase in query_lower for phrase in ["most expensive", "highest price", "starting from expensive", "expensive first"]):
            result["sort_order"] = "desc"
        elif any(phrase in query_lower for phrase in ["cheapest", "lowest price", "starting from cheap", "cheap first"]):
            result["sort_order"] = "asc"
        
        # Extract price range - handle both "to" and "and" patterns
        price_patterns = [
            r'(\d+)k?\s*(?:to|and)\s*(\d+)k?',
            r'between\s+(\d+)k?\s*(?:to|and)\s*(\d+)k?',
            r'(\d+)k?\s*-\s*(\d+)k?'
        ]
        
        for pattern in price_patterns:
            price_match = re.search(pattern, query.lower())
            if price_match:
                min_p = int(price_match.group(1))
                max_p = int(price_match.group(2))
                result["min_price"] = min_p * 1000 if min_p < 1000 else min_p
                result["max_price"] = max_p * 1000 if max_p < 1000 else max_p
                break
        
        # Also check for single price limits
        under_match = re.search(r'under\s+(\d+)k?', query.lower())
        if under_match:
            max_p = int(under_match.group(1))
            result["max_price"] = max_p * 1000 if max_p < 1000 else max_p
        
        # Extract product type
        if "phone" in query.lower() or "smartphone" in query.lower():
            result["product_type"] = "smartphones"
        elif "laptop" in query.lower():
            result["product_type"] = "laptops"
        
        # Extract platform
        if "flipkart" in query.lower():
            result["platform"] = "flipkart"
        
        return result
    
    def extract_data(self, query: str) -> List[Product]:
        """Main extraction method"""
        print("Parsing your query...")
        parsed = self.parse_query(query)
        print(f"Understood: {parsed}")
        
        print(f"Searching {parsed['platform']} for {parsed['product_type']}...")
        
        if parsed["platform"] == "amazon":
            products = self.scraper.scrape_amazon_products(
                parsed["product_type"],
                parsed["min_price"],
                parsed["max_price"],
                parsed.get("sort_order", "asc")
            )
        else:
            print(f"Platform {parsed['platform']} not yet supported")
            return []
        
        print(f"Found {len(products)} products matching criteria")
        return products
    
    def summarize_results(self, products: List[Product], original_query: str) -> str:
        """Generate intelligent summary of results - SIMPLIFIED VERSION"""
        if not products:
            return "No products found matching your criteria."
        
        # Create a simple summary without complex LLM processing
        avg_price = sum(p.price_numeric for p in products) / len(products)
        min_price = min(p.price_numeric for p in products)
        max_price = max(p.price_numeric for p in products)
        
        # Count products with ratings
        rated_products = [p for p in products if p.rating != "N/A"]
        
        summary = f"""SEARCH RESULTS SUMMARY:
                
        • Found {len(products)} products matching your criteria
        • Price Range: ₹{min_price:,} - ₹{max_price:,}
        • Average Price: ₹{avg_price:,.0f}
        • Products with ratings: {len(rated_products)}/{len(products)}

        TOP RECOMMENDATIONS:"""
        
        # Add top 3 products
        for i, product in enumerate(products[:3], 1):
            summary += f"\n{i}. {product.name[:50]}{'...' if len(product.name) > 50 else ''}"
            summary += f"\n   {product.price} | {product.rating}\n"
        
        return summary

def main():
    parser = argparse.ArgumentParser(description="Smart Web Extractor")
    parser.add_argument("--model", default="llama3:8b-instruct-q8_0", help="Ollama model to use")
    parser.add_argument("--query", help="Direct query to process")
    args = parser.parse_args()
    
    print("Smart Web Extractor v2.0 - FIXED VERSION")
    print("=" * 50)
    
    extractor = SmartExtractor(args.model)
    
    # Test Ollama connection
    print("Testing Ollama connection...")
    test_response = extractor.llm.generate("Hello", "Respond with just 'OK' if you're working.")
    if "error" in test_response.lower():
        print("Ollama connection failed. Make sure Ollama is running and the model is installed.")
        print(f"   Run: ollama pull {args.model}")
        sys.exit(1)
    print("Ollama connected successfully!")
    
    if args.query:
        # Process single query
        products = extractor.extract_data(args.query)
        
        if products:
            print(f"\nFound {len(products)} products:")
            print("-" * 80)
            for i, product in enumerate(products[:20], 1):  # Limit to top 20
                print(f"{i:2d}. {product.name[:70]}")
                print(f"     {product.price} | {product.rating}")
                if product.url != "N/A":
                    print(f"     {product.url[:70]}...")
                print()
            
            # Generate AI summary
            print("AI Analysis:")
            print("-" * 40)
            summary = extractor.summarize_results(products, args.query)
            print(summary)
        else:
            print("No products found matching your criteria.")
    
    else:
        # Interactive mode
        print("\nInteractive Mode - Type your queries below:")
        print("Example: 'Give me all phones under 99k on amazon'")
        print("Type 'quit' to exit\n")
        
        while True:
            try:
                query = input("Your query: ").strip()
                
                if query.lower() in ['quit', 'exit', 'q']:
                    print("Goodbye!")
                    break
                
                if not query:
                    continue
                
                print("\n" + "="*60)
                start_time = time.time()
                
                products = extractor.extract_data(query)
                
                if products:
                    print(f"\nFound {len(products)} products:")
                    print("-" * 80)
                    for i, product in enumerate(products[:10], 1):  # Show top 10
                        print(f"{i:2d}. {product.name[:60]}")
                        print(f"     {product.price} | {product.rating}")
                        if product.url != "N/A":
                            print(f"     {product.url[:70]}...")
                        print()
                    
                    if len(products) > 10:
                        print(f"... and {len(products) - 10} more products")
                    
                    # Generate AI summary
                    print("AI Analysis:")
                    print("-" * 40)
                    summary = extractor.summarize_results(products, query)
                    print(summary)
                else:
                    print("No products found matching your criteria.")
                
                elapsed = time.time() - start_time
                print(f"\nCompleted in {elapsed:.2f} seconds")
                print("="*60 + "\n")
                
            except KeyboardInterrupt:
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"Error: {str(e)}")

if __name__ == "__main__":
    main()