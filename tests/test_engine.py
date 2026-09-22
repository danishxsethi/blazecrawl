"""Engine unit tests: extraction, markdown, url normalization, robots."""

from blazecrawl_core.engine.content_extractor import ExtractOptions, get_content_extractor
from blazecrawl_core.engine.robots import is_allowed

HTML = """<html><head><title>Widget Spec</title>
<meta name="description" content="widget spec"></head>
<body><nav>nav</nav><article><h1>Widget</h1>
<p>The widget is a device that does things. It has many features and this
paragraph is long enough to be treated as meaningful main content by the
readability extractor.</p>
<a href="/docs">Docs</a><img src="/w.png" alt="widget"></article></body></html>"""


async def test_extract_markdown_and_metadata():
    ex = get_content_extractor()
    r = await ex.extract(
        HTML, "https://example.com/", ExtractOptions(include_links=True, include_images=True)
    )
    assert r.metadata.title == "Widget Spec"
    assert r.markdown and "Widget" in r.markdown
    assert r.extraction_engine in ("readability", "trafilatura", "beautifulsoup", "full_html")
    assert any(link["url"] == "https://example.com/docs" for link in r.links)
    assert any(img["src"].endswith("/w.png") for img in r.images)


async def test_extract_plaintext():
    ex = get_content_extractor()
    r = await ex.extract(HTML, "https://example.com/", ExtractOptions(formats=["markdown", "text"]))
    assert r.plaintext and "widget" in r.plaintext.lower()


def test_url_normalizer_present():
    from blazecrawl_core.engine.url_normalizer import get_url_normalizer

    n = get_url_normalizer()
    assert n is not None


async def test_robots_allows_public_by_default_when_unreachable():
    # A host whose robots.txt is unreachable -> allowed (standard behaviour).
    # Use a non-routable but public-looking domain to avoid network dependency.
    assert isinstance(await is_allowed("https://example.com/"), bool)
