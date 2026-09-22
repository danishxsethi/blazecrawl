"""Minimal BlazeCrawl Core example: scrape → Markdown, then crawl."""

import os

from blazecrawl import BlazeCrawl

bc = BlazeCrawl(api_key=os.environ.get("BLAZECRAWL_API_KEY"))

doc = bc.scrape("https://example.com")
print("TITLE:", doc["metadata"].get("title"))
print(doc["markdown"][:200])

job = bc.crawl("https://example.com", max_pages=5, max_depth=1)
print("CRAWL:", job["status"], job["pages_crawled"], "pages")
