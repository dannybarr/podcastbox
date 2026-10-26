"""Refuse cloud model endpoints.

Inference hosts must be loopback, a private IP, or a single-label Docker
DNS name. IMAP is not checked here: that connection is the user's own
mail server.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


class ExternalServiceError(ValueError):
    """Raised when a model URL points at a public host."""


def assert_private_base_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").strip().lower()
    if parsed.scheme not in {"http", "https"} or not host:
        raise ExternalServiceError(f"Refusing model URL {url!r}.")
    if host in {"localhost", "host.docker.internal"} or "." not in host:
        return url.rstrip("/")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ExternalServiceError(
            f"Refusing non-local model host {host!r}. PodcastBox does not call cloud APIs."
        ) from exc
    if ip.is_loopback or ip.is_private:
        return url.rstrip("/")
    raise ExternalServiceError(
        f"Refusing non-local model host {host!r}. PodcastBox does not call cloud APIs."
    )
