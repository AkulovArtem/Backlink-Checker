"""Shared URL/domain normalisation helpers used by parser, report, and export."""

import re
from urllib.parse import urlparse


def get_domain(url: str) -> str:
    """Extract bare domain (no www., no scheme) from a full URL."""
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def normalize_domain(domain: str) -> str:
    """Strip scheme, www., and trailing slash from a raw domain or URL string."""
    domain = domain.lower().strip()
    domain = re.sub(r"^https?://", "", domain)
    return domain.removeprefix("www.").rstrip("/")


def matches_target(href: str, target: str) -> bool:
    """Return True if href's domain equals target or is a subdomain of it."""
    link_domain = get_domain(href)
    return link_domain == target or link_domain.endswith("." + target)
