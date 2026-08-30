"""Shared URL/domain normalisation helpers used by parser, report, and export."""

import re
from urllib.parse import urlparse

URL_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)
MAX_DONORS = 100_000
MAX_TARGETS = 50


def parse_donor_lines(text: str) -> tuple[list[str], int]:
    """Split pasted donor text into unique http(s) URLs.

    Returns (valid_urls, invalid_count). Invalid lines are those without
    an http/https scheme. Order of first occurrence is preserved.
    The caller applies MAX_DONORS / remaining-slot caps so it can warn.
    """
    raw = [u.strip() for u in text.splitlines() if u.strip()]
    invalid_count = sum(1 for u in raw if not URL_SCHEME_RE.match(u))
    valid = list(dict.fromkeys(u for u in raw if URL_SCHEME_RE.match(u)))
    return valid, invalid_count


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
