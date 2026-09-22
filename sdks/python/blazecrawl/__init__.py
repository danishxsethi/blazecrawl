"""BlazeCrawl Python SDK (OSS)."""

from blazecrawl.client import BlazeCrawl
from blazecrawl.exceptions import (
    AuthError,
    BlazeCrawlError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)

__version__ = "0.1.0"
__all__ = [
    "BlazeCrawl",
    "BlazeCrawlError",
    "AuthError",
    "NotFoundError",
    "RateLimitError",
    "ValidationError",
    "__version__",
]
