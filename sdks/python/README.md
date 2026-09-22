# blazecrawl (Python SDK)

```python
from blazecrawl import BlazeCrawl

with BlazeCrawl(api_key="blz_local_...") as bc:
    doc = bc.scrape("https://example.com")
    print(doc["markdown"])
```
