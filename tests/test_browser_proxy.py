import pytest

from blazecrawl_core.network.browser_proxy import BrowserEgressProxy
from blazecrawl_core.network.ssrf import SSRFValidationError


@pytest.mark.parametrize(
    "authority",
    [
        "user:pass@example.com:443",
        "example.com:0",
        "example.com:65536",
        "example.com:notaport",
        "example.com\\:443",
        "example.com\r\nX: y",
    ],
)
def test_proxy_rejects_ambiguous_authorities(authority):
    with pytest.raises(SSRFValidationError):
        BrowserEgressProxy._authority(authority)


@pytest.mark.parametrize(
    ("authority", "default", "expected"),
    [
        ("example.com:443", None, ("example.com", 443)),
        ("example.com", 80, ("example.com", 80)),
        ("[::1]:443", None, ("::1", 443)),
    ],
)
def test_proxy_parses_authority(authority, default, expected):
    assert BrowserEgressProxy._authority(authority, default_port=default) == expected


def test_proxy_rejects_missing_explicit_port_for_connect():
    with pytest.raises(SSRFValidationError):
        BrowserEgressProxy._authority("example.com")
