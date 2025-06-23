from langchain_core.documents import Document
import asyncio
from playwright.async_api import async_playwright
import random

class CustomChromiumLoader():
    def __init__(self, url: str):
        self.url = url
    
    async def ascrape_playwright_with_headers(url: str) -> str:

        USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 9_0_8) Gecko/20100101 Firefox/59.7",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 11_9_2; like Mac OS X) AppleWebKit/534.23 (KHTML, like Gecko)  Chrome/55.0.3939.364 Mobile Safari/535.9",
        "Mozilla/5.0 (Linux; Android 5.0.2; SM-A700I Build/LMY47X) AppleWebKit/534.3 (KHTML, like Gecko)  Chrome/49.0.3625.166 Mobile Safari/534.9",
        "Mozilla/5.0 (Windows; U; Windows NT 6.2; x64) Gecko/20100101 Firefox/64.7",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_8_0) Gecko/20100101 Firefox/55.4",
        "Mozilla/5.0 (Linux; Android 10; GM1917) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/77.0.3865.116 Mobile Safari/537.36 EdgA/45.12.4.5121",
        ]

        HEADERS = {
            "Accept-Language": "en-US, en;q=0.9",
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8"
        }
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(extra_http_headers=HEADERS)  # <- inject headers here
            page = await context.new_page()
            await page.goto(url, timeout=15000)
            await page.wait_for_load_state("load")
            content = await page.content()
            await browser.close()
            return content

    def load(self):
        import asyncio
        html = asyncio.run(self.ascrape_playwright_with_headers(self.url))
        return [Document(page_content=html)]
