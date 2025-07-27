import asyncio
from crawl4ai import *

async def main():
    browser_conf = BrowserConfig(headless=False)
    run_conf = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        js_code=[
            "window.scrollTo(0, document.body.scrollHeight/2);",
            "await new Promise(resolve => setTimeout(resolve, 3000));"
        ],
        wait_for_images=True,
        magic=True,
        simulate_user=True,
        override_navigator=True,
        scan_full_page=True,
        delay_before_return_html=7,
    )

    async with AsyncWebCrawler(config=browser_conf) as crawler:
        result = await crawler.arun(
            url="https://www.amazon.in/s?k=steam+cleaning+power+efficient+washing+machine",
            config=run_conf
        )
        print(result.markdown[:5000])

if __name__ == "__main__":
    asyncio.run(main())