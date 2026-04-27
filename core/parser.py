"""
Parse rendered HTML: extract title, canonical, all links, backlinks to target domains.
"""

import re
import html as _html_module
import logging
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from core.models import BacklinkInfo
from utils.url_utils import get_domain, normalize_domain

logger = logging.getLogger(__name__)


def _matches_target(href: str, targets: set[str]) -> bool:
    link_domain = get_domain(href)
    return any(link_domain == t or link_domain.endswith("." + t) for t in targets)


def _extract_anchor(tag) -> tuple[str, str]:
    """
    Returns (anchor_text, anchor_type).
    Priority: inner text → img alt → title attr.
    Type: "text" if there is visible text, "image" if only img.
    """
    inner_text = tag.get_text(strip=True)
    if inner_text:
        return inner_text, "text"

    img = tag.find("img")
    if img:
        alt = img.get("alt", "").strip()
        return alt or "", "image"

    title = tag.get("title", "").strip()
    return title, "text"


def _get_rel_type(tag, page_nofollow: bool) -> str:
    """
    Determine rel type for a single <a> tag.
    If page-level robots says nofollow → all links are nofollow.
    """
    if page_nofollow:
        return "nofollow"
    rel_values = set(tag.get("rel") or [])
    for val in ("sponsored", "ugc", "nofollow"):
        if val in rel_values:
            return val
    return "dofollow"


def _extract_context(tag, raw_html: str, window: int = 200,
                     search_from: int = 0) -> tuple[str, int]:
    """
    Extract ±window chars of raw HTML around the link tag.
    Searches by href attribute value rather than BS4 tag serialization —
    BS4/lxml may reorder attributes so str(tag) often mismatches the source.
    Returns (context_html, next_search_pos).
    """
    href = str(tag.get("href", "")).strip()
    idx = -1

    if href:
        escaped = _html_module.escape(href, quote=True)
        # Try decoded href first; also try HTML-escaped form (e.g. & → &amp;)
        variants = [href] if href == escaped else [href, escaped]

        for val in variants:
            for pattern in (f'href="{val}"', f"href='{val}'"):
                pos = raw_html.find(pattern, search_from)
                if pos != -1:
                    idx = pos
                    break
            if idx != -1:
                break

        # Fallback: search from beginning (handles the case where search_from
        # already passed this occurrence due to earlier identical hrefs)
        if idx == -1:
            for val in variants:
                for pattern in (f'href="{val}"', f"href='{val}'"):
                    pos = raw_html.find(pattern)
                    if pos != -1:
                        idx = pos
                        break
                if idx != -1:
                    break

    if idx == -1:
        return str(tag)[:500], search_from

    start = max(0, idx - window)
    end = min(len(raw_html), idx + len(href) + window)
    return raw_html[start:end], idx + 1


def parse_page(html: str, page_url: str, target_domains: list[str]) -> dict:
    """
    Parse rendered HTML and return a dict with:
      title, canonical, internal_links, external_links,
      page_nofollow (bool), backlinks (list[BacklinkInfo])
    """
    soup = BeautifulSoup(html, "lxml")
    targets = {normalize_domain(d) for d in target_domains}
    page_host = get_domain(page_url)

    # Title
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # Canonical
    canonical_tag = soup.find("link", rel="canonical")
    canonical_href = canonical_tag.get("href") if canonical_tag else None
    canonical_url = str(canonical_href).strip() if canonical_href else None

    # Check page-level nofollow (meta robots)
    page_nofollow = False
    for meta in soup.find_all("meta", attrs={"name": re.compile(r"^robots$", re.I)}):
        content = str(meta.get("content") or "").lower()
        if "nofollow" in content:
            page_nofollow = True
            break

    # Count internal / external links + collect backlinks
    internal_links = 0
    external_links = 0
    backlinks: list[BacklinkInfo] = []
    context_pos = 0   # tracks search offset so duplicate tags get their own context

    for tag in soup.find_all("a", href=True):
        href = str(tag["href"]).strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        # Resolve relative URLs
        absolute_href = urljoin(page_url, href)
        link_host = get_domain(absolute_href)

        if link_host == page_host:
            internal_links += 1
        else:
            external_links += 1

        if _matches_target(absolute_href, targets):
            anchor_text, anchor_type = _extract_anchor(tag)
            rel_type = _get_rel_type(tag, page_nofollow)
            context, context_pos = _extract_context(tag, html, search_from=context_pos)

            backlinks.append(BacklinkInfo(
                target_url=absolute_href,
                anchor_text=anchor_text,
                anchor_type=anchor_type,
                rel_type=rel_type,
                context_html=context,
            ))

    return {
        "title": title,
        "canonical_url": canonical_url,
        "internal_links": internal_links,
        "external_links": external_links,
        "page_nofollow": page_nofollow,
        "backlinks": backlinks,
        "soup": soup,
    }
