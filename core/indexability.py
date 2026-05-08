"""
Check page indexability via:
  - <meta name="robots"> / <meta name="googlebot"> etc.
  - X-Robots-Tag HTTP header
"""

from bs4 import BeautifulSoup

from core.models import IndexabilityResult

# Mapping from bot name used in meta/header to our field
BOT_NAMES = {
    "google": ["robots", "googlebot"],
    "yandex": ["robots", "yandexbot"],
    "bing":   ["robots", "bingbot"],
    "baidu":  ["robots", "baiduspider"],
}


def _parse_directives(content: str) -> set[str]:
    """Parse comma-separated robots directives into a lowercase set."""
    return {d.strip().lower() for d in content.split(",")}


def _is_noindex(directives: set[str]) -> bool:
    return "noindex" in directives


def check_indexability(soup: BeautifulSoup, response_headers: dict) -> IndexabilityResult:
    result = IndexabilityResult()

    # ── Meta robots ────────────────────────────────────────────────────────
    meta_values: dict[str, set[str]] = {}
    for tag in soup.find_all("meta"):
        name = str(tag.get("name") or "").lower()
        content = str(tag.get("content") or "")
        if name in {"robots", "googlebot", "yandexbot", "bingbot", "baiduspider"}:
            meta_values[name] = _parse_directives(content)

    all_meta_parts = []
    for name, directives in meta_values.items():
        all_meta_parts.append(f"{name}: {', '.join(sorted(directives))}")
    result.meta_robots = "; ".join(all_meta_parts)

    # ── X-Robots-Tag header ────────────────────────────────────────────────
    x_robots_raw = ""
    for hdr_key, hdr_val in response_headers.items():
        if hdr_key.lower() == "x-robots-tag":
            x_robots_raw = hdr_val
            break
    result.x_robots_tag = x_robots_raw

    x_robots_directives: dict[str, set[str]] = {}
    if x_robots_raw:
        # X-Robots-Tag can be: "noindex" or "googlebot: noindex" or mixed
        # e.g. "noindex, noarchive" — multiple parts share the same "robots" key,
        # so we must merge (update) rather than overwrite.
        for part in x_robots_raw.split(","):
            part = part.strip()
            if ":" in part:
                bot, _, directive = part.partition(":")
                key = bot.strip().lower()
                x_robots_directives.setdefault(key, set()).update(_parse_directives(directive))
            else:
                x_robots_directives.setdefault("robots", set()).update(_parse_directives(part))

    # ── Determine indexability per bot ────────────────────────────────────
    def _bot_is_closed(bot_key: str) -> bool:
        for meta_name in BOT_NAMES[bot_key]:
            if meta_name in meta_values and _is_noindex(meta_values[meta_name]):
                return True
        for header_bot in BOT_NAMES[bot_key]:
            if header_bot in x_robots_directives and _is_noindex(x_robots_directives[header_bot]):
                return True
        return False

    result.google = "closed" if _bot_is_closed("google") else "open"
    result.yandex = "closed" if _bot_is_closed("yandex") else "open"
    result.bing   = "closed" if _bot_is_closed("bing")   else "open"
    result.baidu  = "closed" if _bot_is_closed("baidu")  else "open"

    return result
