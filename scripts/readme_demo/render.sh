#!/usr/bin/env bash
# Render all README demo GIFs from their asciinema casts.
#
# Orchestration:
#   1. HERO is self-contained: session_hero.sh starts its own published container
#      (the visible `docker run` is the executed command), reads its local key
#      from the logs without printing it, and cleans up after itself.
#   2. A shared disposable instance (loopback-only, demo key) is then started for
#      the map/crawl, security, and MCP demos, and stopped afterward.
#   3. Each cast is rendered to a GIF with agg and optimized with gifsicle.
#
# Truthfulness standard: every line displayed with a "$" shell prompt is actually
# executed; architectural captions are presented without a shell prompt; and all
# product output shown comes from real BlazeCrawl execution. See README.md in
# this directory for prerequisites.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
WORK="${README_DEMO_WORK:-/tmp/blazecrawl-readme-demo}"
CASTS="$WORK/casts"
OUT_RAW="$WORK/raw"
mkdir -p "$CASTS" "$OUT_RAW"

# --- tool locations (override via env if installed elsewhere) ----------------
AGG="${AGG:-$(command -v agg || true)}"
ASCIIINEMA="${ASCIIINEMA:-$(command -v asciinema || true)}"
GIFSICLE="${GIFSICLE:-$(command -v gifsicle || true)}"
FFMPEG="${FFMPEG:-$(command -v ffmpeg || true)}"

for tool in AGG ASCIIINEMA GIFSICLE FFMPEG; do
  eval "val=\"\$$tool\""
  if [ -z "$val" ]; then
    echo "missing required tool: $tool (see scripts/readme_demo/README.md)" >&2
    exit 1
  fi
done

# --- demo instance ------------------------------------------------------------
DEMO_NAME="blazecrawl-readme-demo"
DEMO_VOLUME="blazecrawl-readme-demo-data"
DEMO_PORT="${README_DEMO_PORT:-8010}"
DEMO_URL="http://127.0.0.1:${DEMO_PORT}"
# Obviously non-secret, loopback-only demo value. Satisfies the key format
# (blz_local_ prefix, >=16 chars) without being a real credential.
DEMO_KEY="blz_local_readme_demo"
IMAGE="ghcr.io/danishxsethi/blazecrawl:0.1.2"

start_demo() {
  echo ">> starting disposable demo instance ($IMAGE on $DEMO_URL)"
  docker rm -f "$DEMO_NAME" >/dev/null 2>&1 || true
  docker volume rm "$DEMO_VOLUME" >/dev/null 2>&1 || true
  docker run -d --name "$DEMO_NAME" \
    -p "127.0.0.1:${DEMO_PORT}:8000" \
    -e "BLAZECRAWL_API_KEY=${DEMO_KEY}" \
    -v "${DEMO_VOLUME}:/data/blazecrawl" \
    "$IMAGE" >/dev/null
  # wait for readiness
  local i
  for i in $(seq 1 60); do
    if curl -fsS "$DEMO_URL/ready" >/dev/null 2>&1; then break; fi
    sleep 1
  done
  curl -fsS "$DEMO_URL/health" >/dev/null
  echo ">> demo instance ready"
}

stop_demo() {
  echo ">> cleaning up demo instance"
  docker rm -f "$DEMO_NAME" >/dev/null 2>&1 || true
  docker volume rm "$DEMO_VOLUME" >/dev/null 2>&1 || true
}

record() {
  # record <name> <session-script> <cols> <rows>
  local name="$1" script="$2" cols="$3" rows="$4"
  echo ">> recording $name"
  # BLAZECRAWL_CLI_VENV prepends a venv that provides the `blazecrawl` CLI and
  # `blazecrawl-mcp` server (used by the map-crawl and mcp sessions).
  BLAZECRAWL_DEMO_URL="$DEMO_URL" BLAZECRAWL_DEMO_KEY="$DEMO_KEY" \
    PATH="${BLAZECRAWL_CLI_VENV:+$BLAZECRAWL_CLI_VENV/bin:}$PATH" \
    "$ASCIIINEMA" rec --command "bash \"$REPO_ROOT/$script\"" \
    --cols "$cols" --rows "$rows" --overwrite "$CASTS/$name.cast" >/dev/null
}

render() {
  # render <name> <cols> <rows> <font-size>
  local name="$1" cols="$2" rows="$3" font="$4"
  echo ">> rendering $name.gif"
  "$AGG" --cols "$cols" --rows "$rows" --font-size "$font" \
    --theme github-dark --idle-time-limit 2 --last-frame-duration 2 \
    "$CASTS/$name.cast" "$OUT_RAW/$name.gif" >/dev/null
}

main() {
  # HERO first: fully self-contained (starts and cleans up its own container).
  # No shared instance is running yet, so the hero's port 8000 is free.
  echo ">> recording hero (self-contained)"
  "$ASCIIINEMA" rec --command "bash \"$REPO_ROOT/scripts/readme_demo/session_hero.sh\"" \
    --cols 100 --rows 24 --overwrite "$CASTS/hero.cast" >/dev/null
  render hero 100 24 18

  # Shared disposable instance for the remaining demos.
  start_demo
  trap stop_demo EXIT

  # map -> crawl
  record map-crawl scripts/readme_demo/session_map_crawl.sh 100 24
  render map-crawl 100 24 18

  # security / egress
  record security scripts/readme_demo/session_security.sh 100 24
  render security 100 24 18

  # mcp
  record mcp scripts/readme_demo/session_mcp.sh 100 24
  render mcp 100 24 18

  echo ">> raw GIFs in $OUT_RAW"
  echo ">> next: run scripts/readme_demo/optimize.sh"
}

main "$@"
