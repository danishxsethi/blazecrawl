"""HTML → Markdown conversion optimized for LLM consumption.

Uses the permissively-licensed ``markdownify`` (MIT) for the actual conversion,
wrapped in BlazeCrawl's pre/post-processing for clean, token-efficient output.
The previous ``html2text`` dependency is GPL-3.0 and was removed to keep the
core Apache-2.0-compatible.
"""

from __future__ import annotations

import re

from markdownify import markdownify as _md

from blazecrawl_core.logging import get_logger

logger = get_logger(__name__)


class MarkdownConverter:
    """Converts clean HTML to high-quality Markdown."""

    def __init__(self) -> None:
        pass

    def _preprocess_html(self, html: str) -> str:
        """Fix common HTML issues before conversion."""
        html = re.sub(r"<br\s*/?>", "<br/>", html, flags=re.IGNORECASE)
        html = re.sub(r"</p>\s*<p>", "</p>\n<p>", html, flags=re.IGNORECASE)
        html = re.sub(r"</li>\s*<li>", "</li>\n<li>", html, flags=re.IGNORECASE)
        html = re.sub(r"&(?![a-zA-Z0-9#]+;)", "&amp;", html)
        html = html.replace("&amp;amp;", "&amp;").replace("&amp;#", "&#")
        html = re.sub(r"<p>\s*</p>", "", html, flags=re.IGNORECASE)
        html = re.sub(r"<p>\s*<br/>\s*</p>", "", html, flags=re.IGNORECASE)
        html = re.sub(
            r"\s*<(div|section|article|header|footer|main|aside)\b",
            "\n<\\1",
            html,
            flags=re.IGNORECASE,
        )
        html = re.sub(
            r"</(div|section|article|header|footer|main|aside)>\s*",
            "</\\1>\n",
            html,
            flags=re.IGNORECASE,
        )
        return html

    def _postprocess_markdown(self, markdown: str) -> str:
        """Clean converted Markdown for token-efficient LLM use."""
        markdown = re.sub(r"\n{4,}", "\n\n\n", markdown)
        lines = [line.strip() for line in markdown.split("\n")]
        markdown = "\n".join(lines)
        markdown = re.sub(r"\[\s*\]\([^)]+\)", "", markdown)
        markdown = re.sub(r"^\s*\[.*\]:\s*$", "", markdown, flags=re.MULTILINE)
        # Strip residual HTML tags.
        markdown = re.sub(r"<[^>]+>", "", markdown)
        markdown = re.sub(r"[ \t]{2,}", " ", markdown)
        markdown = re.sub(r"\n{3,}", "\n\n", markdown)
        return markdown.strip()

    def convert(self, html: str, base_url: str = "") -> str:
        """Convert HTML to Markdown.

        Args:
            html: HTML string.
            base_url: Base URL used to resolve relative links/images.

        Returns:
            Markdown string (empty string on failure).
        """
        try:
            processed = self._preprocess_html(html)
            markdown = _md(
                processed,
                base_url=base_url,
                heading_style="ATX",
                bullets="-",
                strip=["script", "style", "noscript"],
            )
            return self._postprocess_markdown(markdown)
        except Exception as e:
            logger.error("HTML→Markdown conversion failed", error=str(e))
            return ""

    def convert_to_text(self, html: str) -> str:
        """Convert HTML to plain text (links/images dropped)."""
        try:
            processed = self._preprocess_html(html)
            text = _md(
                processed,
                base_url="",
                strip=["a", "img", "script", "style", "noscript"],
            )
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text.strip()
        except Exception as e:
            logger.error("HTML→text conversion failed", error=str(e))
            return ""


_converter: MarkdownConverter | None = None


def get_markdown_converter() -> MarkdownConverter:
    global _converter
    if _converter is None:
        _converter = MarkdownConverter()
    return _converter
