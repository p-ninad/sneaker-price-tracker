"""Utilities for parsing product URLs into platform and product identifiers."""

import re
from urllib.parse import urlparse
from typing import Optional


PLATFORM_URL_HINTS = {
    "myntra": ("myntra.com",),
    "ajio": ("ajio.com",),
    "vegnonveg": ("vegnonveg.com", "vegnonveg.in"),
    "superkicks": ("superkicks.in", "superkicks.com"),
}


def extract_platform_from_url(url: str) -> Optional[str]:
    """Identify the platform from a product URL."""
    if not url:
        return None

    parsed = urlparse(url)
    hostname = parsed.netloc.lower()

    for platform, hints in PLATFORM_URL_HINTS.items():
        if any(hint in hostname for hint in hints):
            return platform

    return None


def extract_product_id_from_url(url: str) -> Optional[str]:
    """Extract a product identifier from a URL path."""
    if not url:
        return None

    parsed = urlparse(url)
    hostname = parsed.netloc.lower()
    path = parsed.path.strip("/")

    if not path:
        return None

    parts = [part for part in path.split("/") if part]
    if not parts:
        return None

    if "myntra.com" in hostname:
        numeric_parts = [part for part in parts if re.fullmatch(r"\d+", part)]
        if numeric_parts:
            return numeric_parts[-1]
        if parts[-1].lower() == "buy" and len(parts) >= 2:
            return parts[-2]

    return parts[-1]
