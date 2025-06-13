#!/usr/bin/env python3
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
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
    
    def scrape_amazon_products(self, search_term: str, min_price: int = 0, max_price: int = 100000) -> List[Product]:
        """Scrape Amazon for products within price range"""
        products = []
        
        # Amazon search URL
        search_url = f"https://www.amazon.in/s?k={search_term.replace(' ', '+')}&ref=sr_pg_1"
        
        try:
            response = self.session.get(search_url)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find product containers
            product_containers = soup.find_all('div', {'data-component-type': 's-search-result'})
            
            for container in product_containers:
                try:
                    # Extract product name - try multiple selectors
                    name_elem = container.find('h2', class_='a-size-mini')
                    if not name_elem:
                        name_elem = container.find('span', class_='a-size-medium')
                    if not name_elem:
                        name_elem = container.find('h2')
                    if not name_elem:
                        name_elem = container.find('a', {'class': 'a-link-normal'})
                    
                    name = "N/A"
                    if name_elem:
                        # Get text from the element or its child elements
                        name_text = name_elem.get_text().strip()
                        if name_text:
                            name = name_text
                        elif name_elem.find('span'):
                            name = name_elem.find('span').get_text().strip()
                    
                    # Extract price
                    price_elem = container.find('span', class_='a-price-whole')
                    if not price_elem:
                        price_elem = container.find('span', class_='a-offscreen')
                    
                    if price_elem:
                        price_text = price_elem.get_text().strip()
                        # Extract numeric price
                        price_num = int(re.sub(r'[^\d]', '', price_text)) if re.search(r'\d', price_text) else 0
                        
                        # Check if price is within range
                        if min_price <= price_num <= max_price:
                            # Extract product URL
                            link_elem = container.find('h2').find('a') if container.find('h2') else None
                            product_url = urljoin("https://www.amazon.in", link_elem['href']) if link_elem else "N/A"
                            
                            # Extract rating
                            rating_elem = container.find('span', class_='a-icon-alt')
                            rating = rating_elem.get_text().split()[0] if rating_elem else "N/A"
                            
                            products.append(Product(
                                name=name,
                                price=f"₹{price_num:,}",
                                url=product_url,
                                rating=rating
                            ))
                            
                except Exception as e:
                    continue
                    
        except Exception as e:
            print(f"Error scraping Amazon: {str(e)}")
        
        return products

class SmartExtractor:
    def __init__(self, model_name: str = "llama3:8b-instruct-q8_0"):
        self.llm = OllamaClient(model=model_name)
        self.scraper = WebScraper()
    
    def parse_query(self, user_query: str) -> Dict:
        """Parse user query to extract intent, platform, product, and price range"""
        system_prompt = """<|begin_of_text|><|start_header_id|>system<|end_header_id|>

You are an expert e-commerce query parser. Your task is to extract structured information from natural language shopping queries.

## EXTRACTION RULES:
1. Extract these fields: platform, product_type, min_price, max_price, additional_filters
2. Convert 'k' notation to full numbers (20k = 20000)
3. Use default price ranges if not specified
4. Normalize product types to standard categories
5. Return ONLY valid JSON, no explanations

## PLATFORM MAPPING:
- amazon/amazon.in → "amazon"
- flipkart → "flipkart" 
- Default → "amazon"

## PRODUCT CATEGORIES:
- phones/smartphones/mobile → "smartphones"
- laptops/computers → "laptops"
- earbuds/headphones → "audio"
- Default → "products"

## EXAMPLES:
Input: "Give me all phones between 20k to 30k on amazon"
Output: {"platform": "amazon", "product_type": "smartphones", "min_price": 20000, "max_price": 30000, "additional_filters": []}

Input: "Show gaming laptops under 80000"
Output: {"platform": "amazon", "product_type": "laptops", "min_price": 0, "max_price": 80000, "additional_filters": ["gaming"]}

Input: "Find wireless earbuds with noise cancellation from 5k to 15k"
Output: {"platform": "amazon", "product_type": "audio", "min_price": 5000, "max_price": 15000, "additional_filters": ["wireless", "noise cancellation"]}

<|eot_id|><|start_header_id|>user<|end_header_id|>"""
        
        prompt = f"{user_query}\n\n<|eot_id|><|start_header_id|>assistant<|end_header_id|>"
        
        response = self.llm.generate(prompt, system_prompt)
        
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
                    return parsed_result
            
            # If JSON parsing fails, try the fallback
            return self._fallback_parse(user_query)
            
        except json.JSONDecodeError as e:
            print(f"⚠️  JSON parsing failed: {e}")
            return self._fallback_parse(user_query)
        except Exception as e:
            print(f"⚠️  Unexpected error in query parsing: {e}")
            return self._fallback_parse(user_query)
    
    def _fallback_parse(self, query: str) -> Dict:
        """Fallback parsing when LLM fails"""
        result = {
            "platform": "amazon",
            "product_type": "products",
            "min_price": 0,
            "max_price": 100000
        }
        
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
        print("🔍 Parsing your query...")
        parsed = self.parse_query(query)
        print(f"📊 Understood: {parsed}")
        
        print(f"🌐 Searching {parsed['platform']} for {parsed['product_type']}...")
        
        if parsed["platform"] == "amazon":
            products = self.scraper.scrape_amazon_products(
                parsed["product_type"],
                parsed["min_price"],
                parsed["max_price"]
            )
        else:
            print(f"❌ Platform {parsed['platform']} not yet supported")
            return []
        
        return products
    
    def summarize_results(self, products: List[Product], original_query: str) -> str:
        """Generate intelligent summary of results"""
        if not products:
            return "No products found matching your criteria."
        
        # Prepare product data for analysis
        product_data = []
        for i, p in enumerate(products[:10], 1):
            price_num = int(re.sub(r'[^\d]', '', p.price)) if re.search(r'\d', p.price) else 0
            product_data.append({
                "rank": i,
                "name": p.name,
                "price": price_num,
                "rating": p.rating
            })
        
        avg_price = sum(p["price"] for p in product_data) / len(product_data) if product_data else 0
        price_range = f"₹{min(p['price'] for p in product_data):,} - ₹{max(p['price'] for p in product_data):,}"
        
        system_prompt = """<|begin_of_text|><|start_header_id|>system<|end_header_id|>

You are an expert shopping advisor analyzing e-commerce search results. Provide actionable insights and recommendations.

## ANALYSIS FRAMEWORK:
1. **Summary Statistics**: Total found, price range, average price
2. **Top Recommendations**: Best 2-3 products with reasons
3. **Value Analysis**: Best value for money picks
4. **Market Insights**: Price trends, brand analysis
5. **Buying Advice**: When to buy, what to avoid

## OUTPUT FORMAT:
Use clear sections with emojis. Be concise but insightful. Focus on practical buying decisions.

## GUIDELINES:
- Highlight standout products with specific reasons
- Mention price-to-value ratios
- Include rating analysis when available
- Provide actionable next steps
- Keep response under 300 words

<|eot_id|><|start_header_id|>user<|end_header_id|>"""
        
        # Create the analysis text directly
        analysis_text = f"""## SEARCH QUERY: {original_query}

## RESULTS ANALYSIS:
- Total Products Found: {len(products)}
- Price Range: {price_range}
- Average Price: ₹{avg_price:,.0f}

## TOP PRODUCTS:
{chr(10).join([f"{p['rank']}. {p['name']} - ₹{p['price']:,} (Rating: {p['rating']})" for p in product_data])}

Analyze these results and provide shopping recommendations:

<|eot_id|><|start_header_id|>assistant<|end_header_id|>"""
        
        return self.llm.generate("", system_prompt + analysis_text)

def main():
    parser = argparse.ArgumentParser(description="Smart Web Extractor")
    parser.add_argument("--model", default="llama3:8b-instruct-q8_0", help="Ollama model to use")
    parser.add_argument("--query", help="Direct query to process")
    args = parser.parse_args()
    
    print("Smart Web Extractor v1.0")
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
                print(f"{i:2d}. {product.name[:60]}")
                print(f"    💰 {product.price} | ⭐ {product.rating}")
                print(f"    🔗 {product.url[:80]}...")
                print()
            
            # Generate AI summary
            print("AI Analysis:")
            summary = extractor.summarize_results(products, args.query)
            print(summary)
        else:
            print("No products found matching your criteria.")
    
    else:
        # Interactive mode
        print("\nInteractive Mode - Type your queries below:")
        print("Example: 'Give me all phones between 20k to 30k on amazon'")
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
                        print(f"    💰 {product.price} | ⭐ {product.rating}")
                        print(f"    🔗 {product.url[:80]}...")
                        print()
                    
                    if len(products) > 10:
                        print(f"... and {len(products) - 10} more products")
                    
                    # Generate AI summary
                    print("AI Analysis:")
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