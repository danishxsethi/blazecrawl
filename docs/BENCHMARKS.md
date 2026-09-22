# Benchmarks

We publish **only our own reproducible baseline** — not competitor comparisons.
If you compare BlazeCrawl to another tool, you are responsible for an
equivalent, reproducible methodology.

## Methodology

* Target: `https://example.com` (a trivially small, stable page) so numbers
  reflect BlazeCrawl's own overhead, not the target's complexity.
* Environment: single Docker container, Linux x86_64, default settings
  (`BROWSER_POOL_SIZE=2`, memory/Redis cache), measured server-to-client over
  localhost HTTP.
* Each figure is the median of N runs; raw data in
  [benchmark_results.json](benchmark_results.json).
* No competitor benchmarks are included.

## Current baseline (v0.1.0)

| Metric | Value |
|---|---|
| Static scrape latency (p50) | ~70 ms |
| Cache-hit latency (p50) | ~1 ms |
| example.com Markdown size | 135 bytes |

## Caveats

* `example.com` is the best case; real pages with heavy JS, large DOMs, or slow
  origins are slower and may use the browser path.
* Throughput depends on `BROWSER_POOL_SIZE` / `MAX_CONCURRENT_SCRAPES` and
  target-site rate limits / robots `crawl-delay`.
* These are single-node numbers, not a distributed-fleet claim.

## Reproduce

```bash
docker compose up --build
# then run a loop of POST /v1/scrape against a chosen target and record timings
```
