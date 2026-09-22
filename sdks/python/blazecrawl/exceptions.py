"""SDK exceptions."""


class BlazeCrawlError(Exception):
    """Base SDK error with optional HTTP status and payload."""

    def __init__(self, message, status_code=None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class AuthError(BlazeCrawlError):
    """401 — missing/invalid API key."""


class ValidationError(BlazeCrawlError):
    """400/422 — invalid request (including SSRF-rejected URLs)."""


class RateLimitError(BlazeCrawlError):
    """429 — rate limited."""


class NotFoundError(BlazeCrawlError):
    """404 — resource not found."""
