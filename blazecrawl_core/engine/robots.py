"""robots.txt handling for BlazeCrawl Core (OSS).

Fetches and evaluates robots.txt through the SSRF-safe egress layer. Fails
*safe*: when robots cannot be fetched, crawlers must assume "allowed but be
polite" for well-known public content while still never bypassing an explicit
disallow that WAS retrieved. There is no configuration to disable robots
enforcement in the OSS core.
"""

from __future__ import annotations

import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from blazecrawl_core.logging import get_logger
from blazecrawl_core.network.egress import safe_fetch
from blazecrawl_core.network.ssrf import SSRFValidationError

logger = get_logger(__name__)

_DEFAULT_UA = "*"
_cache: dict[str, tuple[float, RobotFileParser | None]] = {}
_CACHE_TTL = 900.0  # 15 minutes


def _robots_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/robots.txt"


async def is_allowed(url: str, user_agent: str = _DEFAULT_UA) -> bool:
    """Return True when robots.txt permits fetching ``url``.

    Fetches/parses robots.txt (cached per-origin). On fetch/parse failure we
    return True (standard crawler behaviour for unreachable robots), but we
    never *fetch* a URL whose retrieved robots.txt disallows it.
    """
    origin_key = urlsplit(url).netloc
    now = time.time()

    cached = _cache.get(origin_key)
    if cached and (now - cached[0]) < _CACHE_TTL:
        rp = cached[1]
    else:
        rp = None
        try:
            resp = await safe_fetch(_robots_url(url), timeout_s=10.0, max_bytes=512 * 1024)
            if resp.status_code == 200:
                rp = RobotFileParser()
                rp.parse(resp.text.splitlines())
        except SSRFValidationError:
            raise
        except Exception as e:
            logger.debug("robots.txt fetch failed; treating as allowed", error=str(e))
            rp = None
        _cache[origin_key] = (now, rp)

    if rp is None:
        return True
    try:
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True
