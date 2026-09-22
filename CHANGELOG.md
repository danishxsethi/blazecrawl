# Changelog

All notable changes to BlazeCrawl Core. Format follows Keep a Changelog;
versioning follows SemVer.

## [0.1.0] — RC1

### Added
- `/v1/scrape`, `/v1/map`, `/v1/crawl` (BFS, same-origin, robots-enforced).
- Clean Markdown extraction (readability → trafilatura → BeautifulSoup).
- Hybrid rendering: static fetch with browser fallback (Playwright).
- Security-first egress: SSRF validate + pin-at-connect, DNS-rebinding
  resistance, private/loopback/link-local/metadata blocking, redirect
  re-validation, https→http downgrade blocking, response size caps, browser
  request interception guard, WebRTC IP-leak mitigation.
- Local API-key auth (generated on first start; loopback-only disable option).
- Caching (memory default, optional Redis) and in-process crawl queue.
- Python SDK, Node SDK, CLI, Python MCP server, Node MCP server.
- Docker / docker-compose zero-config self-host.
