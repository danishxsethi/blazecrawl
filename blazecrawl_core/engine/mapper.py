"""Map/discovery for BlazeCrawl Core.

Discovers the URL set for a site by combining:
1. Well-known sitemap locations (``/sitemap.xml``, ``/robots.txt`` Sitemap
   directives, common index names), parsed for URLs and nested sitemaps.
2. A same-origin link graph obtained by rendering/fetching the seed page.

All network access goes through the SSRF-pinned egress layer; sitemap URLs are
individually validated before being returned so a malicious sitemap cannot
smuggle internal addresses into the result.
"""

from __future__ import annotations

import gzip
import re
from urllib.parse import urlsplit

import defusedxml.ElementTree as ET

from blazecrawl_core.config import settings
from blazecrawl_core.logging import get_logger
from blazecrawl_core.network.egress import safe_fetch
from blazecrawl_core.network.ip_utils import is_private_ip
from blazecrawl_core.network.ssrf import SSRFValidationError, validate_and_pin

logger = get_logger(__name__)

_SITEMAP_CANDIDATES = ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml")
_XML_NS = re.compile(r"\{[^}]*\}")
_MAX_SITEMAP_DEPTH = 3
_MAX_URLS = 10_000


async def _fetch(url: str) -> str | None:
    try:
        resp = await safe_fetch(url, timeout_s=15.0, max_bytes=settings.MAX_RESPONSE_BYTES)
        if resp.status_code != 200:
            return None
        content = resp.content
        if url.endswith(".gz") or resp.headers.get("content-encoding") == "gzip":
            try:
                content = gzip.decompress(content)
            except Exception:
                return None
        return content.decode("utf-8", errors="replace")
    except SSRFValidationError:
        raise
    except Exception:
        return None


def _parse_sitemap(xml_text: str) -> tuple[list[str], list[str]]:
    """Return (child_sitemap_urls, page_urls) from a sitemap document."""
    sitemaps: list[str] = []
    urls: list[str] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return sitemaps, urls
    tag = _XML_NS.sub("", root.tag)
    if tag == "sitemapindex":
        for loc in root.iter():
            if _XML_NS.sub("", loc.tag) == "loc" and loc.text:
                sitemaps.append(loc.text.strip())
    elif tag == "urlset":
        for loc in root.iter():
            if _XML_NS.sub("", loc.tag) == "loc" and loc.text:
                urls.append(loc.text.strip())
    return sitemaps, urls


async def _robots_sitemaps(origin: str) -> list[str]:
    text = await _fetch(f"{origin}/robots.txt")
    if not text:
        return []
    out = []
    for line in text.splitlines():
        if line.lower().startswith("sitemap:"):
            out.append(line.split(":", 1)[1].strip())
    return out


async def _collect_sitemap_urls(sm_url: str, depth: int, out: list[str], seen: set[str]) -> None:
    if depth > _MAX_SITEMAP_DEPTH or sm_url in seen or len(out) >= _MAX_URLS:
        return
    seen.add(sm_url)
    text = await _fetch(sm_url)
    if not text:
        return
    children, urls = _parse_sitemap(text)
    out.extend(urls)
    for child in children[:50]:
        await _collect_sitemap_urls(child, depth + 1, out, seen)


async def _link_graph(seed: str) -> list[str]:
    """Extract same-origin links from the seed page (static fetch)."""
    from blazecrawl_core.engine.content_extractor import ExtractOptions, get_content_extractor

    try:
        resp = await safe_fetch(seed, timeout_s=15.0, max_bytes=settings.MAX_RESPONSE_BYTES)
    except Exception:
        return []
    if resp.status_code != 200:
        return []
    extractor = get_content_extractor()
    ext = await extractor.extract(
        resp.text,
        resp.final_url,
        ExtractOptions(only_main_content=False, include_links=True, formats=[]),
    )
    seed_host = urlsplit(resp.final_url).netloc
    out = []
    for link in ext.links or []:
        u = link.get("url")
        if u and urlsplit(u).netloc == seed_host and u.split("#")[0] not in out:
            out.append(u.split("#")[0])
    return out


async def map_site(url: str, *, include_sitemap: bool = True) -> dict:
    """Return a normalized URL graph for a site.

    Every returned URL is re-validated through the SSRF pin before inclusion so
    a hostile sitemap/redirect cannot inject internal addresses.
    """
    await validate_and_pin(url)  # seed must be a public target
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"

    found: list[str] = []
    sitemaps_found: list[str] = []

    if include_sitemap:
        candidates = [f"{origin}{p}" for p in _SITEMAP_CANDIDATES]
        candidates.extend(await _robots_sitemaps(origin))
        seen: set[str] = set()
        for cand in candidates:
            text = await _fetch(cand)
            if text and ("<urlset" in text or "<sitemapindex" in text):
                sitemaps_found.append(cand)
                await _collect_sitemap_urls(cand, 0, found, seen)

    # Link graph from the seed.
    graph = await _link_graph(url)

    # Validate + de-duplicate (same-origin + public only).
    combined = []
    seen_urls: set[str] = set()
    for u in [url, *graph, *found]:
        u = u.split("#")[0]
        if not u or u in seen_urls:
            continue
        if urlsplit(u).netloc != parts.netloc:
            continue
        host = urlsplit(u).hostname or ""
        if is_private_ip(host):
            continue
        seen_urls.add(u)
        combined.append(u)
        if len(combined) >= _MAX_URLS:
            break

    return {
        "success": True,
        "seed": url,
        "urls": combined,
        "count": len(combined),
        "sitemaps_found": sitemaps_found,
        "sources": {"link_graph": len(graph), "sitemap": len(found)},
    }
