"""Controlled browser egress proxy.

Chromium is configured with this proxy and an empty bypass list.  Every HTTP
origin connection and HTTPS CONNECT is resolved by this process, checked against
the SSRF policy, and opened to the selected validated IP.  The target hostname
remains in the HTTP authority / CONNECT request, so Chromium retains TLS SNI and
certificate verification semantics.
"""

from __future__ import annotations

import asyncio
import socket
from typing import Any
from urllib.parse import urlsplit

from blazecrawl_core.network.ip_utils import is_blocked_address, parse_ip_literal
from blazecrawl_core.network.resolver import Resolver, SystemResolver
from blazecrawl_core.network.ssrf import SSRFValidationError

_MAX_HEADER = 64 * 1024
_MAX_LINE = 8192
_CONNECT_TIMEOUT = 10.0
_IDLE_TIMEOUT = 60.0


class BrowserEgressProxy:
    def __init__(
        self,
        *,
        max_connections: int = 128,
        resolver: Resolver | None = None,
    ) -> None:
        self._server: asyncio.AbstractServer | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._slots = asyncio.Semaphore(max_connections)
        self._resolver = resolver or SystemResolver()
        self.port = 0
        self.connection_events: list[dict[str, Any]] = []

    async def start(self) -> str:
        self._server = await asyncio.start_server(self._accept, "127.0.0.1", 0)
        assert self._server.sockets
        self.port = int(self._server.sockets[0].getsockname()[1])
        return f"http://127.0.0.1:{self.port}"

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.create_task(self._handle(reader, writer))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @staticmethod
    def _authority(value: str, *, default_port: int | None = None) -> tuple[str, int]:
        if any(ch in value for ch in ("@", "\\", "\r", "\n")):
            raise SSRFValidationError("Invalid proxy authority")
        parsed = urlsplit(f"//{value}")
        if parsed.username or parsed.password or not parsed.hostname:
            raise SSRFValidationError("Invalid proxy authority")
        try:
            port = parsed.port if parsed.port is not None else default_port
        except ValueError as exc:
            raise SSRFValidationError("Invalid proxy port") from exc
        if port is None or not 1 <= port <= 65535:
            raise SSRFValidationError("Invalid proxy port")
        return parsed.hostname, port

    async def _validated_socket(
        self, host: str, port: int
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        literal = parse_ip_literal(host)
        raw_ips = [str(literal)] if literal else await self._resolver.resolve(host, port)
        ips = [ip for ip in (parse_ip_literal(s) for s in raw_ips) if ip is not None]
        if not ips or any(is_blocked_address(ip) for ip in ips):
            self.connection_events.append(
                {
                    "event": "rejected",
                    "host": host,
                    "port": port,
                    "resolved": raw_ips,
                }
            )
            raise SSRFValidationError("Browser proxy rejected prohibited address")
        last: Exception | None = None
        for ip in ips:
            sock = socket.socket(
                socket.AF_INET6 if ip.version == 6 else socket.AF_INET, socket.SOCK_STREAM
            )
            sock.setblocking(False)
            address = (str(ip), port, 0, 0) if ip.version == 6 else (str(ip), port)
            try:
                await asyncio.wait_for(
                    asyncio.get_running_loop().sock_connect(sock, address),
                    _CONNECT_TIMEOUT,
                )
                self.connection_events.append(
                    {"event": "connected", "host": host, "port": port, "ip": str(ip)}
                )
                return await asyncio.open_connection(sock=sock)
            except (TimeoutError, OSError) as exc:
                last = exc
                sock.close()
        raise OSError("validated browser destination could not be reached") from last

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        upstream: tuple[asyncio.StreamReader, asyncio.StreamWriter] | None = None
        try:
            async with self._slots:
                header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), _CONNECT_TIMEOUT)
                if len(header) > _MAX_HEADER:
                    raise SSRFValidationError("Proxy headers too large")
                lines = header.decode("latin-1").split("\r\n")
                if not lines or len(lines[0]) > _MAX_LINE:
                    raise SSRFValidationError("Proxy request line too large")
                parts = lines[0].split(" ")
                if len(parts) != 3 or parts[2] not in {"HTTP/1.0", "HTTP/1.1"}:
                    raise SSRFValidationError("Malformed proxy request")
                method, target, _version = parts
                method = method.upper()
                if method == "CONNECT":
                    host, port = self._authority(target)
                elif method in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
                    parsed = urlsplit(target)
                    if parsed.scheme.lower() != "http" or not parsed.netloc:
                        raise SSRFValidationError("Proxy requires an absolute HTTP URL")
                    host, port = self._authority(parsed.netloc, default_port=80)
                else:
                    raise SSRFValidationError("Unsupported proxy method")
                upstream = await self._validated_socket(host, port)
                upstream_reader, upstream_writer = upstream
                if method == "CONNECT":
                    writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    await writer.drain()
                else:
                    parsed = urlsplit(target)
                    origin = parsed.path or "/"
                    if parsed.query:
                        origin += "?" + parsed.query
                    rewritten = (
                        f"{method} {origin} HTTP/1.1\r\n" + "\r\n".join(lines[1:]) + "\r\n\r\n"
                    )
                    upstream_writer.write(rewritten.encode("latin-1"))
                    await upstream_writer.drain()
                await self._tunnel(reader, writer, upstream_reader, upstream_writer)
        except asyncio.CancelledError:
            raise
        except Exception:
            if not writer.is_closing():
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
                await writer.drain()
        finally:
            if upstream is not None:
                upstream[1].close()
                await upstream[1].wait_closed()
            writer.close()
            await writer.wait_closed()

    async def _tunnel(self, client_reader, client_writer, upstream_reader, upstream_writer) -> None:
        async def copy(source, destination):
            try:
                while True:
                    data = await asyncio.wait_for(source.read(65536), _IDLE_TIMEOUT)
                    if not data:
                        break
                    destination.write(data)
                    await destination.drain()
            finally:
                if not destination.is_closing():
                    destination.close()

        await asyncio.gather(
            copy(client_reader, upstream_writer), copy(upstream_reader, client_writer)
        )
