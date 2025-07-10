from langflow.components import Component, Agent
from langflow.llm import OllamaTool
from crawl4ai import AsyncWebCrawler
import urllib.parse

class DynamicValidator(Component):
  """AI Powered TLD validation using Ollama"""
  def __init__ (self):
    self.llm = OllamaTool(
      base_url="http://localhost:11434",
      model="llama3:8b0instruct-q8_0"
    )
  
  async def validate_domain(self, domain: str, country: str = "IN") -> str:
    """Use Ollama to infer correct TLD"""
    prompt = f"""
    Convert {domain} to {country} TLD (e.g., amazon -> amazon.in)
    Return ONLY the corrected domain
    """

    try:
      response = await self.llm.invoke(prompt)
      return response.strip().lower()
    except Exception as e:
      print(f"Ollama Error: {str(e)}")
      return domain

class ParameterNormalizer(Component):
  """Convert user parameters to site-specific syntax"""
  param_rules = {
    "amazon.in": {"price": ["min_price", "max_price"], "size": "size"},
    "flipkart.com": {"price": "price", "size": "size"},
  }

  def normalize(self, site: str, params: dict) -> dict:
    normalized = {}
    for key, val in params.items():
      rule = self.param_rules.get(site, {}).get(key, key)
      normalized[rule] = val
    return normalized

class URLGenerator(Component):
  """Construct site-specific URLs with parameters"""
  site_patterns = {
    "amazon.in": "https://{domain}/s",
    "flipkart.com": "https://{domain}/search",
    "default": "https://duckduckgo.com"
  }

  def generate(self, domain: str, query: str, params: dict = {}) -> str:
    base_url = self.site_patterns.get(domain, self.site_patterns["default"])
    query_str = urllib.parse.quote_plus(query)
    params_str = "&".join([f"{k}={urllib.parse.quote_plus(v)}" for k, v in params.items()])

    return f"{base_url}?k={query_str}&{params_str}".strip("&")


class URLAgent(Agent):
  def setup(self):
    self.add_component(DynamicValidator())
    self.add_component(ParameterNormalizer())
    self.add_component(URLGenerator())

    self.flow = (
      self.input
      .then(self.DynamicValidator.validate_domain)
      .then(self.ParametereNormalizer.normalize, site="")
      .then(self.URLGeneraot.generate, domain="", query="", params={})
    )

    def generate_url(self, query: str, params: dict = {}) -> str:
      return self.flow(query, params)


class ProductScraper:
  def __init__(self):
    self.agent = URLAgent()
    self.browser_config = BrowserConfig (
      headless=False,
      user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    )
    self.run_config = CrawlerRunConfig (
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
  
  async def run_crawl4ai(self, structured: dict) -> list:
    """Scrape products using dynamic URL"""
    domain = structured.get("site", "amazon.in")
    source_url = self.agent.generate_url(
      query=structured["query"],
      params=structured.get("params", {})
    )

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

    def parse_products_from_markdown(self, markdown: str, min_price: int, max_price: int) -> list:
      """Parse products from crawled markdown"""
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

def query_llama(user_input: str) -> dict:
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
  except Exception as e:
      print(f"LLM processing error: {str(e)}")
      return None

def main():
  print("🛒 Ollama-Powered Smart Product Scraper")
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
      
    questions = ask_follow_up_questions(user_input, structured)
    if questions:
        print("\n I have a few questions to refine your search...")
        user_answers = []
        for q in questions:
            ans = input(f"→ {q} ")
            user_answers.append(ans.strip())
        
        structured = refine_structured_query_with_answers(user_input, user_answers, structured)
      
    structured["query"] = sanitize_query(structured["query"])
    structured["site"] = structured.get("site", "amazon.in")

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