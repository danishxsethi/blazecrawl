# README visual demos

Original BlazeCrawl branding and reproducible, **real product demonstrations**.
The primary generation route captures a native local instance and renders its output
into the branded GIFs used by the repository README. No Docker daemon is required.

## What gets generated

| Demo | Real operation | GIF | Duration |
|---|---|---|---|
| Hero | Native launch, `/health`, CLI scrape to Markdown | `docs/assets/blazecrawl-hero.gif` | ~16 s |
| Map / crawl | Discover URLs, then crawl at most three pages | `docs/assets/blazecrawl-map-crawl.gif` | ~12 s |
| MCP | Initialize, list tools, call `scrape` over stdio | `docs/assets/blazecrawl-mcp.gif` | ~10 s |
| Security | Public scrape succeeds; loopback URL is rejected | `docs/assets/blazecrawl-security.gif` | ~11 s |

Each GIF has a corresponding `.png` poster showing its final state. The README links
those posters directly; animations are never the only source of essential instructions.
`docs/assets/blazecrawl-brand.svg` is an original, static vector graphic edited separately.

## Truthfulness and provenance

- Every displayed command is executed against a real, temporary BlazeCrawl instance.
  Commands are launched as argument arrays; wrapped visual lines are not separate shell commands.
- Output is actual program output, not scripted success text. Server startup shows selected
  real log lines; map shows the actual count and first three URLs; crawl shows actual completion
  fields. MCP shows the actual tool list and first returned Markdown paragraph.
- The recording launches the native API through `python scripts/readme_demo/capture.py --serve`,
  **not Docker**. This capture-only Uvicorn helper uses stdin closure for graceful shutdown,
  avoiding Windows console signals that would also interrupt Playwright's child processes.
  It must not be presented as evidence that a container ran. Normal users launch with
  `blazecrawl-server`; the README's Docker onboarding is a separate path.
- The native capture stores the source commit, package version, UTC capture time, readiness
  response, and full map/crawl responses in the capture JSON. Keep that JSON outside the repository.
- Credentials are supplied through the process environment. A new random, temporary key is
  generated for each capture; it is never displayed or written to the capture. Authentication stays on.
- The MCP demonstration is a real protocol exchange, not a simulated AI conversation. No LLM
  participates. The MCP scrape explicitly selects static rendering.
- Public targets are `example.com` for scraping and `quotes.toscrape.com` for map/crawl.
  The blocked destination is a loopback URL. No private data source or external scraping service is used.
- Captures fail explicitly if the browser is unhealthy, a command fails unexpectedly, content is
  missing, a crawl fails, or the expected rejection is absent. Old footage is not substituted.
- Typing/reveal pacing and transitions are editorial presentation choices, **not elapsed-time
  measurements**. These clips make no latency, throughput, or competitor claims.

The checked-in clips were freshly captured on **2026-10-01**, from the native `v0.1.2` source
installation. The current set, including PNG posters and the brand SVG, is approximately **0.69 MB**.

## Prerequisites

Python 3.11+, [uv](https://docs.astral.sh/uv/), Git, network access to the public demo targets,
and an installed Chromium browser through Playwright. The commands below install the core,
Python SDK, Python MCP server, and media requirements into an isolated `.venv`.

Rendering uses **Pillow**, pinned in `requirements.txt`; it is not a core runtime dependency.
Supply installed regular sans-serif, bold sans-serif, and monospace `.ttf` fonts explicitly.
Font files are not copied into or distributed by the repository. Different fonts can change
line wrapping and appearance; clipping checks fail instead of dropping output.

## Native generation on Windows

Run from the repository root in PowerShell:

```powershell
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -e . -e .\sdks\python -e .\mcp\python -r .\scripts\readme_demo\requirements.txt

$env:PATH = (Join-Path (Get-Location) ".venv\Scripts") + ";" + $env:PATH
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location) ".venv\browsers"
python -m playwright install chromium

python .\scripts\readme_demo\capture.py --output "$env:TEMP\blazecrawl-readme-capture.json"
if ($LASTEXITCODE -ne 0) { throw "Capture failed; do not render a previous capture." }
python .\scripts\readme_demo\render.py "$env:TEMP\blazecrawl-readme-capture.json" --mono "$env:WINDIR\Fonts\consola.ttf" --sans "$env:WINDIR\Fonts\segoeui.ttf" --bold "$env:WINDIR\Fonts\seguisb.ttf"
```

The font example uses installed Windows fonts; use your own installed paths if needed.
Port `8017` must be free, or pass `--port PORT` to `capture.py`. The API is bound to `127.0.0.1`.
The script verifies readiness, performs the real operations, and gracefully shuts down its
own server and browser pool. Its temporary state directory is removed afterward.

## Native generation on Linux

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e . -e ./sdks/python -e ./mcp/python \
  -r scripts/readme_demo/requirements.txt
export PATH="$PWD/.venv/bin:$PATH"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.venv/browsers"
python -m playwright install --with-deps chromium

python scripts/readme_demo/capture.py --output /tmp/blazecrawl-readme-capture.json &&
python scripts/readme_demo/render.py /tmp/blazecrawl-readme-capture.json \
  --mono /usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf \
  --sans /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf \
  --bold /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
```

The font example requires DejaVu fonts installed at those paths. Browser OS dependency
installation may require elevated privileges. macOS can use the same native flow with its
virtual-environment/font paths and `playwright install chromium`.

## Rendering checks and budgets

`render.py` renders into a temporary directory, verifies every GIF, then copies the finished
assets into `docs/assets`. Use `--assets DIRECTORY` to write somewhere else.

| Property | Required |
|---|---|
| Dimensions | 1200 x 730 |
| Duration | 10-20 seconds per play |
| Animation | Multiple frames; two plays total (`loop=1`), then stops |
| GIF size | At most 1,000,000 bytes each |
| Total visual set | At most 3,000,000 bytes, including posters and brand SVG |
| Readability | Captured text fits the panel; no output silently clipped |

Generation prints actual frame counts, durations, and byte sizes. Inspect representative
frames and the finished README in light/dark themes and a narrow viewport before committing.
GitHub does not give README GIFs a reliable reduced-motion switch or playback control;
finite loops and explicit static links mitigate that limitation, but do not remove it.

## Earlier Docker / asciinema route

The existing `session_*.sh`, `render.sh`, and `optimize.sh` scripts retain the Linux
Docker/asciinema workflow for terminal-only recordings. They require Docker, asciinema,
`agg`, `gifsicle`, `ffmpeg`, and a Python environment providing the CLI and MCP server.
That route **overwrites the same demo filenames with the earlier terminal presentation**;
use the native capture plus `render.py` for the branded assets above.

```bash
export AGG=/path/to/agg
export BLAZECRAWL_CLI_VENV=/path/to/cli-and-mcp-venv
bash scripts/readme_demo/render.sh
bash scripts/readme_demo/optimize.sh
```

Those legacy scripts use fixed Docker resource names. Review their targeted cleanup before
running them on a shared host. Neither capture route should be used to claim performance
measurements or security coverage beyond the specific real operations shown.
