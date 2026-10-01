"""Capture real native BlazeCrawl demonstrations; never synthesize product output."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = "https://quotes.toscrape.com"


def serve() -> None:
    import uvicorn

    from blazecrawl_core.config import settings

    server = uvicorn.Server(
        uvicorn.Config(
            "blazecrawl_core.api.main:app",
            host=settings.BLAZECRAWL_HOST,
            port=settings.BLAZECRAWL_PORT,
        )
    )

    def request_shutdown() -> None:
        sys.stdin.read()
        server.should_exit = True

    # EOF shuts down Uvicorn without sending Ctrl+Break to its Playwright children.
    threading.Thread(target=request_shutdown, daemon=True).start()
    server.run()


def execute(args: list[str], env: dict[str, str], expected: int = 0) -> str:
    result = subprocess.run(
        args, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=240
    )
    if result.returncode != expected:
        raise RuntimeError(
            f"{Path(args[0]).name} exited {result.returncode}, expected {expected}:\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return (result.stdout if expected == 0 else result.stderr).strip()


def stage(label: str, command: str, output: str, note: str) -> dict[str, str]:
    return {"label": label, "command": command, "output": output, "note": note}


def capture(output: Path, port: int) -> None:
    cli = shutil.which("blazecrawl")
    if not cli:
        raise RuntimeError("Missing blazecrawl; install the core in the active environment.")

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
        port = probe.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "BLAZECRAWL_HOST": "127.0.0.1",
        "BLAZECRAWL_PORT": str(port),
        "BLAZECRAWL_API_URL": base,
        "BLAZECRAWL_API_KEY": "blz_local_" + secrets.token_urlsafe(24),
        "BLAZECRAWL_AUTH_DISABLED": "false",
        "CRAWL_QUEUE_BACKEND": "memory",
        "BROWSER_POOL_SIZE": "1",
        "PYTHONIOENCODING": "utf-8",
        "NO_COLOR": "1",
    }
    env.pop("REDIS_URL", None)
    records = {}
    with tempfile.TemporaryDirectory(prefix="blazecrawl-readme-") as temporary:
        env["BLAZECRAWL_STATE_DIR"] = temporary
        log_path = Path(temporary) / "server.log"
        with log_path.open("w", encoding="utf-8") as log:
            server = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--serve"],
                cwd=ROOT,
                env=env,
                stdin=subprocess.PIPE,
                stdout=log,
                stderr=log,
            )
            try:
                deadline = time.monotonic() + 90
                while True:
                    if server.poll() is not None:
                        raise RuntimeError(log_path.read_text(encoding="utf-8"))
                    try:
                        with urllib.request.urlopen(f"{base}/ready", timeout=2) as response:
                            ready = json.load(response)
                        break
                    except (urllib.error.URLError, TimeoutError) as exc:
                        if time.monotonic() >= deadline:
                            raise RuntimeError(
                                "Demo server did not become ready:\n" + log_path.read_text()
                            ) from exc
                        time.sleep(0.5)
                if server.poll() is not None or not ready["browser"]["is_healthy"]:
                    raise RuntimeError(
                        "Demo requires a healthy Chromium pool:\n" + log_path.read_text()
                    )
                print(f"Capture server ready on {base}; Chromium healthy.", flush=True)

                health = execute([cli, "health"], env)
                if json.loads(health)["status"] != "ok":
                    raise RuntimeError(f"Unexpected health response: {health}")
                markdown = execute(
                    [cli, "scrape", "https://example.com", "--render", "static"], env
                )
                if "documentation examples" not in markdown:
                    raise RuntimeError(f"Scrape did not return expected real Markdown: {markdown}")
                launch = "\n".join(
                    line
                    for line in log_path.read_text(encoding="utf-8").splitlines()
                    if "Application startup complete" in line or "Uvicorn running on" in line
                )
                if not launch:
                    raise RuntimeError("Server startup evidence is missing.")
                records["hero"] = {
                    "title": "One URL. Useful Markdown.",
                    "subtitle": "A real local launch, health check, and scrape.",
                    "stages": [
                        stage(
                            "Start your engine",
                            "python scripts/readme_demo/capture.py --serve",
                            launch,
                            "Native source install · bound to loopback",
                        ),
                        stage(
                            "Check the connection",
                            "blazecrawl health",
                            health,
                            "Actual /health response · authenticated API configured",
                        ),
                        stage(
                            "Extract the page",
                            "blazecrawl scrape https://example.com --render static",
                            markdown,
                            "Actual Markdown · fetched through the egress boundary",
                        ),
                    ],
                }
                print("Captured launch, health, and Markdown.", flush=True)

                mapped_raw = execute([cli, "map", SITE], env)
                mapped = json.loads(mapped_raw)
                if not mapped["success"] or not mapped["urls"]:
                    raise RuntimeError(f"Map failed: {mapped_raw}")
                crawl_raw = execute(
                    [cli, "crawl", SITE, "--max-pages", "3", "--max-depth", "1", "--wait"], env
                )
                crawled = json.loads(crawl_raw)
                if crawled["status"] != "completed" or not 1 <= crawled["pages_crawled"] <= 3:
                    raise RuntimeError(f"Bounded crawl failed: {crawl_raw}")
                if not all(page.get("markdown") for page in crawled["pages"]):
                    raise RuntimeError("Crawl returned a page without Markdown.")
                records["map-crawl"] = {
                    "title": "Discover first. Crawl with limits.",
                    "subtitle": "Real URL discovery and a same-origin, bounded crawl.",
                    "stages": [
                        stage(
                            "Find the site's pages",
                            f"blazecrawl map {SITE}",
                            json.dumps(
                                {"count": mapped["count"], "urls": mapped["urls"][:3]}, indent=2
                            ),
                            "Selected response fields · first three discovered URLs",
                        ),
                        stage(
                            "Extract a bounded set",
                            f"blazecrawl crawl {SITE} --max-pages 3 --max-depth 1 --wait",
                            json.dumps(
                                {
                                    key: crawled[key]
                                    for key in ("status", "pages_crawled", "pages_failed")
                                },
                                indent=2,
                            ),
                            "Actual completion fields · same-origin crawl with robots rules",
                        ),
                    ],
                }
                print("Captured map and bounded crawl.", flush=True)

                mcp_output = execute(
                    [sys.executable, str(ROOT / "scripts" / "readme_demo" / "mcp_demo_client.py")],
                    env,
                )
                if "documentation examples" not in mcp_output:
                    raise RuntimeError(f"MCP did not return Markdown: {mcp_output}")
                records["mcp"] = {
                    "title": "Web tools for your AI client.",
                    "subtitle": "A real MCP exchange. A self-hosted extraction engine.",
                    "stages": [
                        stage(
                            "Connect over stdio",
                            "python scripts/readme_demo/mcp_demo_client.py",
                            mcp_output,
                            "Real MCP exchange · first Markdown paragraph · no LLM used",
                        ),
                    ],
                }
                blocked_raw = execute(
                    [cli, "scrape", "http://127.0.0.1/", "--render", "static"], env, expected=1
                )
                blocked = json.loads(blocked_raw)
                if blocked["detail"]["error"] != "url_rejected":
                    raise RuntimeError(f"Expected URL rejection, got: {blocked_raw}")
                records["security"] = {
                    "title": "Public pages in. Private networks out.",
                    "subtitle": "Real allowed and rejected requests, not simulated telemetry.",
                    "stages": [
                        stage(
                            "Fetch a public page",
                            "blazecrawl scrape https://example.com --render static",
                            markdown,
                            "Actual successful extraction · public destination",
                        ),
                        stage(
                            "Reject a loopback destination",
                            "blazecrawl scrape http://127.0.0.1/ --render static",
                            blocked_raw,
                            "Actual API rejection · CLI exit code 1",
                        ),
                    ],
                }
                print("Captured MCP and URL rejection.", flush=True)
                evidence = {
                    "captured_at": datetime.now(UTC).isoformat(),
                    "version": json.loads(health)["version"],
                    "source_commit": execute(["git", "rev-parse", "HEAD"], env),
                    "origin": "native source install",
                    "ready": ready,
                    "demos": records,
                    "full_map_response": mapped,
                    "full_crawl_response": crawled,
                }
                serialized = json.dumps(evidence, ensure_ascii=False, indent=2)
                if env["BLAZECRAWL_API_KEY"] in serialized:
                    raise RuntimeError("Refusing to write capture containing an API key.")
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(serialized + "\n", encoding="utf-8")
                print(f"Fresh capture written to {output}", flush=True)
            finally:
                if server.stdin is None:
                    raise RuntimeError("Capture server is missing its shutdown pipe.")
                server.stdin.close()
                try:
                    server.wait(timeout=30)
                except subprocess.TimeoutExpired as exc:
                    server.kill()
                    server.wait(timeout=10)
                    raise RuntimeError("The capture server did not shut down gracefully.") from exc


if __name__ == "__main__":
    if sys.argv[1:] == ["--serve"]:
        serve()
        raise SystemExit(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--port", type=int, default=8017, choices=range(1, 65536), metavar="PORT")
    arguments = parser.parse_args()
    capture(arguments.output, arguments.port)
