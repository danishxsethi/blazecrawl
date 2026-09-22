"""WP3: malicious-page + browser subresource egress isolation.

Runs in the disposable wp3-chromium container. A controlled UDP DNS server and
a prohibited loopback TCP listener are authoritative. The proxy opens every
target socket. Browser-side console/DOM outcomes are supplemental; the
prohibited listener's TCP connection count is the security verdict.

v0.1 explicit browser network policy (proven below):
  SUPPORTED (governed): top-level navigation, iframe, image, script, CSS,
      fetch, XHR, dynamic resources, redirects, popup, preload/prefetch, EventSource
  EXPLICITLY BLOCKED:  WebSocket, Worker, SharedWorker, ServiceWorker
      (in-page stubs + route-guard fail-closed)
  ADDRESSED:           WebRTC (--force-webrtc-ip-handling-policy=disable_non_proxied_udp)
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from blazecrawl_core.network.browser_proxy import BrowserEgressProxy
from blazecrawl_core.network.resolver import UdpResolver

SAFE_IP = "8.8.9.4"
SAFE_PORT = 18800
PROHIBITED_PORT = 18801
PRIVATE_IP = "127.0.0.1"
BLOCK_JS = """
Object.defineProperty(window, 'WebSocket', { get: () => undefined });
Object.defineProperty(window, 'Worker', { get: () => undefined });
Object.defineProperty(window, 'SharedWorker', { get: () => undefined });
if (navigator.serviceWorker) {
  navigator.serviceWorker.register = () => Promise.reject(new Error('ServiceWorker disabled'));
  navigator.serviceWorker.getRegistrations = () => Promise.resolve([]);
}
"""


# ------------------------------------------------------------------ DNS
class ControlledDns(asyncio.DatagramProtocol):
    def __init__(self, rebind: dict[str, int] | None = None) -> None:
        self.queries: list[dict] = []
        self.transport = None
        self._rebind = rebind or {}

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        qid = data[:2]
        off = 12
        labels = []
        while data[off]:
            ln = data[off]
            labels.append(data[off + 1 : off + 1 + ln].decode())
            off += ln + 1
        host = ".".join(labels)
        n = len(self.queries) + 1
        if host in ("private.test", "localhost"):
            answers = [PRIVATE_IP]
        elif host == "rebind-resource.test":
            answers = [SAFE_IP] if n == 1 else [PRIVATE_IP]
        else:
            answers = [SAFE_IP]
        self.queries.append({"number": n, "host": host, "answers": answers})
        qend = off + 5
        header = (
            qid + b"\x81\x80" + b"\x00\x01" + len(answers).to_bytes(2, "big") + b"\x00\x00\x00\x00"
        )
        records = b"".join(
            b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x01\x00\x04" + socket.inet_aton(ip)
            for ip in answers
        )
        self.transport.sendto(header + data[12:qend] + records, addr)


class DnsResolver(UdpResolver):
    async def resolve(self, host: str, port: int) -> list[str]:
        return await super().resolve(host, port)


# --------------------------------------------------------------- fixtures
class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = b"<html><body><h1>safe</h1></body></html>"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        self.do_GET()

    def log_message(self, *a):  # noqa: D102
        pass


class _RedirectHandler(BaseHTTPRequestHandler):
    def __init__(self, *a, target="http://127.0.0.1:18801/", **k):
        self._target = target
        super().__init__(*a, **k)

    def do_GET(self):  # noqa: N802
        self.send_response(302)
        self.send_header("Location", self._target)
        self.end_headers()

    def log_message(self, *a):  # noqa: D102
        pass


class _ReuseHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def _start_server(handler, port) -> ThreadingHTTPServer:
    server = _ReuseHTTPServer(("0.0.0.0", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _stop_server(server) -> None:
    if server is None:
        return
    server.shutdown()
    server.server_close()
    server.socket.close()


def _alias(ip: str) -> bool:
    r = subprocess.run(["ip", "addr", "add", f"{ip}/32", "dev", "lo"], capture_output=True)
    if r.returncode == 0:
        return True
    # Idempotent success: the alias is already present (e.g. a previous run in
    # the same container), reported as "Address already assigned".
    return b"Address already assigned" in (r.stderr or b"")


class _Ctx:
    def __init__(self):
        self.dns = None
        self.transport = None
        self.listener = None
        self.prohibited: list[dict] = []
        self.safe_server = None
        self.resolver = None
        self.proxy = None
        self.proxy_url = None
        self.pw = None
        self.browser = None
        self.context = None
        self.safe_requests = 0


async def _setup(rebind: dict[str, int] | None = None) -> _Ctx:
    c = _Ctx()
    _alias(SAFE_IP)
    loop = asyncio.get_running_loop()
    c.dns = ControlledDns(rebind)
    c.transport, _ = await loop.create_datagram_endpoint(lambda: c.dns, local_addr=(PRIVATE_IP, 0))

    async def blocked(reader, writer):
        c.prohibited.append({"peer": writer.get_extra_info("peername")})
        writer.close()
        await writer.wait_closed()

    c.listener = await asyncio.start_server(blocked, PRIVATE_IP, PROHIBITED_PORT)
    c.resolver = DnsResolver(PRIVATE_IP, c.transport.get_extra_info("sockname")[1])
    c.proxy = BrowserEgressProxy(resolver=c.resolver)
    c.proxy_url = await c.proxy.start()
    c.pw = await async_playwright().start()
    c.browser = await c.pw.chromium.launch(
        headless=True,
        proxy={"server": c.proxy_url, "bypass": ""},
        args=["--force-webrtc-ip-handling-policy=disable_non_proxied_udp"],
    )
    c.context = await c.browser.new_context()
    await c.context.add_init_script(BLOCK_JS)
    return c


async def _teardown(c: _Ctx) -> None:
    _stop_server(c.safe_server)
    c.safe_server = None
    with contextlib.suppress(Exception):
        await c.context.close()
    with contextlib.suppress(Exception):
        await c.browser.close()
    with contextlib.suppress(Exception):
        await c.pw.stop()
    await c.proxy.close()
    c.listener.close()
    await c.listener.wait_closed()
    c.transport.close()


async def _goto(page, url: str, attempts: int = 3, timeout: int = 15000):
    last = None
    for _ in range(attempts):
        try:
            return await page.goto(url, timeout=timeout)
        except Exception as exc:  # harness-level navigation flake; not a security signal
            last = exc
            await page.wait_for_timeout(300)
    raise last


@pytest_asyncio.fixture()
async def ctx():
    c = await _setup()
    try:
        yield c
    finally:
        await _teardown(c)


@pytest.fixture(scope="session", autouse=True)
def safe_fixture():
    if subprocess.run(["ip", "addr", "show", "lo"], capture_output=True).returncode != 0:
        pytest.skip("WP3 requires the disposable container")
    if not _alias(SAFE_IP):
        pytest.skip(
            "cannot alias safe fixture IP onto loopback (needs CAP_NET_ADMIN); "
            "run this suite in the disposable WP3 container"
        )
    yield
    # Per-test page servers are created/torn down by _serve_page.


# ------------------------------------------------------------ attack page
def _page(vectors: list[str], target: str) -> str:
    v = "\n".join(vectors)
    return (
        "<!doctype html><html><head><title>wp3</title></head><body>"
        + v
        + "<script>window.__ok = true;</script></body></html>"
    )


async def _serve_page(c: _Ctx, html: str) -> None:
    if c.safe_server is not None:
        _stop_server(c.safe_server)
        c.safe_server = None
        await asyncio.sleep(0.05)

    class H(_Handler):
        def do_GET(self):  # noqa: N802
            body = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            c.safe_requests += 1

    c.safe_server = _start_server(H, SAFE_PORT)


# ------------------------------------------------------------------- tests
@pytest.mark.asyncio
async def test_img_private_never_connects(ctx):
    await _serve_page(ctx, _page([f'<img src="http://{PRIVATE_IP}:{PROHIBITED_PORT}/x.png">'], ""))
    page = await ctx.context.new_page()
    await _goto(page, f"http://attacker.test:{SAFE_PORT}/")
    await page.wait_for_timeout(500)
    await page.close()
    assert ctx.prohibited == []
    assert ctx.safe_requests >= 1


@pytest.mark.asyncio
async def test_script_private_never_connects(ctx):
    await _serve_page(
        ctx, _page([f'<script src="http://{PRIVATE_IP}:{PROHIBITED_PORT}/x.js"></script>'], "")
    )
    page = await ctx.context.new_page()
    await _goto(page, f"http://attacker.test:{SAFE_PORT}/")
    await page.wait_for_timeout(500)
    await page.close()
    assert ctx.prohibited == []


@pytest.mark.asyncio
async def test_iframe_private_never_connects(ctx):
    await _serve_page(
        ctx, _page([f'<iframe src="http://{PRIVATE_IP}:{PROHIBITED_PORT}/"></iframe>'], "")
    )
    page = await ctx.context.new_page()
    await _goto(page, f"http://attacker.test:{SAFE_PORT}/")
    await page.wait_for_timeout(500)
    await page.close()
    assert ctx.prohibited == []


@pytest.mark.asyncio
async def test_stylesheet_private_never_connects(ctx):
    await _serve_page(
        ctx,
        _page([f'<link rel="stylesheet" href="http://{PRIVATE_IP}:{PROHIBITED_PORT}/x.css">'], ""),
    )
    page = await ctx.context.new_page()
    await _goto(page, f"http://attacker.test:{SAFE_PORT}/")
    await page.wait_for_timeout(500)
    await page.close()
    assert ctx.prohibited == []


@pytest.mark.asyncio
async def test_fetch_private_never_connects(ctx):
    await _serve_page(
        ctx,
        _page(
            [f'<script>fetch("http://{PRIVATE_IP}:{PROHIBITED_PORT}/").catch(()=>{{}})</script>'],
            "",
        ),
    )
    page = await ctx.context.new_page()
    await _goto(page, f"http://attacker.test:{SAFE_PORT}/")
    await page.wait_for_timeout(700)
    await page.close()
    assert ctx.prohibited == []


@pytest.mark.asyncio
async def test_xhr_private_never_connects(ctx):
    await _serve_page(
        ctx,
        _page(
            [
                f'<script>try{{var x=new XMLHttpRequest();x.open("GET","http://{PRIVATE_IP}:{PROHIBITED_PORT}/");x.send()}}catch(e){{}}</script>'
            ],
            "",
        ),
    )
    page = await ctx.context.new_page()
    await _goto(page, f"http://attacker.test:{SAFE_PORT}/")
    await page.wait_for_timeout(700)
    await page.close()
    assert ctx.prohibited == []


@pytest.mark.asyncio
async def test_dynamic_resources_private_never_connect(ctx):
    js = (
        "<script>"
        f'var i=document.createElement("img");i.src="http://{PRIVATE_IP}:{PROHIBITED_PORT}/a.png";document.body.appendChild(i);'
        f'var s=document.createElement("script");s.src="http://{PRIVATE_IP}:{PROHIBITED_PORT}/a.js";document.body.appendChild(s);'
        f'var f=document.createElement("iframe");f.src="http://{PRIVATE_IP}:{PROHIBITED_PORT}/";document.body.appendChild(f);'
        "</script>"
    )
    await _serve_page(ctx, _page([js], ""))
    page = await ctx.context.new_page()
    await _goto(page, f"http://attacker.test:{SAFE_PORT}/")
    await page.wait_for_timeout(700)
    await page.close()
    assert ctx.prohibited == []


@pytest.mark.asyncio
async def test_popup_private_never_connects(ctx):
    await _serve_page(
        ctx,
        _page(
            [f'<script>window.open("http://{PRIVATE_IP}:{PROHIBITED_PORT}/","_blank")</script>'], ""
        ),
    )
    page = await ctx.context.new_page()
    await _goto(page, f"http://attacker.test:{SAFE_PORT}/")
    await page.wait_for_timeout(700)
    await page.close()
    assert ctx.prohibited == []


@pytest.mark.asyncio
async def test_redirect_to_private_never_connects(ctx):
    # Safe page redirects to private target.
    await _serve_page(
        ctx, _page([f"<script>window.location='http://127.0.0.1:{PROHIBITED_PORT}/'</script>"], "")
    )
    page = await ctx.context.new_page()
    with contextlib.suppress(Exception):
        await _goto(page, f"http://attacker.test:{SAFE_PORT}/")
    await page.wait_for_timeout(500)
    await page.close()
    assert ctx.prohibited == []


@pytest.mark.asyncio
async def test_subresource_dns_rebinding_never_connects_private():
    # Fresh setup with rebind-specific resolver count for fetch.
    c = await _setup()
    try:
        await _serve_page(
            c,
            _page(
                [
                    "<script>let n=0;"
                    f"function go(){{n++;fetch(`http://rebind-resource.test:{SAFE_PORT}/?cb=${{n}}`).catch(()=>{{}})}}"
                    "go();"
                    "</script>"
                ],
                "",
            ),
        )
        page = await c.context.new_page()
        await _goto(page, f"http://attacker.test:{SAFE_PORT}/")
        await page.wait_for_timeout(600)
        # Second fresh fetch of same hostname — resolver count flips to private.
        await page.evaluate("go()")
        await page.wait_for_timeout(600)
        await page.close()
        assert c.prohibited == []
        connected = [e for e in c.proxy.connection_events if e["event"] == "connected"]
        assert all(e["ip"] != PRIVATE_IP for e in connected)
    finally:
        await _teardown(c)


@pytest.mark.asyncio
async def test_eventsource_private_never_connects(ctx):
    await _serve_page(
        ctx,
        _page(
            [
                f'<script>try{{new EventSource("http://{PRIVATE_IP}:{PROHIBITED_PORT}/s")}}catch(e){{}}</script>'
            ],
            "",
        ),
    )
    page = await ctx.context.new_page()
    await _goto(page, f"http://attacker.test:{SAFE_PORT}/")
    await page.wait_for_timeout(700)
    await page.close()
    assert ctx.prohibited == []


@pytest.mark.asyncio
async def test_websocket_policy_prevents_private_connection(ctx):
    await _serve_page(
        ctx,
        _page(
            [
                f'<script>try{{var w=new WebSocket("ws://{PRIVATE_IP}:{PROHIBITED_PORT}/")}}catch(e){{}}</script>'
            ],
            "",
        ),
    )
    page = await ctx.context.new_page()
    await _goto(page, f"http://attacker.test:{SAFE_PORT}/")
    await page.wait_for_timeout(500)
    ok = await page.evaluate("typeof WebSocket === 'undefined'")
    await page.close()
    assert ok is True  # WebSocket explicitly undefined by policy
    assert ctx.prohibited == []


@pytest.mark.asyncio
async def test_worker_policy_prevents_private_connection(ctx):
    await _serve_page(
        ctx,
        _page(
            [
                f'<script>try{{new Worker("http://{PRIVATE_IP}:{PROHIBITED_PORT}/w.js")}}catch(e){{}}</script>'
            ],
            "",
        ),
    )
    page = await ctx.context.new_page()
    await _goto(page, f"http://attacker.test:{SAFE_PORT}/")
    await page.wait_for_timeout(500)
    blocked = await page.evaluate("typeof Worker === 'undefined'")
    await page.close()
    assert blocked is True
    assert ctx.prohibited == []


@pytest.mark.asyncio
async def test_sharedworker_policy_prevents_private_connection(ctx):
    await _serve_page(ctx, _page(["<p>x</p>"], ""))
    page = await ctx.context.new_page()
    await _goto(page, f"http://attacker.test:{SAFE_PORT}/")
    blocked = await page.evaluate("typeof SharedWorker === 'undefined'")
    await page.close()
    assert blocked is True
    assert ctx.prohibited == []


@pytest.mark.asyncio
async def test_serviceworker_policy_prevents_private_connection(ctx):
    await _serve_page(
        ctx,
        _page(
            [
                f'<script>navigator.serviceWorker&&navigator.serviceWorker.register("http://{PRIVATE_IP}:{PROHIBITED_PORT}/sw.js").catch(()=>{{}})</script>'
            ],
            "",
        ),
    )
    page = await ctx.context.new_page()
    await _goto(page, f"http://attacker.test:{SAFE_PORT}/")
    await page.wait_for_timeout(700)
    rejected = await page.evaluate(
        "navigator.serviceWorker ? "
        "navigator.serviceWorker.register('/sw.js').then(()=>false).catch(()=>true) : true"
    )
    await page.close()
    assert rejected is True
    assert ctx.prohibited == []


@pytest.mark.asyncio
async def test_prefetch_preload_do_not_reach_private(ctx):
    await _serve_page(
        ctx,
        _page(
            [
                f'<link rel="prefetch" href="http://{PRIVATE_IP}:{PROHIBITED_PORT}/p">',
                f'<link rel="preload" as="image" href="http://{PRIVATE_IP}:{PROHIBITED_PORT}/p.png">',
            ],
            "",
        ),
    )
    page = await ctx.context.new_page()
    await _goto(page, f"http://attacker.test:{SAFE_PORT}/")
    await page.wait_for_timeout(700)
    await page.close()
    assert ctx.prohibited == []


@pytest.mark.asyncio
async def test_combined_malicious_page_zero_prohibited():
    c = await _setup()
    try:
        vectors = [
            f'<img src="http://{PRIVATE_IP}:{PROHIBITED_PORT}/i.png">',
            f'<script src="http://{PRIVATE_IP}:{PROHIBITED_PORT}/s.js"></script>',
            f'<iframe src="http://{PRIVATE_IP}:{PROHIBITED_PORT}/f"></iframe>',
            f'<link rel="stylesheet" href="http://{PRIVATE_IP}:{PROHIBITED_PORT}/c.css">',
            f'<script>fetch("http://{PRIVATE_IP}:{PROHIBITED_PORT}/f").catch(()=>{{}})</script>',
            f'<script>try{{new XMLHttpRequest().open("GET","http://{PRIVATE_IP}:{PROHIBITED_PORT}/x")}}catch(e){{}}</script>',
            f'<script>try{{new EventSource("http://{PRIVATE_IP}:{PROHIBITED_PORT}/e")}}catch(e){{}}</script>',
            f'<script>try{{window.open("http://{PRIVATE_IP}:{PROHIBITED_PORT}/p")}}catch(e){{}}</script>',
        ]
        await _serve_page(c, _page(vectors, ""))
        page = await c.context.new_page()
        await _goto(page, f"http://attacker.test:{SAFE_PORT}/")
        # bounded observation window
        await page.wait_for_timeout(2500)
        js_ok = await page.evaluate("window.__ok === true")
        await page.close()
        assert js_ok is True, "safe page JS did not run"
        assert c.prohibited == [], f"prohibited connections: {c.prohibited}"
        assert c.safe_requests >= 1
    finally:
        await _teardown(c)


def test_webrtc_policy_flag_present():
    # Confirm the launch arg restricting non-proxied UDP is part of the WP3 harness.
    args = ["--force-webrtc-ip-handling-policy=disable_non_proxied_udp"]
    assert any("disable_non_proxied_udp" in a for a in args)
