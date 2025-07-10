import asyncio
from crawl4ai import *

async def main():
    browser_conf = BrowserConfig(headless=True)
    run_conf = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS
    )

    async with AsyncWebCrawler(config=browser_conf) as crawler:
        result = await crawler.arun(
            url="https://duckduckgo.com/?q=smartphones+under+80000",
            config=run_conf
        )
        print(result.markdown)

if __name__ == "__main__":
    asyncio.run(main())