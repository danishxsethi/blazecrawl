# Roadmap

BlazeCrawl Core is `v0.1.0`. This is a directional roadmap, not a commitment;
priorities follow real usage and contributor interest.

## Now (0.1.x)
* scrape / crawl / map, Markdown, browser rendering, SSRF hardening
* Python + Node SDK, CLI, MCP servers, Docker self-host
* hardening, tests, docs, contributor onboarding

## Next (0.2)
* pluggable search-provider interface (community adapters)
* pluggable LLM-extraction provider interface
* Redis-backed distributed crawl queue backend
* local filesystem export (JSONL/Markdown)
* browser-pool metrics + Prometheus exporter
* screenshot output format

## Later (0.3+)
* plugin/extractor registry
* change detection / diffing
* scheduled crawls
* additional document parsers (PDF) with size/sandbox guards

## Explicitly out of scope for OSS Core
Managed proxies, managed anti-bot, managed LLM execution, SSO/SCIM, billing,
multi-tenant metering — see [OSS_VS_CLOUD.md](OSS_VS_CLOUD.md).

Vote/discuss on the GitHub issue tracker.
