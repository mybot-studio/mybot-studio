"""Outbound-request policy.

Flow `action_http_request` nodes and the proxy tester both fetch operator or
end-user supplied URLs. Without a policy the panel becomes an SSRF proxy into
the docker network / cloud metadata endpoint, so internal targets are refused
unless ALLOW_PRIVATE_URLS is explicitly enabled.
"""

import ipaddress
import logging
import socket
from urllib.parse import urlparse

from app.config import settings

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = ("http", "https")
BLOCKED_HOSTS = {"metadata.google.internal", "metadata", "instance-data"}


class UrlPolicyError(ValueError):
    """Raised when a URL must not be fetched."""


def _ip_is_public(raw: str) -> bool:
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_outbound_url(url: str) -> str:
    """Returns the URL if it is safe to fetch, otherwise raises UrlPolicyError."""
    target = (url or "").strip()
    if not target:
        raise UrlPolicyError("URL is empty")

    parsed = urlparse(target)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UrlPolicyError(f"Scheme '{parsed.scheme or 'none'}' is not allowed (http/https only)")
    if not parsed.hostname:
        raise UrlPolicyError("URL has no host")

    host = parsed.hostname.strip("[]")
    if host.lower() in BLOCKED_HOSTS:
        raise UrlPolicyError(f"Host '{host}' is not allowed")

    if settings.ALLOW_PRIVATE_URLS:
        return target

    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, parsed.port or 80, proto=socket.IPPROTO_TCP)}
    except socket.gaierror as error:
        raise UrlPolicyError(f"Host '{host}' could not be resolved: {error}") from error
    except OSError as error:
        raise UrlPolicyError(f"Host '{host}' could not be resolved: {error}") from error

    if not addresses:
        raise UrlPolicyError(f"Host '{host}' could not be resolved")

    for address in addresses:
        if not _ip_is_public(address):
            raise UrlPolicyError(
                f"Host '{host}' resolves to a non-public address ({address}); "
                "set ALLOW_PRIVATE_URLS=true only if you intend to reach internal services"
            )
    return target


def is_safe_outbound_url(url: str) -> bool:
    try:
        validate_outbound_url(url)
        return True
    except UrlPolicyError:
        return False
