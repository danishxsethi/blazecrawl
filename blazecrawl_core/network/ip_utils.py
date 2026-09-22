"""Private/reserved IP classification.

Derived from BlazeCrawl's network-blocking primitives, with the same denylist
semantics. Handles IPv4, IPv6, IPv4-mapped
IPv6 (``::ffff:127.0.0.1``) and legacy IPv4 textual forms (``127.1``,
``2130706433``, ``0x7f.0.0.1``).
"""

from __future__ import annotations

import ipaddress
import socket

PRIVATE_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),  # "This" network (RFC 1122)
    ipaddress.ip_network("127.0.0.0/8"),  # Loopback
    ipaddress.ip_network("10.0.0.0/8"),  # Private Class A
    ipaddress.ip_network("172.16.0.0/12"),  # Private Class B
    ipaddress.ip_network("192.168.0.0/16"),  # Private Class C
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local (cloud metadata)
    ipaddress.ip_network("100.64.0.0/10"),  # Shared address space (RFC 6598)
    ipaddress.ip_network("192.0.0.0/24"),  # IETF protocol assignments (RFC 6890)
    ipaddress.ip_network("192.0.2.0/24"),  # TEST-NET-1 (RFC 5737)
    ipaddress.ip_network("198.18.0.0/15"),  # Benchmarking (RFC 2544)
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2 (RFC 5737)
    ipaddress.ip_network("203.0.113.0/24"),  # TEST-NET-3 (RFC 5737)
    ipaddress.ip_network("224.0.0.0/4"),  # Multicast
    ipaddress.ip_network("240.0.0.0/4"),  # Reserved
    ipaddress.ip_network("255.255.255.255/32"),  # Limited broadcast
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("::/128"),  # IPv6 unspecified
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local (incl. ULA metadata)
    ipaddress.ip_network("fc00::/7"),  # IPv6 ULA (RFC 4193)
    ipaddress.ip_network("2001:db8::/32"),  # IPv6 documentation (RFC 3849)
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped IPv6
    ipaddress.ip_network("64:ff9b::/96"),  # NAT64 well-known prefix
]


def parse_ip_literal(ip_str: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse strict and legacy textual IP forms into an ipaddress object."""
    try:
        return ipaddress.ip_address(ip_str)
    except ValueError:
        try:
            return ipaddress.IPv4Address(socket.inet_aton(ip_str))
        except OSError:
            return None


def is_blocked_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True when an IP falls into any blocked private/reserved range."""
    if hasattr(ip, "ipv4_mapped") and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    for network in PRIVATE_NETWORKS:
        try:
            if ip in network:
                return True
        except TypeError:
            continue
    return False


def is_private_ip(ip_str: str) -> bool:
    """Check if an IP string (or hostname) resolves into a blocked range."""
    if not ip_str:
        return False

    ip = parse_ip_literal(ip_str)
    if ip is not None:
        return is_blocked_address(ip)

    try:
        addr_infos = socket.getaddrinfo(ip_str, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False

    for _family, _socktype, _proto, _canonname, sockaddr in addr_infos:
        resolved_ip = parse_ip_literal(sockaddr[0])
        if resolved_ip is not None and is_blocked_address(resolved_ip):
            return True

    return False
