"""Structured logging for BlazeCrawl Core.

A self-contained subset of the original logging helpers, with no cloud
dependencies. Emits JSON-structured records with an optional request id.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

_request_id_var: Any = None

try:
    import contextvars

    _request_id_var = contextvars.ContextVar("blazecrawl_request_id", default=None)
except Exception:  # pragma: no cover - contextvars always available on py3.12
    _request_id_var = None


_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*\S+"),
    re.compile(r"blz_live_[A-Za-z0-9]+"),
    re.compile(r"sk_live_[A-Za-z0-9]+"),
]


def _redact(value: str) -> str:
    out = value
    for pat in _SECRET_PATTERNS:
        out = pat.sub(
            lambda m: (
                m.group(0).split("=")[0] + "=[REDACTED]" if "=" in m.group(0) else "[REDACTED]"
            ),
            out,
        )
    return out


def set_request_id(request_id: str | None = None) -> str:
    rid = request_id or hashlib.sha256(repr(id(object())).encode()).hexdigest()[:16]
    if _request_id_var is not None:
        _request_id_var.set(rid)
    return rid


def get_request_id() -> str | None:
    if _request_id_var is None:
        return None
    return _request_id_var.get()


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": _redact(record.getMessage()),
        }
        rid = get_request_id()
        if rid:
            payload["request_id"] = rid
        # Merge structlog-style extra dict if present.
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            for k, v in extra.items():
                payload[k] = v
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger("blazecrawl_core")
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    root.propagate = False
    _configured = True


class _Logger:
    """Thin adapter providing structlog-style kwargs on stdlib logging."""

    def __init__(self, name: str) -> None:
        _configure()
        self._log = logging.getLogger(name)

    def _emit(self, level: int, msg: str, **kwargs: Any) -> None:
        self._log.log(level, msg, extra={"extra": kwargs} if kwargs else None)

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._emit(logging.DEBUG, msg, **kwargs)

    def info(self, msg: str, **kwargs: Any) -> None:
        self._emit(logging.INFO, msg, **kwargs)

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._emit(logging.WARNING, msg, **kwargs)

    def error(self, msg: str, **kwargs: Any) -> None:
        self._emit(logging.ERROR, msg, **kwargs)

    def exception(self, msg: str, **kwargs: Any) -> None:
        self._log.exception(msg, extra={"extra": kwargs} if kwargs else None)


def get_logger(name: str) -> _Logger:
    return _Logger(name)
