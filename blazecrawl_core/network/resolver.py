"""Resolver abstraction for BlazeCrawl egress.

Production uses :class:`SystemResolver` (getaddrinfo). Tests inject a
controlled resolver that returns programmed answers. Both flow through
the same validation and numeric-IP socket-connect logic in
``BrowserEgressProxy``.
"""

from __future__ import annotations

import asyncio
import socket
from typing import Protocol


class Resolver(Protocol):
    async def resolve(self, host: str, port: int) -> list[str]: ...


class SystemResolver:
    """Production resolver backed by the OS (getaddrinfo)."""

    async def resolve(self, host: str, port: int) -> list[str]:
        try:
            infos = await asyncio.get_running_loop().run_in_executor(
                None, lambda: socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
            )
        except socket.gaierror as exc:
            from blazecrawl_core.network.ssrf import SSRFValidationError

            raise SSRFValidationError("Hostname resolution failed") from exc
        ips: list[str] = []
        for _fam, _type, _proto, _canon, sockaddr in infos:
            ip = sockaddr[0]
            if ip not in ips:
                ips.append(ip)
        return ips


class UdpResolver:
    """Resolver that queries a real UDP DNS server (for tests).

    Uses a real asyncio datagram endpoint; no loop-private socket calls.
    """

    def __init__(self, dns_host: str, dns_port: int) -> None:
        self.dns_host = dns_host
        self.dns_port = dns_port
        self.queries: list[dict[str, str | int]] = []

    async def resolve(self, host: str, port: int) -> list[str]:
        import socket as _socket

        labels = b"".join(bytes([len(p)]) + p.encode() for p in host.split(".")) + b"\x00"
        pkt = b"\xbe\xef\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00" + labels + b"\x00\x01\x00\x01"
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[list[str]] = loop.create_future()

        class _Client(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                transport.sendto(pkt)
                self._t = transport

            def datagram_received(self, data, addr):
                if not fut.done():
                    fut.set_result([_socket.inet_ntoa(data[-4:])])
                self._t.close()

            def error_received(self, exc):
                if not fut.done():
                    fut.set_exception(exc)
                self._t.close()

        transport, _ = await loop.create_datagram_endpoint(
            _Client, remote_addr=(self.dns_host, self.dns_port)
        )
        try:
            answer = await asyncio.wait_for(fut, 2)
        finally:
            transport.close()
        self.queries.append({"host": host, "answer": answer[0]})
        return answer


async def resolve_host(host: str, port: int) -> list[str]:
    return await SystemResolver().resolve(host, port)
