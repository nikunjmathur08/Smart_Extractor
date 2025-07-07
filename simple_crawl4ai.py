import asyncio
from crawl4ai import AsyncWebCrawler

async def multipleScrape (urls: list[str]):
  async with AsyncWebCrawler() as crawler:
    results = await crawler.arun_many(urls=urls)
    return results
  
urls = [
  "https://www.walmart.com/search?q=lg+oled",
  "https://www.walmart.com/search?q=lg+oled&page=2",
  "https://www.walmart.com/search?q=lg+oled&page=3",
]

res_list = asyncio.run(multipleScrape(urls))

for i, res in enumerate(res_list):
  print(f"\n=== Page {i+1} ===")
  print(f"URL: {res.url}")
  print(f"Success: {res.success}")
  print(f"Status Code: {res.status_code}")

  if res.success:
    print("\n--- Markdown ---")
    print(res.markdown.strip()[:1000])  # limit to first 1000 chars
    print("\n--- Extracted Text ---")
    print(res.text.strip()[:1000])  # optional
  else:
    print("Failed to scrape.")