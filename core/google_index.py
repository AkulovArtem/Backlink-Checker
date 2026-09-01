"""Google index check via XMLRiver (inindex) or XMLStock (site: query)."""

from __future__ import annotations

import json
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

PROVIDER_RIVER = "xmlriver"
PROVIDER_STOCK = "xmlstock"
PROVIDER_JSONSEO = "jsonseo"

XMLRIVER_BALANCE_PATH = "https://xmlriver.com/api/get_balance/"
XMLSTOCK_BALANCE_PATH = "https://xmlstock.com/api/"
JSONSEO_BALANCE_PATH = "https://jsonseo.ru/api/balance"
JSONSEO_SEARCH_PATH = "https://jsonseo.ru/api/google/xml"

INDEX_CONCURRENCY = 10
HTTP_TIMEOUT = 45
MAX_QUERY_LEN = 1400
INDEX_RETRIES = 3
RETRYABLE_ERROR_CODES = frozenset({"20", "55", "101", "110", "202", "500"})
TRANSIENT_ERROR_MARKERS = ("временно недоступен", "повторите", "try again")
NON_RETRYABLE_HTTP = frozenset({401, 402, 403, 404, 422})


@dataclass
class IndexCheckResult:
    status: str  # indexed | not_indexed | error
    error: str = ""
    retryable: bool = False


@dataclass
class BalanceResult:
    ok: bool
    amount: float | None = None
    error: str = ""

    @property
    def is_usable(self) -> bool:
        return self.ok and self.amount is not None and self.amount > 0


@dataclass
class IndexProvider:
    name: str
    endpoint: str
    balance: float = 0.0


def parse_user_key(api_url: str) -> tuple[str, str] | None:
    """Extract (user, key) from a personal API URL."""
    raw = (api_url or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "http://placeholder/?" + raw.lstrip("?")
    query = dict(parse_qsl(urlparse(raw).query, keep_blank_values=True))
    user = (query.get("user") or "").strip()
    key = (query.get("key") or "").strip()
    if user and key:
        return user, key
    return None


def extract_api_key(value: str) -> str:
    """Raw API key, or ``key=`` from a URL / query string."""
    raw = (value or "").strip()
    if not raw:
        return ""
    if "://" in raw or "=" in raw:
        parsed = urlparse(raw if "://" in raw else "http://placeholder/?" + raw.lstrip("?"))
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        return (query.get("key") or "").strip()
    return raw


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _walk(elem: ET.Element, name: str):
    for child in elem.iter():
        if _local_tag(child.tag) == name:
            yield child


def _parse_float(text: str) -> float | None:
    cleaned = (text or "").strip().replace("\xa0", "").replace(" ", "")
    cleaned = cleaned.replace("₽", "").replace("руб.", "").replace("руб", "")
    cleaned = cleaned.replace(",", ".")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _is_plain_number(text: str) -> bool:
    return _parse_float(text) is not None and all(
        ch.isdigit() or ch in ".,-+ ₽\xa0" or ch in "руб."
        for ch in text.strip()
    )


def parse_balance_body(body: str) -> BalanceResult:
    """Parse XMLRiver (plain number) or XMLStock (JSON.balance) responses."""
    text = (body or "").strip()
    if not text:
        return BalanceResult(ok=False, error="Пустой ответ сервиса")

    if _is_plain_number(text):
        amount = _parse_float(text)
        if amount is not None:
            return BalanceResult(ok=True, amount=amount)

    if text.startswith(("{", "[")):
        try:
            data = json.loads(text)
        except ValueError:
            return BalanceResult(ok=False, error="Некорректный JSON")
        if not isinstance(data, dict):
            return BalanceResult(ok=False, error="Некорректный JSON")
        err = data.get("error")
        if err not in (None, 0, "0", False, ""):
            return BalanceResult(ok=False, error=str(err)[:200])
        for key in ("balance", "Balance"):
            if key not in data:
                continue
            raw = data[key]
            amount = float(raw) if isinstance(raw, (int, float)) else _parse_float(str(raw))
            if amount is not None:
                return BalanceResult(ok=True, amount=amount)
        return BalanceResult(ok=False, error="В ответе нет поля balance")

    if text.startswith(("<", "<?xml")):
        try:
            root = ET.fromstring(text)  # nosec B314
        except ET.ParseError:
            return BalanceResult(ok=False, error="Некорректный XML")
        err = next(_walk(root, "error"), None)
        if err is not None and (err.text or err.get("code")):
            msg = (err.text or f"Ошибка {err.get('code', '')}").strip()
            return BalanceResult(ok=False, error=msg[:200])
        node = next(_walk(root, "balance"), None)
        if node is not None and node.text:
            parsed = _parse_float(node.text)
            if parsed is not None:
                return BalanceResult(ok=True, amount=parsed)
        return BalanceResult(ok=False, error="В XML нет баланса")

    snippet = " ".join(text.split())[:200]
    if snippet.lower().startswith("error"):
        return BalanceResult(ok=False, error=snippet)
    return BalanceResult(ok=False, error="Не удалось разобрать баланс")


def _canonical_query(query: str) -> str:
    if not query:
        return ""
    pairs = sorted(parse_qsl(query, keep_blank_values=True))
    return urlencode(pairs)


def _normalize_url(url: str) -> str:
    raw = (url or "").strip().lower()
    parsed = urlparse(raw)
    host = parsed.netloc.removeprefix("www.")
    path = parsed.path.rstrip("/") or ""
    base = f"{host}{path}"
    query = _canonical_query(parsed.query)
    return f"{base}?{query}" if query else base


def urls_match(left: str, right: str) -> bool:
    a, b = _normalize_url(left), _normalize_url(right)
    return bool(a) and a == b


def index_url_for_check(
    original: str,
    final_url: str = "",
    canonical: str | None = None,
) -> str:
    """URL to send to the index API: canonical, else post-redirect, else original."""
    for candidate in (canonical, final_url, original):
        if not candidate:
            continue
        text = candidate.strip()
        if text.lower().startswith(("http://", "https://")):
            return text
    return original


def _doc_urls(root: ET.Element) -> list[str]:
    """URLs of organic <doc> hits only — not sitelinks or related blocks."""
    found: list[str] = []
    for doc in _walk(root, "doc"):
        for child in list(doc):
            if _local_tag(child.tag) == "url" and (child.text or "").strip():
                found.append(child.text.strip())
                break
    return found


def parse_index_xml(body: str, target_url: str) -> IndexCheckResult:
    """Interpret XMLRiver / XMLStock search XML as an index check.

    Indexed only if an organic <doc><url> matches the target.
    XMLRiver <found>100</found> is a default stub and must not count.
    """
    text = (body or "").strip()
    if not text:
        return IndexCheckResult("error", "Пустой ответ сервиса")
    try:
        root = ET.fromstring(text)  # nosec B314
    except ET.ParseError:
        return IndexCheckResult("error", "Некорректный XML")

    err = next(_walk(root, "error"), None)
    if err is not None:
        code = (err.get("code") or "").strip()
        msg = (err.text or f"Ошибка {code}").strip()
        if code == "15":
            return IndexCheckResult("not_indexed")
        lower = msg.lower()
        retryable = code in RETRYABLE_ERROR_CODES or (
            not code and any(marker in lower for marker in TRANSIENT_ERROR_MARKERS)
        )
        return IndexCheckResult(
            "error",
            msg[:200],
            retryable=retryable,
        )

    if any(urls_match(u, target_url) for u in _doc_urls(root)):
        return IndexCheckResult("indexed")
    return IndexCheckResult("not_indexed")


def canonical_search_endpoint(name: str, api_url: str) -> str:
    """Return a search endpoint, filling in the default path when only keys are given."""
    raw = (api_url or "").strip()
    creds = parse_user_key(raw)
    user, key = creds if creds else ("", "")
    parsed = urlparse(raw if "://" in raw else "")
    host = (parsed.netloc or "").lower()
    if "xmlriver" in host:
        if "/search/" in (parsed.path or ""):
            return raw
        return f"{parsed.scheme}://{parsed.netloc}/search/xml?user={user}&key={key}"
    if "xmlstock" in host:
        if "/google/" in (parsed.path or ""):
            return raw
        scheme = parsed.scheme or "https"
        return f"{scheme}://{parsed.netloc}/google/xml/?user={user}&key={key}"
    if name == PROVIDER_JSONSEO:
        key_only = extract_api_key(raw) or key
        if "jsonseo.ru" in host and "/google/xml" in (parsed.path or ""):
            if key_only and "key=" not in (parsed.query or ""):
                sep = "&" if parsed.query else "?"
                return f"{raw}{sep}key={key_only}"
            return raw
        return f"{JSONSEO_SEARCH_PATH}?key={key_only}"
    if name == PROVIDER_RIVER:
        return f"http://xmlriver.com/search/xml?user={user}&key={key}"
    return f"https://xmlstock.com/google/xml/?user={user}&key={key}"


def needs_balance_fetch(provider: str, preferred: str | None) -> bool:
    """False if the task picked the other service — skip that HTTP round-trip."""
    preferred = (preferred or "").strip()
    if not preferred:
        return True
    return provider == preferred


def pick_provider(
    river_url: str,
    river_balance: BalanceResult | None,
    stock_url: str,
    stock_balance: BalanceResult | None,
    preferred: str = "",
    jsonseo_key: str = "",
    jsonseo_balance: BalanceResult | None = None,
) -> tuple[IndexProvider | None, list[str]]:
    """Pick a usable provider. If ``preferred`` is set, only that service is used."""
    notices: list[str] = []
    river_url = (river_url or "").strip()
    stock_url = (stock_url or "").strip()
    jsonseo_key = (jsonseo_key or "").strip()
    preferred = (preferred or "").strip()

    def _consider(
        label: str, url: str, bal: BalanceResult | None, name: str
    ) -> IndexProvider | None:
        if not url:
            return None
        if bal is None:
            notices.append(f"{label}: не удалось получить баланс.")
            return None
        if not bal.ok:
            notices.append(f"{label}: {bal.error}")
            return None
        if bal.amount is None:
            notices.append(f"{label}: не удалось прочитать сумму баланса.")
            return None
        if bal.amount <= 0:
            notices.append(f"{label}: баланс 0 ₽ — сервис не будет использован.")
            return None
        return IndexProvider(
            name, canonical_search_endpoint(name, url), float(bal.amount)
        )

    if preferred == PROVIDER_JSONSEO:
        chosen = _consider("JSON SEO", jsonseo_key, jsonseo_balance, PROVIDER_JSONSEO)
        if chosen is not None:
            return chosen, notices
        notices.append(
            "Выбран JSON SEO, но сервис недоступен. "
            "Индексация в Google не выполняется."
        )
        return None, notices
    if preferred == PROVIDER_STOCK:
        chosen = _consider("XMLStock", stock_url, stock_balance, PROVIDER_STOCK)
        if chosen is not None:
            return chosen, notices
        notices.append(
            "Выбран XMLStock, но сервис недоступен. "
            "Индексация в Google не выполняется."
        )
        return None, notices
    if preferred == PROVIDER_RIVER:
        chosen = _consider("XMLRiver", river_url, river_balance, PROVIDER_RIVER)
        if chosen is not None:
            return chosen, notices
        notices.append(
            "Выбран XMLRiver, но сервис недоступен. "
            "Индексация в Google не выполняется."
        )
        return None, notices

    chosen = _consider("XMLRiver", river_url, river_balance, PROVIDER_RIVER)
    if chosen is not None:
        return chosen, notices
    chosen = _consider("XMLStock", stock_url, stock_balance, PROVIDER_STOCK)
    if chosen is not None:
        return chosen, notices

    if river_url or stock_url:
        notices.append(
            "Оба сервиса недоступны или с нулевым балансом. "
            "Индексация в Google не выполняется."
        )
    else:
        notices.append(
            "Не задан URL XMLRiver или XMLStock. "
            "Индексация в Google не выполняется."
        )
    return None, notices


def _http_get(url: str, headers: dict[str, str] | None = None) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Разрешены только http/https URL")
    req_headers = {"User-Agent": "BacklinkChecker/1.6"}
    if headers:
        req_headers.update(headers)
    req = Request(url, headers=req_headers)
    try:
        with urlopen(req, timeout=HTTP_TIMEOUT) as resp:  # nosec B310
            return resp.read().decode("utf-8", errors="replace")
    except TimeoutError as exc:
        raise URLError(str(exc) or "timeout") from exc


def fetch_balance(provider: str, api_url: str) -> BalanceResult:
    if provider == PROVIDER_JSONSEO:
        key = extract_api_key(api_url)
        if not key:
            return BalanceResult(ok=False, error="Не указан API-ключ")
        url = JSONSEO_BALANCE_PATH + "?" + urlencode({"key": key})
        try:
            body = _http_get(url, headers={"Authorization": f"Bearer {key}"})
        except HTTPError as exc:
            return BalanceResult(ok=False, error=f"HTTP {exc.code}")
        except URLError as exc:
            return BalanceResult(ok=False, error=str(exc.reason)[:200])
        except Exception as exc:
            logger.exception("Balance fetch failed")
            return BalanceResult(ok=False, error=str(exc)[:200])
        return parse_balance_body(body)
    creds = parse_user_key(api_url)
    if not creds:
        return BalanceResult(ok=False, error="В URL нет параметров user и key")
    user, key = creds
    if provider == PROVIDER_RIVER:
        url = XMLRIVER_BALANCE_PATH + "?" + urlencode({"user": user, "key": key})
    else:
        url = XMLSTOCK_BALANCE_PATH + "?" + urlencode({"user": user, "key": key})
    try:
        body = _http_get(url)
    except HTTPError as exc:
        return BalanceResult(ok=False, error=f"HTTP {exc.code}")
    except URLError as exc:
        return BalanceResult(ok=False, error=str(exc.reason)[:200])
    except Exception as exc:
        logger.exception("Balance fetch failed")
        return BalanceResult(ok=False, error=str(exc)[:200])
    return parse_balance_body(body)


def _with_query(endpoint: str, extra: dict[str, str]) -> str:
    parsed = urlparse(endpoint.strip())
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(extra)
    return urlunparse(parsed._replace(query=urlencode(query)))


def site_query_target(page_url: str) -> str:
    """host + path [+ query] without scheme — Google site: does not take https://."""
    parsed = urlparse(page_url.strip())
    host = parsed.netloc or parsed.path.split("/")[0]
    path = parsed.path if parsed.netloc else ""
    if path == "/":
        path = ""
    else:
        path = path.rstrip("/")
    target = f"{host}{path}"
    if parsed.query:
        target = f"{target}?{parsed.query}"
    return target


def build_index_request_url(provider: IndexProvider, page_url: str) -> str:
    if len(page_url) > MAX_QUERY_LEN:
        raise ValueError("URL длиннее 1400 символов")
    if provider.name == PROVIDER_RIVER:
        return _with_query(
            provider.endpoint,
            {"query": page_url, "inindex": "1", "strict": "1", "groupby": "10"},
        )
    return _with_query(
        provider.endpoint,
        {
            "query": f"site:{site_query_target(page_url)}",
            "nfpr": "1",
            "groupby": "10",
        },
    )


def check_url_indexed(page_url: str, provider: IndexProvider) -> IndexCheckResult:
    last = IndexCheckResult("error", "Нет ответа")
    for attempt in range(INDEX_RETRIES):
        try:
            url = build_index_request_url(provider, page_url)
        except ValueError as exc:
            return IndexCheckResult("error", str(exc))
        try:
            body = _http_get(url)
        except HTTPError as exc:
            last = IndexCheckResult(
                "error",
                f"HTTP {exc.code}",
                retryable=exc.code not in NON_RETRYABLE_HTTP,
            )
        except URLError as exc:
            last = IndexCheckResult(
                "error", str(exc.reason)[:200], retryable=True
            )
        except Exception as exc:
            logger.exception("Index check failed for %s", page_url)
            last = IndexCheckResult("error", str(exc)[:200], retryable=True)
        else:
            last = parse_index_xml(body, page_url)
        if last.status != "error" or not last.retryable:
            return last
        if attempt + 1 < INDEX_RETRIES:
            time.sleep(1.5 * (attempt + 1))
    return last


def format_balance_label(
    result: BalanceResult | None, empty_url: bool, kind: str = "url"
) -> str:
    if empty_url:
        if kind == "key":
            return "Укажите API-ключ, чтобы увидеть баланс"
        return "Укажите персональный URL, чтобы увидеть баланс"
    if result is None:
        return "Загрузка баланса…"
    if not result.ok:
        return f"Баланс недоступен: {result.error}"
    amount = result.amount if result.amount is not None else 0.0
    text = f"Баланс: {amount:.2f} ₽".replace(".", ",")
    if amount <= 0:
        text += " — сервис не будет использован"
    return text
