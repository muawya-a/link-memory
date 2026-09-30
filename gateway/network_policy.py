"""Fail-closed policy for non-HTTP database egress and internal listeners."""

from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlsplit


NEO4J_ALLOWLIST_ENV = "MEMORY_GATEWAY_NEO4J_ALLOWLIST"
REMOTE_EGRESS_ENABLED_ENV = "MEMORY_GATEWAY_REMOTE_EGRESS_ENABLED"
_NEO4J_SCHEMES = {"bolt", "bolt+s"}
# Routing schemes can discover additional advertised hosts. Until a resolver
# enforces the allowlist on every discovered address, remote routing is denied.
_NEO4J_REMOTE_TLS_SCHEMES = {"bolt+s"}


def remote_egress_enabled() -> bool:
    """Require explicit process opt-in before any non-loopback data egress."""
    return os.getenv(REMOTE_EGRESS_ENABLED_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _neo4j_origin(value: str) -> tuple[str, str, int]:
    if not isinstance(value, str) or not value or value != value.strip() or any(ord(ch) < 32 for ch in value):
        raise ValueError("neo4j_destination_denied")
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("neo4j_destination_denied") from exc
    if (
        scheme not in _NEO4J_SCHEMES
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.fragment
        or parsed.query
    ):
        raise ValueError("neo4j_destination_denied")
    try:
        canonical_host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("neo4j_destination_denied") from exc
    if port is None:
        port = 7687
    if not 1 <= port <= 65535:
        raise ValueError("neo4j_destination_denied")
    return scheme, canonical_host, port


def _is_localhost(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _neo4j_allowlist() -> set[tuple[str, str, int]]:
    raw_value = os.getenv(NEO4J_ALLOWLIST_ENV, "")
    entries: set[tuple[str, str, int]] = set()
    for raw_entry in raw_value.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue
        try:
            parsed = urlsplit(entry)
            origin = _neo4j_origin(entry)
        except ValueError as exc:
            raise ValueError("neo4j_allowlist_invalid") from exc
        if parsed.query or parsed.fragment or origin[0] not in _NEO4J_REMOTE_TLS_SCHEMES or _is_localhost(origin[1]):
            raise ValueError("neo4j_allowlist_invalid")
        entries.add(origin)
    return entries


def assert_neo4j_uri_allowed(uri: str) -> str:
    """Allow loopback database URIs or an exact, TLS-verified remote origin."""
    scheme, host, port = _neo4j_origin(uri)
    if _is_localhost(host):
        return uri
    if not remote_egress_enabled():
        raise ValueError("neo4j_destination_denied")
    if scheme not in _NEO4J_REMOTE_TLS_SCHEMES:
        raise ValueError("neo4j_destination_denied")
    if (scheme, host, port) not in _neo4j_allowlist():
        raise ValueError("neo4j_destination_denied")
    return uri


def assert_loopback_bind_host(host: str) -> str:
    """Keep unauthenticated in-process sidecars off externally reachable interfaces."""
    if not isinstance(host, str) or not host or host != host.strip():
        raise ValueError("internal_listener_must_be_loopback")
    normalized = host.strip("[]").lower()
    if normalized == "localhost":
        return host
    try:
        if ipaddress.ip_address(normalized).is_loopback:
            return host
    except ValueError:
        pass
    raise ValueError("internal_listener_must_be_loopback")


def assert_gateway_bind_host(host: str) -> str:
    """Require an IPv4 loopback literal supported by ThreadingHTTPServer."""
    if not isinstance(host, str) or not host or host != host.strip():
        raise ValueError("gateway_listener_must_be_ipv4_loopback")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise ValueError("gateway_listener_must_be_ipv4_loopback") from None
    if address.version != 4 or not address.is_loopback:
        raise ValueError("gateway_listener_must_be_ipv4_loopback")
    return host


def safe_internal_http_log(service: str, args: tuple[object, ...]) -> str:
    """Keep status visibility while omitting caller-controlled request targets."""
    status: int | None = None
    if len(args) > 1:
        try:
            candidate = int(args[1])
            if 100 <= candidate <= 599:
                status = candidate
        except (TypeError, ValueError):
            pass
    return f"{service} HTTP status={status}" if status is not None else f"{service} HTTP request"
