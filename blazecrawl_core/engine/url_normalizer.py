"""RFC 3986-compliant URL normalisation for consistent cache keys and deduplication.

Design goals
------------
- Deterministic: the same logical URL always produces the same normalised form.
- Lossless for content: only removes information that does not affect page content
  (tracking params, fragments, redundant encoding, default ports).
- Fast: no network I/O; pure string/regex operations.
- Thread-safe: URLNormalizer is stateless and can be shared across coroutines.

Normalisation steps (in order)
-------------------------------
1.  Parse with urllib.parse.urlsplit
2.  Lowercase scheme + host (RFC 3986 §6.2.2.1)
3.  Remove default ports (80 for http, 443 for https)
4.  Remove fragment (#section) — fragments are client-side only
5.  Decode unnecessary percent-encoding (unreserved chars: A-Z a-z 0-9 - . _ ~)
6.  Re-encode any improperly encoded characters
7.  Resolve . and .. path segments (RFC 3986 §5.2.4)
8.  Collapse consecutive slashes in path
9.  Remove trailing slash on path (except root "/")
10. Sort query parameters alphabetically
11. Remove tracking / analytics parameters
"""

from __future__ import annotations

import hashlib
import re
from typing import Final
from urllib.parse import (
    quote,
    unquote,
    urljoin,
    urlsplit,
    urlunsplit,
)

try:
    import tldextract as _tldextract

    _HAS_TLDEXTRACT = True
except ImportError:  # pragma: no cover
    _HAS_TLDEXTRACT = False

from blazecrawl_core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default ports that should be stripped from the authority component
_DEFAULT_PORTS: Final[dict[str, int]] = {"http": 80, "https": 443}

# Unreserved characters per RFC 3986 §2.3 — these must NOT be percent-encoded
_UNRESERVED: Final[str] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"

# Characters that are safe in path segments (unreserved + sub-delims + ":" + "@")
_PATH_SAFE: Final[str] = _UNRESERVED + ":@!$&'()*+,;="

# Characters that are safe in query values
_QUERY_SAFE: Final[str] = _UNRESERVED + ":@!$'()*+,;/?"

# Tracking / analytics query parameters to strip unconditionally.
# Sorted for readability; membership test is O(1) via frozenset.
TRACKING_PARAMS: Final[frozenset[str]] = frozenset(
    {
        # Google Analytics / Ads
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "utm_source_platform",
        "utm_creative_format",
        "utm_marketing_tactic",
        "_ga",
        "_gl",
        "gclid",
        "gclsrc",
        "dclid",
        # Meta / Facebook
        "fbclid",
        # Microsoft Ads
        "msclkid",
        # Mailchimp
        "mc_cid",
        "mc_eid",
        # Twitter / X
        "twclid",
        # Instagram
        "igshid",
        # Yandex
        "yclid",
        # TikTok
        "ttclid",
        # LinkedIn
        "li_fat_id",
        # Generic referral / session
        "ref",
        "referrer",
        "source",
        "session_id",
        "sid",
    }
)

# Regex that matches a single percent-encoded triplet, e.g. %2F
_PCT_ENCODED: Final[re.Pattern[str]] = re.compile(r"%([0-9A-Fa-f]{2})")

# Regex for collapsing consecutive slashes in a path (but not the leading //)
_DOUBLE_SLASH: Final[re.Pattern[str]] = re.compile(r"/{2,}")


# ---------------------------------------------------------------------------
# URLNormalizer
# ---------------------------------------------------------------------------


class URLNormalizer:
    """RFC 3986-compliant URL normalisation.

    All methods are pure functions (no side effects, no state).  The class
    exists to group related helpers and allow easy subclassing / mocking.

    Usage
    -----
    >>> n = URLNormalizer()
    >>> n.normalize("HTTPS://Example.COM/path/../docs?b=2&utm_source=google&a=1#frag")
    'https://example.com/docs?a=1&b=2'
    """

    # ------------------------------------------------------------------
    # Primary public API
    # ------------------------------------------------------------------

    def normalize(self, url: str) -> str:
        """Return the canonical form of *url*.

        Returns the original URL unchanged if parsing fails, so callers
        never receive an empty string or an exception.
        """
        if not url or not url.strip():
            return url

        try:
            return self._normalize(url.strip())
        except Exception as exc:
            logger.warning("URL normalisation failed, returning original", url=url, error=str(exc))
            return url

    def get_domain(self, url: str) -> str:
        """Return the registerable domain (eTLD+1) of *url*.

        Examples
        --------
        >>> n.get_domain("https://sub.example.co.uk/path")
        'example.co.uk'
        >>> n.get_domain("https://example.com")
        'example.com'

        Falls back to the raw hostname when tldextract is unavailable.
        """
        host = self._host(url)
        if not host:
            return ""

        if _HAS_TLDEXTRACT:
            ext = _tldextract.extract(host)
            if ext.domain and ext.suffix:
                return f"{ext.domain}.{ext.suffix}"
            # Bare IP or localhost
            return host

        # Fallback: strip leading subdomains heuristically (last two labels)
        parts = host.split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return host

    def get_base_url(self, url: str) -> str:
        """Return ``scheme://host`` with no path, query, or fragment.

        >>> n.get_base_url("https://example.com/docs?q=1")
        'https://example.com'
        """
        try:
            s = urlsplit(url)
            return urlunsplit((s.scheme.lower(), s.netloc.lower(), "", "", ""))
        except Exception:
            return url

    def is_same_domain(self, url1: str, url2: str) -> bool:
        """Return True if both URLs share the same registerable domain."""
        return self.get_domain(url1) == self.get_domain(url2)

    def is_subdomain(self, url: str, base_url: str) -> bool:
        """Return True if *url* is on a subdomain of *base_url*'s domain.

        Also returns True when the domains are identical (same domain counts
        as a "subdomain" of itself for crawl-inclusion purposes).

        Examples
        --------
        >>> n.is_subdomain("https://docs.example.com", "https://example.com")
        True
        >>> n.is_subdomain("https://other.com", "https://example.com")
        False
        """
        url_host = self._host(url)
        base_host = self._host(base_url)
        if not url_host or not base_host:
            return False

        # Exact match
        if url_host == base_host:
            return True

        # url_host ends with ".base_host"
        return url_host.endswith(f".{base_host}")

    def matches_glob(self, url_path: str, patterns: list[str]) -> bool:
        """Return True if *url_path* matches ANY of *patterns*.

        Pattern syntax
        --------------
        ``*``   — matches any characters within a single path segment
                  (i.e. does not cross ``/`` boundaries).
        ``**``  — matches any characters across any number of segments
                  (crosses ``/`` boundaries).
        ``?``   — matches exactly one character (not ``/``).

        The match is anchored: the pattern must match the full path.

        Examples
        --------
        >>> n.matches_glob("/docs/intro", ["/docs/*"])
        True
        >>> n.matches_glob("/docs/api/ref", ["/docs/*"])
        False
        >>> n.matches_glob("/docs/api/ref", ["/docs/**"])
        True
        >>> n.matches_glob("/blog/2024/post", ["/blog/????/*"])
        True
        """
        if not patterns:
            return False

        # Normalise path: ensure leading slash, no trailing slash
        path = "/" + url_path.lstrip("/")
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")

        for pattern in patterns:
            pat = "/" + pattern.lstrip("/")
            if pat != "/" and pat.endswith("/"):
                pat = pat.rstrip("/")

            if self._glob_match(path, pat):
                return True

        return False

    def url_hash(self, url: str) -> str:
        """Return the SHA-256 hex digest of the normalised URL.

        This is the canonical deduplication key used throughout the crawl
        system.  Always 64 hex characters.
        """
        return hashlib.sha256(self.normalize(url).encode()).hexdigest()

    # ------------------------------------------------------------------
    # Internal normalisation pipeline
    # ------------------------------------------------------------------

    def _normalize(self, url: str) -> str:
        """Core normalisation — called by normalize() after input validation."""
        # Step 1: Parse
        split = urlsplit(url)

        # Reject non-HTTP(S) schemes early
        scheme = split.scheme.lower()
        if scheme not in ("http", "https"):
            # Return as-is; callers validate scheme separately
            return url

        # Step 2: Lowercase host
        host = split.hostname or ""
        host = host.lower()

        # Step 3: Remove default ports
        port = split.port
        if port and _DEFAULT_PORTS.get(scheme) == port:
            port = None

        # Reconstruct netloc
        netloc = host
        if port:
            netloc = f"{host}:{port}"

        # Step 4: Drop fragment (already excluded by urlsplit when we rebuild)

        # Step 5-6: Normalise path encoding, then resolve . and ..
        path = self._normalize_path_encoding(split.path)
        path = self._resolve_dot_segments(path)

        # Step 8: Consecutive slashes already collapsed in _normalize_path_encoding.
        # Apply regex as a safety net for any edge cases.
        if path and not path.startswith("//"):
            leading = "/" if path.startswith("/") else ""
            interior = path.lstrip("/")
            collapsed = _DOUBLE_SLASH.sub("/", interior)
            path = leading + collapsed

        # Step 9: Remove trailing slash (except root)
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")

        # Treat bare root "/" as empty path so the output is "https://host"
        # not "https://host/" — both are equivalent but the shorter form is
        # the canonical one used throughout the system.
        if path == "/":
            path = ""

        # Steps 10-11: Process query string
        query = self._normalize_query(split.query)

        # Step 4 (fragment): omit entirely
        return urlunsplit((scheme, netloc, path, query, ""))

    def _normalize_path_encoding(self, path: str) -> str:
        """Decode over-encoded unreserved chars; re-encode anything that
        should be encoded but isn't.

        RFC 3986 §2.3: unreserved characters SHOULD NOT be percent-encoded.
        RFC 3986 §3.3: path segments may contain sub-delims, ":", "@".

        We process each segment individually so that literal "/" separators
        are never percent-encoded.  Empty segments (from consecutive slashes)
        are dropped here, which collapses "//path" → "/path".
        """
        if not path:
            return path

        # Split on "/" to process each segment independently.
        segments = path.split("/")
        normalised: list[str] = []
        for i, seg in enumerate(segments):
            if i == 0:
                # First element: empty string if path starts with "/"
                # Keep it to preserve the leading slash.
                normalised.append(quote(unquote(seg), safe=_PATH_SAFE))
            elif seg == "":
                # Empty segment = consecutive slash — drop it (collapse //)
                continue
            else:
                decoded = unquote(seg)
                normalised.append(quote(decoded, safe=_PATH_SAFE))
        return "/".join(normalised)

    def _resolve_dot_segments(self, path: str) -> str:
        """Remove . and .. segments per RFC 3986 §5.2.4.

        Uses urljoin against a dummy base to leverage the stdlib's
        already-correct implementation.  We guard against the edge case
        where a path starting with "//" would be misinterpreted as a
        protocol-relative URL by urljoin.
        """
        if "." not in path:
            return path

        # Prevent urljoin from treating "//..." as a protocol-relative URL
        # by temporarily replacing the leading double-slash.
        had_double_leading = path.startswith("//")
        if had_double_leading:
            path = path[1:]  # strip one leading slash; restore after

        resolved = urljoin("http://x", path)
        result = urlsplit(resolved).path

        if had_double_leading:
            result = "/" + result
        return result

    def _normalize_query(self, query: str) -> str:
        """Sort query parameters and strip tracking params.

        Preserves parameters with empty values (e.g. ``?flag``).
        """
        if not query:
            return ""

        params: list[tuple[str, str]] = []
        for part in query.split("&"):
            if not part:
                continue
            if "=" in part:
                key, _, value = part.partition("=")
            else:
                key, value = part, ""

            # Normalise key encoding (keys are case-sensitive per RFC)
            key = unquote(key)

            # Strip tracking parameters
            if key in TRACKING_PARAMS:
                continue

            # Normalise value encoding
            value = quote(unquote(value), safe=_QUERY_SAFE)

            params.append((key, value))

        if not params:
            return ""

        # Sort alphabetically by key, then by value for stability
        params.sort(key=lambda kv: (kv[0], kv[1]))

        return "&".join(f"{k}={v}" if v else k for k, v in params)

    # ------------------------------------------------------------------
    # Glob matching
    # ------------------------------------------------------------------

    def _glob_match(self, path: str, pattern: str) -> bool:
        """Match *path* against *pattern* with ``*``, ``**``, ``?`` support.

        ``**`` is converted to a regex that matches any characters including
        ``/``.  ``*`` matches any characters except ``/``.  ``?`` matches
        exactly one character that is not ``/``.
        """
        # Convert glob pattern to regex
        regex = self._glob_to_regex(pattern)
        return bool(re.fullmatch(regex, path))

    @staticmethod
    def _glob_to_regex(pattern: str) -> str:
        """Convert a glob pattern to a regex string.

        Conversion rules:
        - ``**`` → ``.*``          (any chars including /)
        - ``*``  → ``[^/]*``       (any chars except /)
        - ``?``  → ``[^/]``        (one char except /)
        - All other regex metacharacters are escaped.
        """
        # We process the pattern character by character to handle ** vs *
        result: list[str] = []
        i = 0
        while i < len(pattern):
            ch = pattern[i]
            if ch == "*":
                if i + 1 < len(pattern) and pattern[i + 1] == "*":
                    result.append(".*")
                    i += 2
                    # Skip optional trailing slash after **
                    if i < len(pattern) and pattern[i] == "/":
                        result.append("/?")
                        i += 1
                else:
                    result.append("[^/]*")
                    i += 1
            elif ch == "?":
                result.append("[^/]")
                i += 1
            else:
                result.append(re.escape(ch))
                i += 1
        return "".join(result)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _host(self, url: str) -> str:
        """Extract and lowercase the hostname from *url*."""
        try:
            return urlsplit(url).hostname or ""
        except Exception:
            return ""


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_normalizer: URLNormalizer | None = None


def get_url_normalizer() -> URLNormalizer:
    """Return the process-wide URLNormalizer singleton."""
    global _normalizer
    if _normalizer is None:
        _normalizer = URLNormalizer()
    return _normalizer
