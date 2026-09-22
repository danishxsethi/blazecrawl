# BlazeCrawl Core

**Security-first, self-hostable web-data engine.** Turn web pages into clean,
LLM-ready Markdown and structured data via three endpoints: `/v1/scrape`,
`/v1/crawl`, and `/v1/map`.

BlazeCrawl Core is the **open-source engine**. It is built for people who want
to run their own scraping infrastructure **without handing their URLs, traffic,
or credentials to a third party** — and without giving up the outbound-request
security that most self-hosted scrapers skip.

## What it is

* A single-binary, self-hosted web-data API you run yourself.
* Hardened by default: every outbound fetch is **SSRF-validated and
  pinned-at-connect** (DNS-rebinding resistant), blocks private/loopback/
  link-local/cloud-metadata ranges, blocks `https→http` redirect downgrades,
  and caps response sizes.
* Browser-backed rendering (Playwright) for JS-heavy pages, with a fast static
  path for simple pages.
* robots.txt-respecting crawler (same-origin BFS).
* Python SDK, Node SDK, CLI, and MCP servers.

## What it is not

* **Not a hosted SaaS.** There is no account to create and no external service
  to sign up for. You run it; you own it.
* **Not a managed anti-bot / residential-proxy product.** Managed proxy fleets,
  managed LLM extraction, enterprise SSO/SCIM, and multi-tenant metering are
  part of the separate commercial *BlazeCrawl Cloud* — they are deliberately
  excluded here (see [docs/OSS_VS_CLOUD.md](docs/OSS_VS_CLOUD.md)).
* **Not a "Firecrawl killer".** It is a focused, security-first engine. No
  inflated benchmark claims — see [docs/BENCHMARKS.md](docs/BENCHMARKS.md) for
  our own reproducible baseline methodology.

## Why it exists

Most self-hosted scrapers treat the outbound request as trusted. BlazeCrawl
Core treats every user-supplied URL as hostile: it resolves the host once,
validates every returned address against a private/reserved denylist, pins the
connection to the validated IP (so DNS can't be rebound between check and use),
and re-validates every redirect hop. That posture is the point.

## Quickstart (Docker)

Prerequisites: Docker + Docker Compose.

```bash
git clone <this-repo>
cd blazecrawl
docker compose up --build
```

The API listens on `http://localhost:8000` (loopback only). On first start it
generates a local API key, writes it to the `api-state` volume
(`/data/blazecrawl/api_key`, mode `0600`), and shows it once in the logs:

```bash
docker compose logs api | grep "first run"
# [blazecrawl] first run: generated local API key and wrote it to
#   /data/blazecrawl/api_key (mode 0600). Key (shown once): blz_local_xxxxxxxx
```

Restart the stack and the same key is reused silently.

```bash
curl -X POST http://localhost:8000/v1/scrape \
  -H "Authorization: Bearer blz_local_xxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com"}'
```

> **Stable keys:** set your own key and it will never be persisted or printed:
> `BLAZECRAWL_API_KEY=my-secret-key docker compose up`. To expose the API
> beyond loopback, change the published port deliberately and put TLS in front.

> **Trusted local development:** to skip the API key entirely, run bound to
> loopback with auth explicitly disabled:
> `BLAZECRAWL_AUTH_DISABLED=true BLAZECRAWL_HOST=127.0.0.1`.
> This is refused on any non-loopback bind.

## Local (no Docker)

```bash
pip install -e .
playwright install chromium
blazecrawl-server          # serves on http://127.0.0.1:8000
```

## API

| Endpoint | Description |
|---|---|
| `GET /health` | Liveness. |
| `GET /ready` | Readiness + browser-pool/cache/queue status. |
| `POST /v1/scrape` | Scrape a URL → Markdown/HTML/text/links/images. |
| `POST /v1/map` | Discover a site's URL set (sitemap + link graph). |
| `POST /v1/crawl` | Start a same-origin BFS crawl (async job). |
| `GET /v1/crawl/{id}` | Poll crawl status/results. |
| `DELETE /v1/crawl/{id}` | Cancel a crawl. |

### Scrape

```bash
curl -X POST http://localhost:8000/v1/scrape \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","formats":["markdown","links"],"render":"auto"}'
```

`render` is `auto` (static, with browser fallback when content is thin),
`static`, or `browser`.

### Map

```bash
curl -X POST http://localhost:8000/v1/map \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"url":"https://example.com"}'
```

### Crawl

```bash
curl -X POST http://localhost:8000/v1/crawl \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","max_pages":25,"max_depth":2}'
# → {"job_id":"...","status_url":"/v1/crawl/..."}
curl http://localhost:8000/v1/crawl/<job_id> -H "Authorization: Bearer $KEY"
```

## SDKs & CLI

**Python**

```python
from blazecrawl import BlazeCrawl

with BlazeCrawl(api_key="blz_local_...") as bc:
    print(bc.scrape("https://example.com")["markdown"])
```

**Node**

```js
import { BlazeCrawl } from "@blazecrawl/sdk";
const doc = await new BlazeCrawl({ apiKey: "blz_local_..." }).scrape("https://example.com");
console.log(doc.markdown);
```

**CLI**

```bash
export BLAZECRAWL_API_KEY=blz_local_...
blazecrawl scrape https://example.com
blazecrawl map https://example.com
blazecrawl crawl https://example.com --max-pages 25 --wait
```

**MCP** (Claude Code, etc.)

```json
{
  "mcpServers": {
    "blazecrawl": {
      "command": "blazecrawl-mcp",
      "env": { "BLAZECRAWL_API_KEY": "blz_local_..." }
    }
  }
}
```

## Architecture

```
        ┌────────────────────────────────────────────┐
 SDK ──▶│  FastAPI  /v1/scrape  /v1/map  /v1/crawl   │
 CLI ──▶│                                            │
 MCP ──▶│  auth (local key)                          │
        └───────┬────────────────────────────────────┘
                │
     ┌──────────▼───────────┐     ┌──────────────────────────┐
     │  network/egress      │     │  engine                  │
     │  • SSRF validate+pin │────▶│  • content extraction    │
     │  • manual redirects  │     │    (readability/trafil.) │
     │  • private-IP block  │     │  • HTML → Markdown       │
     │  • browser req guard │     │  • browser pool (Playwright)
     └──────────────────────┘     │  • crawler (BFS + robots)│
                                   │  • cache (memory|redis)  │
                                   └──────────────────────────┘
```

Full details in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Security model

BlazeCrawl Core is designed to be safe to point at arbitrary URLs. Highlights:

* DNS-rebinding-resistant egress (resolve-once + pin-at-connect).
* Private/loopback/link-local/cloud-metadata/IPv4-mapped-IPv6 blocked.
* `https→http` redirect downgrades blocked; redirect hops re-validated.
* Response size caps; per-hop timeouts; browser request interception guard.
* robots.txt enforced and not configurable-off in the OSS core.

See [SECURITY.md](SECURITY.md) for the disclosure policy and
[docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md) for the full model.

## Maturity

`v0.1.0` — early release. The scrape/map/crawl engine, egress security, SDKs,
CLI and MCP are functional and tested. This is **not yet** battle-hardened at
large scale; please report issues. See [CHANGELOG.md](CHANGELOG.md) and the
[roadmap](docs/ROADMAP.md).

## Contributing

We welcome contributions — see [CONTRIBUTING.md](CONTRIBUTING.md) and the
good-first-issue backlog in [docs/CONTRIBUTION_BACKLOG.md](docs/CONTRIBUTION_BACKLOG.md).

## License

Apache-2.0 — see [LICENSE](LICENSE).
