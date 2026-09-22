"""Content extraction service using Readability and Trafilatura.

This module provides the core content extraction pipeline that takes raw HTML
and produces clean, structured output in various formats.
"""

import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import chardet
import trafilatura
from lxml import html
from readability import Document

from blazecrawl_core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ExtractOptions:
    """Options for content extraction.

    Attributes:
        only_main_content: Strip boilerplate (nav, footer, sidebar, ads).
        include_links: Extract all links from the content.
        include_images: Extract all images from the content.
        include_metadata: Extract page metadata.
        formats: List of output formats to generate.
    """

    only_main_content: bool = True
    include_links: bool = False
    include_images: bool = False
    include_metadata: bool = True
    formats: list[str] = field(default_factory=lambda: ["markdown"])


@dataclass
class PageMetadata:
    """Metadata extracted from a web page.

    Attributes:
        title: Page title.
        description: Page description or excerpt.
        language: Detected page language.
        author: Author information if available.
        published_date: Publication date if available.
        og_image: Open Graph image URL.
        canonical_url: Canonical URL.
        favicon: Favicon URL.
        status_code: HTTP status code.
        content_type: Content-Type header.
    """

    title: str | None = None
    description: str | None = None
    language: str | None = None
    author: str | None = None
    published_date: str | None = None
    og_image: str | None = None
    canonical_url: str | None = None
    favicon: str | None = None
    status_code: int = 200
    content_type: str | None = None


@dataclass
class ExtractedContent:
    """Result of content extraction.

    Attributes:
        url: Original URL that was scraped.
        markdown: Extracted content in Markdown format.
        html: Extracted content in HTML format.
        raw_html: Original raw HTML.
        plaintext: Plain text version of content.
        links: List of extracted links with metadata.
        images: List of extracted images with metadata.
        metadata: Page metadata.
        structured_data: Structured data extracted from the page (JSON-LD, microdata, RDFa, etc.).
        word_count: Word count of extracted content.
        extraction_time_ms: Time taken for extraction.
        extraction_engine: Name of the engine that produced the main content.
    """

    url: str
    markdown: str | None = None
    html: str | None = None
    raw_html: str | None = None
    plaintext: str | None = None
    links: list[dict[str, Any]] | None = None
    images: list[dict[str, Any]] | None = None
    metadata: PageMetadata = field(default_factory=PageMetadata)
    structured_data: dict[str, Any] | None = None
    word_count: int = 0
    extraction_time_ms: float = 0.0
    extraction_engine: str | None = None


class ContentExtractor:
    """Extracts clean, structured content from web pages.

    This class orchestrates the content extraction pipeline:
    1. Parse raw HTML with lxml
    2. Extract metadata (title, description, OG tags, etc.)
    3. Run readability-lxml to isolate main content
    4. Fallback to trafilatura if readability fails
    5. Convert to requested formats
    6. Extract links and images
    """

    def __init__(self) -> None:
        """Initialize the content extractor."""
        from blazecrawl_core.engine.markdown_converter import get_markdown_converter

        self._md = get_markdown_converter()

    def _detect_encoding(self, raw_html: bytes, content_type: str | None) -> str:
        """Detect HTML encoding from headers or content.

        Args:
            raw_html: Raw HTML bytes.
            content_type: Content-Type header value.

        Returns:
            Detected encoding string.
        """
        # Try Content-Type header first
        if content_type:
            match = re.search(r"charset=([^\s;]+)", content_type)
            if match:
                return match.group(1)

        # Try meta tag
        try:
            text = raw_html[:2000]
            meta_match = re.search(rb'<meta[^>]+charset=["\']?([^"\'\s>]+)', text, re.IGNORECASE)
            if meta_match:
                return meta_match.group(1).decode("ascii")
        except Exception:
            pass

        # Fallback to chardet
        try:
            result = chardet.detect(raw_html)
            if result and result.get("encoding"):
                return result["encoding"]
        except Exception:
            pass

        return "utf-8"

    def _decode_html(self, raw_html: bytes, content_type: str | None) -> str:
        """Decode HTML bytes to string with proper encoding handling.

        Args:
            raw_html: Raw HTML bytes.
            content_type: Content-Type header value.

        Returns:
            Decoded HTML string.
        """
        encoding = self._detect_encoding(raw_html, content_type)

        try:
            return raw_html.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            # Try common encodings
            for enc in ["utf-8", "latin-1", "cp1252"]:
                try:
                    return raw_html.decode(enc)
                except UnicodeDecodeError:
                    continue

            # Last resort: decode with errors replaced
            return raw_html.decode("utf-8", errors="replace")

    def _strip_script_tags(self, html_str: str) -> str:
        """Remove script, style, and noscript tags from HTML.

        Args:
            html_str: HTML string to clean.

        Returns:
            Cleaned HTML string.
        """
        # Remove script tags
        html_str = re.sub(
            r"<script[^>]*>.*?</script>", "", html_str, flags=re.DOTALL | re.IGNORECASE
        )
        # Remove style tags
        html_str = re.sub(r"<style[^>]*>.*?</style>", "", html_str, flags=re.DOTALL | re.IGNORECASE)
        # Remove noscript tags (but keep content)
        html_str = re.sub(r"</?noscript[^>]*>", "", html_str, flags=re.IGNORECASE)
        return html_str

    def _extract_metadata(self, html_str: str, base_url: str) -> PageMetadata:
        """Extract metadata from HTML.

        Args:
            html_str: HTML string.
            base_url: Base URL for resolving relative URLs.

        Returns:
            PageMetadata instance.
        """
        metadata = PageMetadata()

        try:
            doc = html.fromstring(html_str)

            # Title
            title_elem = doc.xpath("//title")
            if title_elem:
                metadata.title = title_elem[0].text_content().strip()

            # Meta description
            desc_elem = doc.xpath('//meta[@name="description"]/@content')
            if desc_elem:
                metadata.description = desc_elem[0].strip()

            # Language
            lang_elem = doc.xpath("//html/@lang")
            if lang_elem:
                metadata.language = lang_elem[0].strip().lower()

            # Author
            author_elem = doc.xpath('//meta[@name="author"]/@content')
            if not author_elem:
                author_elem = doc.xpath('//meta[@property="article:author"]/@content')
            if author_elem:
                metadata.author = author_elem[0].strip()

            # Published date
            date_elem = doc.xpath('//meta[@property="article:published_time"]/@content')
            if not date_elem:
                date_elem = doc.xpath('//meta[@name="date"]/@content')
            if date_elem:
                metadata.published_date = date_elem[0].strip()

            # Open Graph image
            og_image = doc.xpath('//meta[@property="og:image"]/@content')
            if og_image:
                metadata.og_image = urllib.parse.urljoin(base_url, og_image[0])

            # Canonical URL
            canonical = doc.xpath('//link[@rel="canonical"]/@href')
            if canonical:
                metadata.canonical_url = canonical[0]
            else:
                metadata.canonical_url = base_url

            # Favicon
            favicon = doc.xpath('//link[@rel="icon"]/@href')
            if not favicon:
                favicon = doc.xpath('//link[@rel="shortcut icon"]/@href')
            if favicon:
                metadata.favicon = urllib.parse.urljoin(base_url, favicon[0])
            else:
                # Try default location
                parsed = urllib.parse.urlparse(base_url)
                metadata.favicon = f"{parsed.scheme}://{parsed.netloc}/favicon.ico"

        except Exception as e:
            logger.warning("Error extracting metadata", error=str(e))

        return metadata

    def _extract_with_readability(self, html_str: str) -> tuple[str | None, str | None]:
        """Extract content using readability-lxml.

        Args:
            html_str: HTML string.

        Returns:
            Tuple of (title, content_html) or (None, None) on failure.
        """
        try:
            doc = Document(html_str)
            title = doc.title()
            content = doc.summary()

            # Check if content is too short (readability likely failed)
            if content and len(content.strip()) < 100:
                logger.debug("Readability returned too little content, will try fallback")
                return None, None

            return title, content
        except Exception as e:
            logger.warning("Readability extraction failed", error=str(e))
            return None, None

    def _extract_with_trafilatura(self, html_str: str) -> str | None:
        """Extract content using trafilatura as fallback.

        Args:
            html_str: HTML string.

        Returns:
            Extracted content HTML or None on failure.
        """
        try:
            result = trafilatura.extract(
                html_str,
                output_format="html",
                include_comments=False,
                include_tables=True,
                with_metadata=True,
            )
            return result
        except Exception as e:
            logger.warning("Trafilatura extraction failed", error=str(e))
            return None

    def _extract_links(self, html_str: str, base_url: str) -> list[dict[str, Any]]:
        """Extract all links from HTML.

        Args:
            html_str: HTML string.
            base_url: Base URL for resolving relative URLs.

        Returns:
            List of link dictionaries.
        """
        links = []
        max_links = 10_000  # guard against pathological pages

        try:
            doc = html.fromstring(html_str)
            anchor_tags = doc.xpath("//a[@href]")

            parsed_base = urllib.parse.urlparse(base_url)
            base_domain = parsed_base.netloc

            for anchor in anchor_tags:
                if len(links) >= max_links:
                    logger.warning(
                        "Link extraction capped at limit",
                        url=base_url,
                        limit=max_links,
                    )
                    break

                href = anchor.get("href", "").strip()
                if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue

                # Resolve relative URLs
                try:
                    absolute_url = urllib.parse.urljoin(base_url, href)
                except Exception:
                    continue

                # Determine if internal
                parsed_url = urllib.parse.urlparse(absolute_url)
                is_internal = parsed_url.netloc == base_domain

                # Get link text
                text = anchor.text_content().strip()

                links.append(
                    {
                        "url": absolute_url,
                        "text": text[:500] if text else None,  # Limit text length
                        "is_internal": is_internal,
                    }
                )

        except Exception as e:
            logger.warning("Error extracting links", error=str(e))

        return links

    def _extract_images(self, html_str: str, base_url: str) -> list[dict[str, Any]]:
        """Extract all images from HTML.

        Args:
            html_str: HTML string.
            base_url: Base URL for resolving relative URLs.

        Returns:
            List of image dictionaries.
        """
        images = []
        max_images = 1_000  # guard against pathological pages

        try:
            doc = html.fromstring(html_str)
            img_tags = doc.xpath("//img")

            for img in img_tags:
                if len(images) >= max_images:
                    logger.warning(
                        "Image extraction capped at limit",
                        url=base_url,
                        limit=max_images,
                    )
                    break

                src = img.get("src", "").strip()
                if not src:
                    continue

                # Resolve relative URLs
                try:
                    absolute_src = urllib.parse.urljoin(base_url, src)
                except Exception:
                    absolute_src = src

                # Get alt text
                alt = img.get("alt", "").strip()

                # Get dimensions if available
                width = img.get("width")
                height = img.get("height")

                # Try to get natural dimensions from style
                style = img.get("style", "")
                if not width:
                    width_match = re.search(r"width:\s*(\d+)", style)
                    if width_match:
                        width = width_match.group(1)
                if not height:
                    height_match = re.search(r"height:\s*(\d+)", style)
                    if height_match:
                        height = height_match.group(1)

                images.append(
                    {
                        "src": absolute_src,
                        "alt": alt if alt else None,
                        "width": int(width) if width and width.isdigit() else None,
                        "height": int(height) if height and height.isdigit() else None,
                    }
                )

        except Exception as e:
            logger.warning("Error extracting images", error=str(e))

        return images

    def _html_to_markdown(self, html_str: str, base_url: str) -> str:
        """Convert HTML to Markdown.

        Args:
            html_str: HTML string.
            base_url: Base URL for resolving relative links.

        Returns:
            Markdown string.
        """
        return self._md.convert(html_str, base_url)

    def _html_to_text(self, html_str: str) -> str:
        """Convert HTML to plain text.

        Args:
            html_str: HTML string.

        Returns:
            Plain text string.
        """
        # Try trafilatura first
        try:
            text = trafilatura.extract(
                html_str,
                output_format="txt",
                include_comments=False,
            )
            if text:
                return text.strip()
        except Exception:
            pass

        # Fallback to the Markdown converter's text mode (links/images dropped).
        return self._md.convert_to_text(html_str)

    def _extract_structured_data(self, html_str: str, base_url: str) -> dict[str, Any]:
        """Extract embedded structured data (JSON-LD, microdata, RDFa, microformats).

        Args:
            html_str: HTML string to parse.
            base_url: Base URL for resolving relative URLs.

        Returns:
            Dict mapping syntax name to a list of extracted items.
        """
        try:
            import extruct
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning(
                "extruct not available, skipping structured data extraction", error=str(exc)
            )
            return {}

        try:
            data = extruct.extract(
                html_str,
                base_url=base_url,
                uniform=True,
                syntaxes=["json-ld", "microdata", "rdfa", "microformat"],
            )
        except Exception as exc:
            logger.warning("Structured data extraction failed", error=str(exc))
            return {}

        return {k: v for k, v in data.items() if v}

    def _extract_with_beautifulsoup(self, html_str: str) -> str | None:
        """Extract visible text from HTML using BeautifulSoup as a last resort.

        Args:
            html_str: HTML string.

        Returns:
            Visible text or None if nothing useful was found.
        """
        try:
            from bs4 import BeautifulSoup
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning("BeautifulSoup not available, skipping fallback", error=str(exc))
            return None

        try:
            soup = BeautifulSoup(html_str, "html.parser")
            # Drop script/style just in case
            for tag in soup.find_all(["script", "style"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            if text:
                return text
        except Exception as exc:
            logger.warning("BeautifulSoup fallback extraction failed", error=str(exc))

        return None

    async def extract(
        self,
        html: str,
        url: str,
        options: ExtractOptions | None = None,
    ) -> ExtractedContent:
        """Extract content from HTML with the full pipeline.

        Pipeline:
        1. Parse raw HTML with lxml
        2. Extract metadata (title, description, OG tags, canonical URL, etc.)
        3. Run readability-lxml to isolate main content
        4. If readability fails or returns < 100 chars, fallback to trafilatura
        5. Convert clean HTML → requested formats
        6. Extract all links (internal + external)
        7. Extract all images
        8. Return ExtractedContent

        Args:
            html: Raw HTML content (string or bytes).
            url: Base URL for resolving relative URLs.
            options: Extraction options.

        Returns:
            ExtractedContent with all requested data.
        """
        start_time = time.perf_counter()
        options = options or ExtractOptions()

        # Handle bytes input
        if isinstance(html, bytes):
            content_type = None
            html = self._decode_html(html, content_type)

        # Strip script/style tags
        clean_html = self._strip_script_tags(html)

        # Extract metadata
        metadata = PageMetadata()
        if options.include_metadata:
            metadata = self._extract_metadata(clean_html, url)

        # Extract structured data from the original HTML (script tags are
        # required for JSON-LD, so we use the un-stripped HTML).
        structured_data: dict[str, Any] = {}
        if options.include_metadata:
            structured_data = self._extract_structured_data(html, url)

        # Extract main content
        content_html = None
        extraction_engine: str | None = None

        if options.only_main_content:
            # Try readability first
            title, content_html = self._extract_with_readability(clean_html)
            if content_html:
                extraction_engine = "readability"

            # Fallback to trafilatura if readability failed
            if not content_html or len(content_html.strip()) < 100:
                logger.debug("Falling back to trafilatura")
                content_html = self._extract_with_trafilatura(clean_html)
                if content_html:
                    extraction_engine = "trafilatura"

                # Update title from trafilatura if available
                if not title and content_html:
                    try:
                        meta = trafilatura.extract_metadata(clean_html)
                        if meta and meta.title:
                            title = meta.title
                    except Exception:
                        pass

            # Use title from readability if we got one
            if title and not metadata.title:
                metadata.title = title
        else:
            # Use full HTML
            content_html = clean_html
            extraction_engine = "full_html"

        # Build result
        result = ExtractedContent(
            url=url,
            raw_html=html,
            html=content_html,
            metadata=metadata,
            structured_data=structured_data,
        )

        # Convert to requested formats
        if content_html:
            if "markdown" in options.formats:
                result.markdown = self._html_to_markdown(content_html, url)
                if result.markdown:
                    result.word_count = len(result.markdown.split())

            if "text" in options.formats or "plaintext" in options.formats:
                result.plaintext = self._html_to_text(content_html)

            if "html" in options.formats:
                result.html = content_html

            result.extraction_engine = extraction_engine

        # BeautifulSoup fallback when the primary engines failed to produce content
        if options.only_main_content and (not content_html or len(content_html.strip()) < 100):
            logger.debug("Falling back to BeautifulSoup for visible text")
            bs_text = self._extract_with_beautifulsoup(clean_html)
            if bs_text:
                result.markdown = bs_text
                result.plaintext = bs_text
                result.word_count = len(bs_text.split())
                result.extraction_engine = "beautifulsoup"
                logger.info("BeautifulSoup fallback used", url=url, word_count=result.word_count)

        # Extract links
        if options.include_links:
            result.links = self._extract_links(clean_html, url)

        # Extract images
        if options.include_images:
            result.images = self._extract_images(clean_html, url)

        # Calculate extraction time
        result.extraction_time_ms = (time.perf_counter() - start_time) * 1000

        logger.info(
            "Content extracted",
            url=url,
            word_count=result.word_count,
            extraction_time_ms=round(result.extraction_time_ms, 2),
            has_markdown=result.markdown is not None,
            links_count=len(result.links) if result.links else 0,
            images_count=len(result.images) if result.images else 0,
            extraction_engine=result.extraction_engine,
        )

        return result


# Global extractor instance
_content_extractor: ContentExtractor | None = None


def get_content_extractor() -> ContentExtractor:
    """Get the global content extractor instance."""
    global _content_extractor
    if _content_extractor is None:
        _content_extractor = ContentExtractor()
    return _content_extractor


# Alias for backward compatibility
content_extractor = get_content_extractor()
