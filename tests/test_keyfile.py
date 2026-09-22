"""Tests for the persistent local API-key bootstrap (WP4 Stage 3)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from blazecrawl_core.api.keyfile import ApiKeyFileError, bootstrap_api_key, state_dir


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    monkeypatch.delenv("BLAZECRAWL_API_KEY", raising=False)
    monkeypatch.setenv("BLAZECRAWL_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def test_first_start_generates_key(tmp_path):
    printed = []
    key, generated = bootstrap_api_key(print_fn=printed.append)
    assert generated is True
    assert key.startswith("blz_local_")
    path = Path(state_dir()) / "api_key"
    assert path.exists()
    assert path.read_text().strip() == key
    # Exactly one first-run message naming the file.
    assert len(printed) == 1
    assert str(path) in printed[0]


def test_key_file_mode_is_0600():
    bootstrap_api_key(print_fn=lambda *_: None)
    path = Path(state_dir()) / "api_key"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(Path(state_dir()).stat().st_mode) == 0o700


def test_restart_returns_same_key_without_printing():
    printed = []
    key1, _ = bootstrap_api_key(print_fn=printed.append)
    printed.clear()
    key2, generated = bootstrap_api_key(print_fn=printed.append)
    assert key2 == key1
    assert generated is False
    assert printed == []  # raw secret must not be re-printed on restart


def test_explicit_env_key_overrides_and_never_persists_or_prints(monkeypatch):
    monkeypatch.setenv("BLAZECRAWL_API_KEY", "blz_operator_secret_key_123456")
    printed = []
    key, generated = bootstrap_api_key(print_fn=printed.append)
    assert key == "blz_operator_secret_key_123456"
    assert generated is False
    assert printed == []
    assert not (Path(state_dir()) / "api_key").exists()


def test_malformed_key_file_fails_clearly():
    path = Path(state_dir())
    path.mkdir(parents=True)
    (path / "api_key").write_text("not-a-valid-key")
    with pytest.raises(ApiKeyFileError, match="malformed"):
        bootstrap_api_key(print_fn=lambda *_: None)


def test_empty_key_file_fails_clearly():
    path = Path(state_dir())
    path.mkdir(parents=True)
    (path / "api_key").write_text("\n")
    with pytest.raises(ApiKeyFileError, match="malformed"):
        bootstrap_api_key(print_fn=lambda *_: None)


def test_unreadable_key_file_fails_safely():
    path = Path(state_dir())
    path.mkdir(parents=True)
    kf = path / "api_key"
    kf.write_text("blz_local_validlookingkey0123456789")
    if os.geteuid() == 0:  # chmod is advisory for root (CI containers)
        pytest.skip("running as root; permission failure not reproducible")
    kf.chmod(0o000)
    try:
        with pytest.raises(ApiKeyFileError, match="not readable"):
            bootstrap_api_key(print_fn=lambda *_: None)
    finally:
        kf.chmod(0o600)


def test_missing_state_directory_is_created_safely(tmp_path):
    # state dir does not exist yet; bootstrap must create it 0700 and succeed.
    key, generated = bootstrap_api_key(print_fn=lambda *_: None)
    assert generated is True
    assert stat.S_IMODE(Path(state_dir()).stat().st_mode) == 0o700
    assert key.startswith("blz_local_")


def test_auth_uses_persisted_key_across_reset(monkeypatch):
    from blazecrawl_core.api import auth
    from blazecrawl_core.config import settings

    printed = []
    settings.BLAZECRAWL_API_KEY = None
    auth.reset_key_cache()
    k1 = auth.effective_api_key()
    auth.reset_key_cache()
    k2 = auth.effective_api_key()
    assert k1 == k2
    assert printed == []
