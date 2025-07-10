from playwright.sync_api import sync_playwright
from fake_useragent import UserAgent
import time
import random

def get_amazon_results(search_query, proxy=None):
    ua = UserAgent()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        context_args = {
            "user_agent": ua.random
        }
        if proxy:
            context_args["proxy"] = {
                "server": proxy
            }

        context = browser.new_context(**context_args)
        page = context.new_page()

        query = search_query.replace(" ", "+")
        url = f"https://www.amazon.in/s?k={query}"
        print("Fetching:", url)

        try:
            page.goto(url, timeout=60000)
            time.sleep(random.uniform(5, 7))  # Allow full render

            # Check for CAPTCHA
            if "Enter the characters you see below" in page.content():
                print("CAPTCHA detected. You may need to solve it manually or rotate proxy.")
                return []

            products = page.query_selector_all('div.s-main-slot div[data-component-type="s-search-result"]')
            results = []

            for product in products[:10]:  # Limit to top 10
                title_el = product.query_selector("h2 span")
                price_el = product.query_selector("span.a-price-whole")

                title = title_el.inner_text().strip() if title_el else "No Title"
                price = price_el.inner_text().strip() if price_el else "No Price"
                results.append({"title": title, "price": price})

            return results

        except Exception as e:
            print("Error:", e)
            return []

        finally:
            browser.close()