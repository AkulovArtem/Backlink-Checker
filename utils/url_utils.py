"""Shared URL/domain normalisation helpers used by parser, report, and export."""

import re
from urllib.parse import unquote, urlparse, urlsplit

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


def decode_donor_file(data: bytes) -> str:
    """Decode an uploaded .txt list: UTF-8 (with or without BOM), UTF-16 with BOM
    (Notepad "Unicode", Excel "Unicode text"), otherwise Windows-1251."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1251", errors="replace")


def _bare_host(url: str) -> str:
    """Hostname without port, userinfo, trailing dot or leading www."""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return ""
    host = host.rstrip(".").removeprefix("www.")
    try:
        # One form for IDN hosts: "пример.рф" and "xn--e1afmkfd.xn--p1ai" must match.
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return host


def get_domain(url: str) -> str:
    """Extract bare domain (no www., no scheme) from a full URL."""
    return _bare_host(url)


def normalize_domain(domain: str) -> str:
    """Bare host from a domain or URL (no scheme, www, path, or query)."""
    raw = (domain or "").strip().lower()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "http://" + raw
    return _bare_host(raw)


def matches_target(href: str, target: str) -> bool:
    """Return True if href's domain equals target or is a subdomain of it."""
    link_domain = get_domain(href)
    return link_domain == target or link_domain.endswith("." + target)


def _page_key(url: str) -> tuple | None:
    try:
        parts = urlsplit((url or "").strip())
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        return None
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        pass
    return (
        parts.scheme.lower(), host, port,
        unquote(parts.path) or "/", unquote(parts.query),
    )


def same_page(a: str, b: str) -> bool:
    """True if two URLs differ only the way a browser rewrites them: "/" added
    to a bare host, percent-encoding, punycode, letter case of scheme/host,
    the #fragment. Scheme, www, path and query changes are real redirects."""
    key_a = _page_key(a)
    return key_a is not None and key_a == _page_key(b)
