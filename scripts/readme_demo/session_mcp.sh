#!/usr/bin/env bash
# MCP / AI-agent demo session. RECORDED by asciinema.
#
# TRUTHFULNESS: the single "$" command shown is the command actually executed —
# scripts/readme_demo/run_mcp_demo, which invokes the real, standards-compliant
# MCP stdio client against a real blazecrawl-mcp server (initialize ->
# tools/list -> tools/call scrape). Explanatory lines are presented WITHOUT a
# shell prompt. No LLM is involved or implied.
set -euo pipefail

export BLAZECRAWL_API_URL="${BLAZECRAWL_DEMO_URL:-http://127.0.0.1:8010}"
export BLAZECRAWL_API_KEY="${BLAZECRAWL_DEMO_KEY:?set BLAZECRAWL_DEMO_KEY}"

typeline() {
  local text="$1" i
  for ((i = 0; i < ${#text}; i++)); do printf '%s' "${text:i:1}"; sleep 0.018; done
  sleep 0.25; printf '\n'
}

clear
printf '  \033[1;33mMCP\033[0m — give an AI client web-extraction tools, self-hosted\n'
sleep 0.9

# Explanatory captions (no shell prompt — these are not commands).
printf '  \033[2mAI client → MCP → BlazeCrawl → web\033[0m\n'
printf '  \033[2mblazecrawl-mcp serves scrape / map / crawl over stdio\033[0m\n'
sleep 0.9

# The one shell command shown is the one actually run. Its output is the real
# MCP exchange.
typeline '$ scripts/readme_demo/run_mcp_demo'
scripts/readme_demo/run_mcp_demo
sleep 2.0

printf '\n  \033[1;32m✓\033[0m real MCP exchange   \033[1;32m✓\033[0m no third-party scraping service\n'
sleep 2.0
