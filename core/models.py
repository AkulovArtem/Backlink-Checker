from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BacklinkInfo:
    target_url: str
    anchor_text: str
    anchor_type: str        # "text" | "image"
    rel_type: str           # "dofollow" | "nofollow" | "ugc" | "sponsored"
    context_html: str       # HTML fragment ±200 chars around the link


@dataclass
class IndexabilityResult:
    # None = page was never successfully loaded; "open"/"closed" = actual result
    google: Optional[str] = None
    yandex: Optional[str] = None
    bing: Optional[str]   = None
    baidu: Optional[str]  = None
    meta_robots: str = ""
    x_robots_tag: str = ""


@dataclass
class DonorResult:
    donor_id: int
    url: str
    http_status: Optional[int] = None
    title: str = ""
    canonical_url: Optional[str] = None
    internal_links: int = 0
    external_links: int = 0
    indexability: IndexabilityResult = field(default_factory=IndexabilityResult)
    backlinks: list[BacklinkInfo] = field(default_factory=list)
    status: str = "pending"   # pending | found | not_found | not_loaded
    error_code: Optional[str] = None


@dataclass
class CheckConfig:
    task_id: int
    donor_urls: list[tuple[int, str]]
    target_domains: list[str]
    user_agent_preset: str = "desktop_chrome"   # desktop_chrome | mobile_chrome | mobile_safari | custom
    custom_user_agent: str = ""
    threads: int = 5
    timeout: int = 30   # seconds


@dataclass
class Task:
    id: int
    name: str
    created_at: str
    status: str           # pending | running | completed | error
    progress: int         # 0-100
    user_agent: str
    custom_user_agent: Optional[str]
    threads: int
    timeout: int
    target_domains: list[str]
    donor_count: int = 0
    backlink_count: int = 0
