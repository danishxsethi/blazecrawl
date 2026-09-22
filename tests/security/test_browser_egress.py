"""WP1B: real-browser browser egress qualification.

A real stateful UDP DNS server provides deterministic answers:
    safe.test    -> SAFE_IP (Docker container 8.8.8.2)
    private.test -> 127.0.0.1
    rebind.test  -> SAFE_IP on query 1, 127.0.0.1 afterwards
    mixed.test   -> SAFE_IP (test resolver returns both addresses; see below)

The injected ``UdpResolver`` sends REAL DNS UDP packets to the local
authoritative server. Chromium is launched with a real proxy configured to
``BrowserEgressProxy``. The prohibited destination is a real asyncio TCP
listener bound to 127.0.0.1:<port>; the suite fails on ANY connection.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import subprocess

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from blazecrawl_core.network.browser_proxy import BrowserEgressProxy
from blazecrawl_core.network.resolver import UdpResolver

SAFE_IP = "8.8.8.2"
PRIVATE_IP = "127.0.0.1"
SAFE_PORT = 18080
PROHIBITED_PORT = 18081


def _ensure_safe_fixture() -> bool:
    """Ensure 8.8.8.2:18080 serves HTTP (Docker container or host alias)."""
    try:
        with socket.create_connection((SAFE_IP, SAFE_PORT), timeout=2):
            return True
    except OSError:
        pass
    try:
        subprocess.run(
            [
                "docker",
                "network",
                "create",
                "--subnet",
                "8.8.8.0/24",
                "wp1bnet",
            ],
            capture_output=True,
            check=False,
        )
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                "wp1bsafe",
                "--network",
                "wp1bnet",
                "--ip",
                SAFE_IP,
                "busybox",
                "httpd",
                "-f",
                "-p",
                str(SAFE_PORT),
            ],
            capture_output=True,
            check=True,
        )
        with socket.create_connection((SAFE_IP, SAFE_PORT), timeout=5):
            return True
    except (OSError, subprocess.CalledProcessError, subprocess.SubprocessError):
        return False


@pytest.fixture(scope="session", autouse=True)
def safe_fixture():
    if not _ensure_safe_fixture():
        pytest.skip(f"cannot reach or start safe fixture at {SAFE_IP}:{SAFE_PORT}")
    yield
    subprocess.run(["docker", "rm", "-f", "wp1bsafe"], capture_output=True, check=False)


_dns_server: ControlledDns | None = None
_dns_transport: asyncio.DatagramTransport | None = None
_prohibited_server: asyncio.AbstractServer | None = None
_prohibited_connections: list[dict] = []


class ControlledDns(asyncio.DatagramProtocol):
    """Stateful authoritative DNS over real UDP."""

    def __init__(self) -> None:
        self.queries: list[dict] = []

    def connection_made(self, transport: asyncio.transports.BaseTransport) -> None:
        self.transport = transport  # type: ignore[attr-defined]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        query_id = data[:2]
        offset = 12
        labels = []
        while data[offset]:
            length = data[offset]
            labels.append(data[offset + 1 : offset + 1 + length].decode())
            offset += length + 1
        host = ".".join(labels)
        qtype = data[offset + 1 : offset + 3]
        number = len(self.queries) + 1

        answers: list[str] = []
        if host == "safe.test":
            answers = [SAFE_IP]
        elif host == "private.test":
            answers = [PRIVATE_IP]
        elif host == "rebind.test":
            answers = [SAFE_IP if number == 1 else PRIVATE_IP]
        elif host == "mixed.test":
            # DNS protocol limits single A answers; "mixed" is exercised at
            # the resolver level below (UdpResolver used with mixed.test
            # returns both addresses). DNS still returns SAFE_IP.
            answers = [SAFE_IP]

        self.queries.append(
            {
                "number": number,
                "host": host,
                "answers": answers,
                "timestamp": asyncio.get_event_loop().time(),
            }
        )
        if qtype == b"\x00\x1c":  # AAAA — return empty answer
            flags = b"\x81\x83"
            header = query_id + flags + b"\x00\x01\x00\x00\x00\x00\x00\x00"
            self.transport.sendto(header + data[12 : offset + 5], addr)
            return
        flags = b"\x81\x80"
        header = (
            query_id + flags + b"\x00\x01" + len(answers).to_bytes(2, "big") + b"\x00\x00\x00\x00"
        )
        body = data[12 : offset + 5]
        records = b""
        for a in answers:
            records += b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x00\x00\x04" + socket.inet_aton(a)
        self.transport.sendto(header + body + records, addr)


class MixedResolver(UdpResolver):
    """Returns SAFE_IP + PRIVATE_IP for mixed.test (real UDP for other hosts)."""

    async def resolve(self, host: str, port: int) -> list[str]:
        if host == "mixed.test":
            return [SAFE_IP, PRIVATE_IP]
        return await super().resolve(host, port)


async def start_dns() -> tuple[ControlledDns, asyncio.DatagramTransport]:
    loop = asyncio.get_running_loop()
    dns = ControlledDns()
    transport, _ = await loop.create_datagram_endpoint(lambda: dns, local_addr=(PRIVATE_IP, 0))
    return dns, transport


async def start_prohibited_listener() -> asyncio.AbstractServer:
    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        _prohibited_connections.append(
            {
                "source": writer.get_extra_info("peername"),
                "timestamp": asyncio.get_event_loop().time(),
            }
        )
        writer.close()
        await writer.wait_closed()

    return await asyncio.start_server(handler, PRIVATE_IP, PROHIBITED_PORT)


async def launch_browser(proxy_url: str):
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True, proxy={"server": proxy_url, "bypass": ""})
    return pw, browser


@pytest.fixture()
def dns() -> ControlledDns:
    assert _dns_server is not None
    return _dns_server


@pytest.fixture()
def prohibited_count() -> int:
    return len(_prohibited_connections)


@pytest.fixture()
def safe_ip() -> str:
    return SAFE_IP


@pytest.fixture()
def prohibited_ip() -> str:
    return PRIVATE_IP


@pytest.fixture()
def fixture_port() -> int:
    return SAFE_PORT


@pytest.fixture()
def prohibited_port() -> int:
    return PROHIBITED_PORT


@pytest_asyncio.fixture(autouse=True)
async def topology():
    """Fresh DNS state and prohibited listener for each test."""
    global _dns_server, _dns_transport, _prohibited_server, _udp_resolver
    _prohibited_connections.clear()
    _dns_server, _dns_transport = await start_dns()
    dns_port = _dns_transport.get_extra_info("sockname")[1]
    _udp_resolver = UdpResolver(PRIVATE_IP, dns_port)
    _prohibited_server = await start_prohibited_listener()
    yield
    _dns_transport.close()
    _prohibited_server.close()
    await _prohibited_server.wait_closed()


def resolver_for(test: str) -> UdpResolver:
    if test == "mixed":
        return MixedResolver(_udp_resolver.dns_host, _udp_resolver.dns_port)
    return _udp_resolver


async def run_browser_navigation(resolver, url: str, expect_success: bool = True):
    """Launch real Chromium, navigate, and return (proxy, response, browser_error)."""
    proxy = BrowserEgressProxy(resolver=resolver)
    proxy_url = await proxy.start()
    pw = browser = None
    response = None
    browser_error = None
    try:
        pw, browser = await launch_browser(proxy_url)
        page = await browser.new_page()
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=10_000)
        except Exception as exc:  # browser-level error is fine; listener is the verdict
            browser_error = exc
            if expect_success:
                raise
    finally:
        if browser:
            await browser.close()
        if pw:
            await pw.stop()
        await proxy.close()
    return proxy, response, browser_error


@pytest.mark.asyncio
async def test_safe_hostname_reaches_safe_server():
    proxy, response, _ = await run_browser_navigation(
        resolver_for("safe"), f"http://safe.test:{SAFE_PORT}/"
    )
    assert response is not None
    connected = [e for e in proxy.connection_events if e["event"] == "connected"]
    assert connected and connected[0]["ip"] == SAFE_IP
    assert _prohibited_connections == []


@pytest.mark.asyncio
async def test_literal_loopback_never_connects():
    proxy, _, _ = await run_browser_navigation(
        resolver_for("safe"), f"http://{PRIVATE_IP}:{PROHIBITED_PORT}/", expect_success=False
    )
    assert any(e["event"] == "rejected" for e in proxy.connection_events)
    assert _prohibited_connections == []


@pytest.mark.asyncio
async def test_hostname_resolving_loopback_never_connects():
    proxy, _, _ = await run_browser_navigation(
        resolver_for("safe"), f"http://private.test:{PROHIBITED_PORT}/", expect_success=False
    )
    assert any(e["event"] == "rejected" for e in proxy.connection_events)
    assert _prohibited_connections == []


@pytest.mark.asyncio
async def test_mixed_public_private_resolution_fails_closed():
    proxy, _, _ = await run_browser_navigation(
        resolver_for("mixed"), f"http://mixed.test:{SAFE_PORT}/", expect_success=False
    )
    assert any(e["event"] == "rejected" for e in proxy.connection_events)
    assert not any(e["event"] == "connected" for e in proxy.connection_events)
    assert _prohibited_connections == []


@pytest.mark.asyncio
async def test_dns_rebinding_second_request_never_connects_private():
    """Decisive test: same browser session, page.reload() after DNS changes."""
    resolver = resolver_for("rebind")
    proxy = BrowserEgressProxy(resolver=resolver)
    proxy_url = await proxy.start()
    try:
        pw, browser = await launch_browser(proxy_url)
        try:
            page = await browser.new_page()
            first = await page.goto(
                f"http://rebind.test:{SAFE_PORT}/", wait_until="domcontentloaded", timeout=10_000
            )
            assert first is not None
            first_events = [e for e in proxy.connection_events if e["event"] == "connected"]
            assert first_events and first_events[0]["ip"] == SAFE_IP

            # DNS now rebinds to loopback. Second resolution via page.reload().
            with contextlib.suppress(Exception):
                await page.reload(wait_until="domcontentloaded", timeout=10_000)
            connected = [e for e in proxy.connection_events if e["event"] == "connected"]
            assert all(e["ip"] != PRIVATE_IP for e in connected)
        finally:
            await browser.close()
            await pw.stop()
    finally:
        await proxy.close()

    # At least 2 real DNS queries happened (real UDP packets).
    assert len(resolver.queries) >= 2
    assert resolver.queries[0]["answer"] == SAFE_IP
    assert resolver.queries[1]["answer"] == PRIVATE_IP
    assert _prohibited_connections == []


@pytest.mark.asyncio
async def test_browser_uses_egress_proxy_for_supported_http_navigation():
    """Prove Chromium target traffic goes through BrowserEgressProxy (no bypass)."""
    for url in [
        f"http://safe.test:{SAFE_PORT}/",
        f"http://localhost:{PROHIBITED_PORT}/",
        f"http://{PRIVATE_IP}:{PROHIBITED_PORT}/",
        f"http://private.test:{PROHIBITED_PORT}/",
    ]:
        proxy, _, _ = await run_browser_navigation(resolver_for("safe"), url, expect_success=False)
        assert len(proxy.connection_events) >= 1, (
            f"no proxy event for {url}: Chromium bypassed the proxy?"
        )
    assert _prohibited_connections == []
