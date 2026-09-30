"""Shared stdlib HTTP boundary for outbound Gateway and MCP requests.

Ambient proxy variables and automatic redirects can silently change the
recipient of a request carrying memory text or credentials. Callers that need
a proxy must introduce an explicit, reviewed configuration instead.
"""

from __future__ import annotations

import ipaddress
import os
import urllib.parse
import urllib.request
from typing import Any

if __package__:
    from .network_policy import remote_egress_enabled
else:
    from network_policy import remote_egress_enabled

EGRESS_ALLOWLIST_ENV = "MEMORY_GATEWAY_EGRESS_ALLOWLIST"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _url_origin(url: str) -> tuple[str, bool, str]:
    """Return a canonical origin, whether it is loopback, and the scheme."""
    try:
        parsed = urllib.parse.urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        raise ValueError("outbound_destination_denied") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or any(character.isspace() or ord(character) < 32 for character in url)
    ):
        raise ValueError("outbound_destination_denied")

    hostname = hostname.rstrip(".").lower()
    try:
        normalized_host = hostname.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValueError("outbound_destination_denied") from None
    try:
        loopback = ipaddress.ip_address(normalized_host).is_loopback
    except ValueError:
        loopback = normalized_host == "localhost"

    default_port = 443 if parsed.scheme == "https" else 80
    port_part = f":{port}" if port is not None and port != default_port else ""
    if ":" in normalized_host:
        authority = f"[{normalized_host}]{port_part}"
    else:
        authority = f"{normalized_host}{port_part}"
    return f"{parsed.scheme}://{authority}", loopback, parsed.scheme


def _configured_egress_origins() -> set[str]:
    raw_allowlist = os.getenv(EGRESS_ALLOWLIST_ENV, "")
    origins: set[str] = set()
    for entry in raw_allowlist.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            origin, loopback, scheme = _url_origin(entry)
        except ValueError:
            raise ValueError("outbound_allowlist_invalid") from None
        parsed = urllib.parse.urlsplit(entry)
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("outbound_allowlist_invalid")
        if scheme == "http" and not loopback:
            raise ValueError("outbound_allowlist_invalid")
        origins.add(origin)
    return origins


def assert_outbound_url_allowed(url: str) -> None:
    """Require explicit remote-egress opt-in and an exact HTTPS origin allowlist.

    Loopback remains available for the desktop/local topology. Its process identity
    is outside this URL-level check and must be protected by the local OS boundary.
    """
    origin, loopback, scheme = _url_origin(url)
    if loopback:
        return
    if not remote_egress_enabled() or scheme != "https" or origin not in _configured_egress_origins():
        raise ValueError("outbound_destination_denied")


async def assert_async_request_allowed(request: Any) -> None:
    """HTTPX async request hook used by optional SDKs that bypass urllib."""
    assert_outbound_url_allowed(str(request.url))


def create_restricted_async_openai_client(*, api_key: str, base_url: str, transport: Any = None) -> Any:
    """Build an OpenAI SDK client guarded by the shared destination policy.

    ``transport`` is injectable for synthetic tests. Production callers should
    leave it unset so HTTPX uses its normal network transport.
    """
    assert_outbound_url_allowed(base_url)
    if urllib.parse.urlsplit(base_url).query:
        raise ValueError("outbound_destination_denied")
    try:
        from openai import AsyncOpenAI, DefaultAsyncHttpxClient
    except ImportError as exc:
        raise RuntimeError("restricted_openai_client_dependency_missing") from exc

    http_client = DefaultAsyncHttpxClient(
        trust_env=False,
        follow_redirects=False,
        event_hooks={"request": [assert_async_request_allowed]},
        transport=transport,
    )
    return AsyncOpenAI(api_key=api_key, base_url=base_url, http_client=http_client)


def urlopen_no_proxy_redirects(request: Any, timeout: float | None = None):
    """Open an approved request without ambient proxies or automatic redirects."""
    url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
    assert_outbound_url_allowed(url)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirectHandler(),
    )
    return opener.open(request, timeout=timeout)
