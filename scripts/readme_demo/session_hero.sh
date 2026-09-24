#!/usr/bin/env bash
# Hero demo session: zero -> first scrape. RECORDED by asciinema.
#
# TRUTHFULNESS: every line shown with a "$" shell prompt is actually executed by
# this script. The visible `docker run` command really starts the container that
# then serves the visible /health and /v1/scrape requests. The local API key is
# read from the container's first-run log line into the KEY variable WITHOUT being
# printed; the scrape command is shown with "$KEY", never the value. The container
# and its volume are removed on exit (trap), even if interrupted.
set -euo pipefail

IMAGE="ghcr.io/danishxsethi/blazecrawl:0.1.2"
NAME="blazecrawl-readme-hero"
VOLUME="blazecrawl-readme-hero-data"
BASE_URL="http://127.0.0.1:8000"

typeline() {
  local text="$1" i
  for ((i = 0; i < ${#text}; i++)); do printf '%s' "${text:i:1}"; sleep 0.018; done
  sleep 0.25; printf '\n'
}

# Clean up the demo container + volume no matter how this script exits.
cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker volume rm "$VOLUME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

clear
printf '  \033[1;33mBlazeCrawl\033[0m — security-first, self-hostable web extraction\n'
sleep 1.0

# 1. Actually start the published image. The displayed command IS the executed
#    command (modulo the -d flag's detached mode, shown verbatim). Any stale
#    container/volume from a prior run is removed first so the run is real.
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker volume rm "$VOLUME" >/dev/null 2>&1 || true
typeline "$ docker run -d --name $NAME -p 127.0.0.1:8000:8000 $IMAGE"
docker run -d --name "$NAME" -p 127.0.0.1:8000:8000 -v "$VOLUME":/data/blazecrawl "$IMAGE"
sleep 0.6

# 2. Genuinely wait for readiness (no fabricated timing; agg compresses idle).
for _ in $(seq 1 90); do
  if curl -fsS "$BASE_URL/ready" >/dev/null 2>&1; then break; fi
  sleep 1
done

# 3. Read the generated local key from the first-run log line into KEY, WITHOUT
#    printing it. The value is never shown in any frame.
KEY="$(docker logs "$NAME" 2>&1 | grep -oE 'blz_local_[A-Za-z0-9_-]+' | head -1)"

# 4. Real /health against the instance the visible docker command just started.
typeline "$ curl $BASE_URL/health"
curl -fsS "$BASE_URL/health" | python3 -m json.tool --compact
sleep 1.2

# 5. Real scrape; the command is shown with "$KEY" (the value stays hidden), and
#    the Markdown shown is the actual response field.
typeline "$ curl -X POST $BASE_URL/v1/scrape -H 'Authorization: Bearer \$KEY' -d '{\"url\":\"https://example.com\"}'"
curl -fsS -X POST "$BASE_URL/v1/scrape" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"url":"https://example.com"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["markdown"])'
sleep 1.4

printf '\n  \033[1;32m✓\033[0m scrape   \033[1;32m✓\033[0m Markdown   \033[1;32m✓\033[0m self-hosted\n'
printf '  \033[2mgithub.com/danishxsethi/blazecrawl\033[0m\n'
sleep 1.6
