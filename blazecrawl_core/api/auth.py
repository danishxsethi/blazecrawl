"""Local authentication for BlazeCrawl Core (Stage 5).

Model (hybrid of Options B + C):

* By default the API requires a bearer API key. If the operator does not set
  ``BLAZECRAWL_API_KEY``, a key is bootstrapped from a persistent local state
  file (mode 0600) on first start and reused across restarts — see
  ``api/keyfile.py``. The raw key is printed once, on first generation only.
* Auth may be disabled ONLY by explicitly setting ``BLAZECRAWL_AUTH_DISABLED=true``
  AND binding to a loopback address. This is a trusted-local-development
  convenience and is refused on a non-loopback bind so the engine can never
  silently become an unauthenticated open proxy on a routable interface.

There is no signup flow, no email verification, no external identity provider.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from blazecrawl_core.api.keyfile import bootstrap_api_key
from blazecrawl_core.config import settings
from blazecrawl_core.logging import get_logger

logger = get_logger(__name__)

_resolved_key: str | None = None


def _is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


def reset_key_cache() -> None:
    """Test hook: forget the cached resolved key."""
    global _resolved_key
    _resolved_key = None


def effective_api_key() -> str | None:
    """Return the active API key, bootstrapping the persistent key file if needed."""
    global _resolved_key
    if settings.BLAZECRAWL_API_KEY:
        return settings.BLAZECRAWL_API_KEY
    if _resolved_key is None:
        _resolved_key, generated = bootstrap_api_key()
        if generated:
            logger.info(
                "No BLAZECRAWL_API_KEY set; generated a persistent local API key "
                "(written once, mode 0600). Subsequent restarts reuse it silently."
            )
        else:
            logger.info("Using persisted local API key from state file.")
    return _resolved_key


def auth_enforced() -> bool:
    """Return whether requests must present a valid API key."""
    if not settings.BLAZECRAWL_AUTH_DISABLED:
        return True
    if not _is_loopback(settings.BLAZECRAWL_HOST):
        logger.error(
            "BLAZECRAWL_AUTH_DISABLED ignored: host is not loopback. "
            "Refusing to run unauthenticated on a routable interface.",
            host=settings.BLAZECRAWL_HOST,
        )
        return True
    logger.warning("Authentication disabled (loopback-only trusted mode)")
    return False


async def require_api_key(request: Request) -> None:
    """FastAPI dependency enforcing the local API key."""
    if not auth_enforced():
        return
    expected = effective_api_key()
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    if not token or not secrets.compare_digest(token, expected or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "authentication_required", "message": "Valid API key required."},
        )


# Convenience dependency alias.
AuthDep = Annotated[None, Depends(require_api_key)]
