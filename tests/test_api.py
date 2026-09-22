"""API journey tests using FastAPI TestClient (auth-disabled loopback mode)."""

import os

import pytest

os.environ.setdefault("BLAZECRAWL_AUTH_DISABLED", "true")
os.environ.setdefault("BLAZECRAWL_HOST", "127.0.0.1")

from fastapi.testclient import TestClient  # noqa: E402

from blazecrawl_core.api.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["mode"] == "oss"


def test_ready(client):
    assert client.get("/ready").status_code == 200


def test_scrape_requires_url(client):
    r = client.post("/v1/scrape", json={})
    assert r.status_code == 422


def test_scrape_blocks_ssrf(client):
    for bad in ["http://127.0.0.1/", "http://169.254.169.254/", "http://[::1]/"]:
        r = client.post("/v1/scrape", json={"url": bad})
        assert r.status_code == 400, bad
        assert r.json()["detail"]["error"] == "url_rejected"


def test_scrape_example_com(client):
    r = client.post("/v1/scrape", json={"url": "https://example.com"})
    assert r.status_code == 200
    d = r.json()
    assert d["success"] is True
    assert "Example Domain" in (d["data"]["markdown"] or "")


def test_map_example_com(client):
    r = client.post("/v1/map", json={"url": "https://example.com"})
    assert r.status_code == 200
    assert r.json()["success"] is True
    assert isinstance(r.json()["urls"], list)


def test_crawl_lifecycle(client):
    r = client.post(
        "/v1/crawl", json={"url": "https://example.com", "max_pages": 1, "max_depth": 0}
    )
    assert r.status_code == 202
    jid = r.json()["job_id"]
    import time

    for _ in range(40):
        g = client.get(f"/v1/crawl/{jid}")
        assert g.status_code == 200
        if g.json()["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.3)
    assert g.json()["status"] == "completed"


def test_crawl_blocks_ssrf(client):
    r = client.post("/v1/crawl", json={"url": "http://192.168.0.1/"})
    assert r.status_code == 400


def test_crawl_not_found(client):
    assert client.get("/v1/crawl/does-not-exist").status_code == 404
