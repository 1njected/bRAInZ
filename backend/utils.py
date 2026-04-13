"""Shared utility functions used across the bRAInZ backend."""

from __future__ import annotations
import hashlib
import ipaddress
import re
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse


def now_iso() -> str:
    """Return current UTC time as an ISO-8601 string (seconds precision, Z suffix)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def slug(text: str, max_len: int = 40) -> str:
    """Convert text to a URL-safe slug, truncated to max_len characters."""
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:max_len]


def content_hash(text: str) -> str:
    """Return a prefixed SHA-256 hex digest of the given text."""
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def validate_url_no_ssrf(url: str, allowed_schemes: tuple[str, ...] = ("http", "https")) -> None:
    """Raise ValueError if url targets a private/internal host or uses a non-allowed scheme.

    Checks:
    - URL scheme must be in allowed_schemes
    - Resolved IP must not be loopback, private, or link-local
    """
    parsed = urlparse(url)
    if parsed.scheme not in allowed_schemes:
        raise ValueError(f"URL scheme '{parsed.scheme}' is not allowed (must be one of: {', '.join(allowed_schemes)})")
    host = parsed.hostname
    if not host:
        raise ValueError("URL has no hostname")
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(host))
    except socket.gaierror as exc:
        raise ValueError(f"Cannot resolve hostname '{host}': {exc}") from exc
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved:
        raise ValueError(f"URL resolves to a private/internal address — not allowed")
