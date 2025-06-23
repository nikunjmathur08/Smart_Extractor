from crawl4ai import *
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
import asyncio

async def main():
    md_gen = DefaultMarkdownGenerator(
        content_filter=PruningContentFilter(0.4, threshold_type="fixed")
    )

    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        markdown_generator=md_gen
    )

    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun("https://amazon.in/s?k=smartphones+under+80000", config=config)
        print("Raw markdown length:", len(result.markdown.raw_markdown))
        fit_result = result.markdown.fit_markdown
        print("Fit markdown length:", len(fit_result))
        print(fit_result)

if __name__ == "__main__":
    asyncio.run(main())