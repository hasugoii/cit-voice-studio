"""Explicit deployment metadata; never trust request headers for public URLs."""
import os
import re
from urllib.parse import urlsplit


def is_selfhost() -> bool:
    return os.environ.get("CIT_DEPLOYMENT_MODE", "desktop") == "selfhost"


def public_url() -> str | None:
    if not is_selfhost():
        return None
    value = os.environ.get("CIT_PUBLIC_URL", "").rstrip("/")
    parts = urlsplit(value)
    if (parts.scheme != "https" or not parts.hostname or parts.username or
            parts.password or parts.path or parts.query or parts.fragment):
        raise ValueError("Self-host requires CIT_PUBLIC_URL as an HTTPS origin")
    parts.port  # Also validate malformed/out-of-range ports.
    return value


def api_prefix() -> str:
    prefix = os.environ.get("CIT_PUBLIC_API_PREFIX", "/public-api")
    if not re.fullmatch(r"/[a-zA-Z0-9_-]+", prefix):
        raise ValueError("CIT_PUBLIC_API_PREFIX must be one URL path segment")
    return prefix


def info() -> dict:
    origin = public_url()
    return {
        "mode": "selfhost" if is_selfhost() else "desktop",
        "public_url": origin,
        "public_api_url": origin + api_prefix() if origin else None,
        "port_managed": is_selfhost(),
        "restart_required": False if is_selfhost() else None,
    }
