# BlazeCrawl OSS vs BlazeCrawl Cloud

## BlazeCrawl Core (this repository) — the engine

Open-source (Apache-2.0). Provides:

* scrape / crawl / map
* clean Markdown + structured extraction
* browser-backed rendering
* hardened outbound-request security (SSRF / egress)
* Python & Node SDKs, CLI, MCP servers
* self-hosted Docker deployment

The OSS core is **not artificially crippled**. It is the same engine, fully
usable at single-node scale.

## BlazeCrawl Cloud — the managed product (separate, commercial)

Adds operational capabilities that are genuinely hard to run yourself:

* managed residential/ISP/mobile proxy fleets and anti-bot routing
* managed LLM extraction (Vertex) with context caching and cost optimization
* multi-tenant tenancy, SSO/SCIM, audit logging
* hosted billing/metering and quotas
* global distributed crawling, managed scaling, observability, SLAs, support

## The contract

The cloud product should win because **operating large-scale crawling
infrastructure is difficult** — not because basic engine features are disabled
in OSS. If a core capability is useful to a self-hoster, it belongs here.
