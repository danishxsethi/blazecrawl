"""Persistent local API-key bootstrap.

Behavior:

* If ``BLAZECRAWL_API_KEY`` is set, it is used verbatim. It is never
  persisted to disk and never printed.
* Otherwise, a key is bootstrapped from a state file:

  1. The state directory is ``$BLAZECRAWL_STATE_DIR`` if set, else
     ``$XDG_STATE_HOME/blazecrawl`` if set, else ``~/.local/state/blazecrawl``.
  2. On first start a cryptographically secure key is generated and written
     exactly once to ``<state-dir>/api_key`` with mode ``0600``.
  3. On restart the same key is reused. The raw key is NOT re-printed; the
     first-run message identifying the file location is.

A malformed or unreadable key file is a hard startup error (fail closed) —
the server must never silently fall back to a different credential.
"""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path

KEY_PREFIX = "blz_local_"
KEY_FILE_NAME = "api_key"


class ApiKeyFileError(RuntimeError):
    """Raised when the persisted API key file is malformed or unreadable."""


def state_dir() -> Path:
    """Resolve the persistent BlazeCrawl state directory."""
    override = os.environ.get("BLAZECRAWL_STATE_DIR")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "blazecrawl"
    return Path.home() / ".local" / "state" / "blazecrawl"


def _validate_key(raw: str, source: Path) -> str:
    key = raw.strip()
    if not key or "\n" in raw.strip("\n") or " " in key:
        raise ApiKeyFileError(
            f"API key file {source} is malformed: expected a single non-empty token."
        )
    if not key.startswith(KEY_PREFIX):
        raise ApiKeyFileError(
            f"API key file {source} is malformed: key must start with {KEY_PREFIX!r}."
        )
    if len(key) < 16:
        raise ApiKeyFileError(f"API key file {source} is malformed: key is implausibly short.")
    return key


def _read_key(path: Path) -> str:
    try:
        raw = path.read_text(encoding="utf-8")
    except PermissionError as e:
        raise ApiKeyFileError(
            f"API key file {path} is not readable by this process "
            f"(permission denied). Fix ownership/mode or set BLAZECRAWL_API_KEY."
        ) from e
    except OSError as e:
        raise ApiKeyFileError(f"API key file {path} could not be read: {e}") from e
    return _validate_key(raw, path)


def _generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(24)


def _write_key_once(path: Path, key: str) -> None:
    """Write the key with mode 0600, refusing to overwrite an existing file."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, key.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    # Enforce mode regardless of process umask.
    os.chmod(path, 0o600)


def bootstrap_api_key(*, print_fn=print) -> tuple[str, bool]:
    """Resolve the effective API key.

    Returns ``(key, generated)`` where ``generated`` is True when a new key
    was created this run (first start). When generated, prints a concise
    first-run message — including the key once — via ``print_fn``.

    Raises ``ApiKeyFileError`` for malformed/unreadable persisted keys.
    """
    env_key = os.environ.get("BLAZECRAWL_API_KEY")
    if env_key:
        # Explicit operator deployment: use as-is, never persist, never print.
        return env_key, False

    base = state_dir()
    path = base / KEY_FILE_NAME

    if path.exists():
        return _read_key(path), False

    try:
        base.mkdir(parents=True, exist_ok=True)
        # Directory must be private to the owner.
        os.chmod(base, 0o700)
        key = _generate_key()
        _write_key_once(path, key)
    except ApiKeyFileError:
        raise
    except PermissionError as e:
        raise ApiKeyFileError(
            f"Cannot create API key file {path}: permission denied "
            f"({e}). Set BLAZECRAWL_STATE_DIR to a writable location or set "
            f"BLAZECRAWL_API_KEY explicitly."
        ) from e
    except OSError as e:
        raise ApiKeyFileError(f"Cannot create API key file {path}: {e}") from e

    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:  # pragma: no cover - defensive; chmod should guarantee this
        raise ApiKeyFileError(f"API key file {path} was created with mode {oct(mode)}, not 0600.")

    print_fn(
        f"[blazecrawl] first run: generated local API key and wrote it to {path} "
        f"(mode 0600). Key (shown once): {key}"
    )
    return key, True
