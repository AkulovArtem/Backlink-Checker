"""Google index check via XMLRiver (inindex) or XMLStock (site: query)."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

PROVIDER_RIVER = "xmlriver"
PROVIDER_STOCK = "xmlstock"

XMLRIVER_BALANCE_PATH = "https://xmlriver.com/api/get_balance/"
XMLSTOCK_BALANCE_PATH = "https://xmlstock.com/api/"

INDEX_CONCURRENCY = 10
HTTP_TIMEOUT = 25
MAX_QUERY_LEN = 1400

_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


@dataclass
class IndexCheckResult:
    status: str  # indexed | not_indexed | error
    error: str = ""


@dataclass
class BalanceResult:
    ok: bool
    amount: Optional[float] = None
    error: str = ""

    @property
    def is_usable(self) -> bool:
        return self.ok and self.amount is not None and self.amount > 0


@dataclass
class IndexProvider:
    name: str
    endpoint: str
    balance: float = 0.0


def parse_user_key(api_url: str) -> Optional[tuple[str, str]]:
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


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _walk(elem: ET.Element, name: str):
    for child in elem.iter():
        if _local_tag(child.tag) == name:
            yield child


def _parse_float(text: str) -> Optional[float]:
    cleaned = (text or "").strip().replace("\xa0", " ").replace(" ", "")
    cleaned = cleaned.replace("₽", "").replace("руб.", "").replace("руб", "")
    cleaned = cleaned.replace(",", ".")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        match = _NUM_RE.search(cleaned)
        if not match:
            return None
        try:
            return float(match.group(0).replace(",", "."))
        except ValueError:
            return None


def parse_balance_body(body: str) -> BalanceResult:
    """Parse a balance API response (plain number, XML, or JSON-like)."""
    text = (body or "").strip()
    if not text:
        return BalanceResult(ok=False, error="Пустой ответ сервиса")

    lowered = text.lower()
    if "error" in lowered and _parse_float(text) is None:
        snippet = re.sub(r"<[^>]+>", " ", text)
        snippet = " ".join(snippet.split())
        return BalanceResult(ok=False, error=snippet[:200] or "Ошибка сервиса")

    amount = _parse_float(text)
    if amount is not None and "<" not in text[:20] and "{" not in text[:20]:
        return BalanceResult(ok=True, amount=amount)

    if text.startswith("<") or text.startswith("<?xml"):
        try:
            root = ET.fromstring(text)  # nosec B314
        except ET.ParseError:
            root = None
        if root is not None:
            err = next(_walk(root, "error"), None)
            if err is not None and (err.text or err.get("code")):
                msg = (err.text or f"Ошибка {err.get('code', '')}").strip()
                return BalanceResult(ok=False, error=msg)
            for tag in ("balance", "sum", "amount", "money"):
                node = next(_walk(root, tag), None)
                if node is not None and node.text:
                    parsed = _parse_float(node.text)
                    if parsed is not None:
                        return BalanceResult(ok=True, amount=parsed)

    try:
        import json

        data = json.loads(text)
        found = _json_balance(data)
        if found is not None:
            return BalanceResult(ok=True, amount=found)
        if isinstance(data, dict):
            err = data.get("error") or data.get("message") or data.get("msg")
            if err and err not in (0, "0", False):
                return BalanceResult(ok=False, error=str(err)[:200])
    except (ValueError, TypeError):
        pass

    amount = _parse_float(text)
    if amount is not None:
        return BalanceResult(ok=True, amount=amount)
    return BalanceResult(ok=False, error="Не удалось разобрать баланс")


def _json_balance(data) -> Optional[float]:
    if isinstance(data, (int, float)):
        return float(data)
    if isinstance(data, str):
        return _parse_float(data)
    if isinstance(data, dict):
        for key in ("balance", "Balance", "sum", "amount", "money"):
            if key in data:
                parsed = _json_balance(data[key])
                if parsed is not None:
                    return parsed
        for value in data.values():
            parsed = _json_balance(value)
            if parsed is not None:
                return parsed
    if isinstance(data, list):
        for item in data:
            parsed = _json_balance(item)
            if parsed is not None:
                return parsed
    return None


def _normalize_url(url: str) -> str:
    raw = (url or "").strip().lower()
    parsed = urlparse(raw)
    host = parsed.netloc.removeprefix("www.")
    path = parsed.path.rstrip("/") or ""
    return f"{host}{path}"


def urls_match(left: str, right: str) -> bool:
    a, b = _normalize_url(left), _normalize_url(right)
    return bool(a) and a == b


def parse_index_xml(body: str, target_url: str) -> IndexCheckResult:
    """Interpret XMLRiver / XMLStock search XML as an index check."""
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
        if code == "15":
            return IndexCheckResult("not_indexed")
        msg = (err.text or f"Ошибка {code}").strip()
        return IndexCheckResult("error", msg[:200])

    doc_urls = [((node.text or "").strip()) for node in _walk(root, "url")]
    doc_urls = [u for u in doc_urls if u]
    if any(urls_match(u, target_url) for u in doc_urls):
        return IndexCheckResult("indexed")

    found_el = next(_walk(root, "found"), None)
    if found_el is not None and (found_el.text or "").strip():
        try:
            n = int(float((found_el.text or "0").strip().replace(",", ".")))
        except ValueError:
            n = 0
        if n == 0:
            return IndexCheckResult("not_indexed")
        # inindex=1 / site:url with hits but no exact URL match still counts
        return IndexCheckResult("indexed")

    if doc_urls:
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
    if name == PROVIDER_RIVER:
        return f"http://xmlriver.com/search/xml?user={user}&key={key}"
    return f"https://xmlstock.com/google/xml/?user={user}&key={key}"


def pick_provider(
    river_url: str,
    river_balance: Optional[BalanceResult],
    stock_url: str,
    stock_balance: Optional[BalanceResult],
) -> tuple[Optional[IndexProvider], list[str]]:
    """Pick XMLRiver if it has money, else XMLStock. Return notices for the UI."""
    notices: list[str] = []
    river_url = (river_url or "").strip()
    stock_url = (stock_url or "").strip()

    def _usable(url: str, bal: Optional[BalanceResult]) -> bool:
        return bool(url) and bal is not None and bal.is_usable

    if river_url:
        if river_balance is None:
            notices.append("XMLRiver: не удалось получить баланс.")
        elif not river_balance.ok:
            notices.append(f"XMLRiver: {river_balance.error}")
        elif river_balance.amount == 0:
            notices.append("XMLRiver: баланс 0 ₽ — сервис не будет использован.")
        elif _usable(river_url, river_balance):
            return (
                IndexProvider(
                    PROVIDER_RIVER,
                    canonical_search_endpoint(PROVIDER_RIVER, river_url),
                    float(river_balance.amount or 0),
                ),
                notices,
            )

    if stock_url:
        if stock_balance is None:
            notices.append("XMLStock: не удалось получить баланс.")
        elif not stock_balance.ok:
            notices.append(f"XMLStock: {stock_balance.error}")
        elif stock_balance.amount == 0:
            notices.append("XMLStock: баланс 0 ₽ — сервис не будет использован.")
        elif _usable(stock_url, stock_balance):
            return (
                IndexProvider(
                    PROVIDER_STOCK,
                    canonical_search_endpoint(PROVIDER_STOCK, stock_url),
                    float(stock_balance.amount or 0),
                ),
                notices,
            )

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


def _http_get(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Разрешены только http/https URL")
    req = Request(url, headers={"User-Agent": "BacklinkChecker/1.4"})
    with urlopen(req, timeout=HTTP_TIMEOUT) as resp:  # nosec B310
        return resp.read().decode("utf-8", errors="replace")


def fetch_balance(provider: str, api_url: str) -> BalanceResult:
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
    except Exception as exc:  # noqa: BLE001
        logger.exception("Balance fetch failed")
        return BalanceResult(ok=False, error=str(exc)[:200])
    return parse_balance_body(body)


def _with_query(endpoint: str, extra: dict[str, str]) -> str:
    parsed = urlparse(endpoint.strip())
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(extra)
    return urlunparse(parsed._replace(query=urlencode(query)))


def build_index_request_url(provider: IndexProvider, page_url: str) -> str:
    if len(page_url) > MAX_QUERY_LEN:
        raise ValueError("URL длиннее 1400 символов")
    if provider.name == PROVIDER_RIVER:
        return _with_query(
            provider.endpoint,
            {"query": page_url, "inindex": "1", "strict": "1"},
        )
    return _with_query(
        provider.endpoint,
        {"query": f"site:{page_url}", "nfpr": "1"},
    )


def check_url_indexed(page_url: str, provider: IndexProvider) -> IndexCheckResult:
    try:
        url = build_index_request_url(provider, page_url)
    except ValueError as exc:
        return IndexCheckResult("error", str(exc))
    try:
        body = _http_get(url)
    except HTTPError as exc:
        return IndexCheckResult("error", f"HTTP {exc.code}")
    except URLError as exc:
        return IndexCheckResult("error", str(exc.reason)[:200])
    except Exception as exc:  # noqa: BLE001
        logger.exception("Index check failed for %s", page_url)
        return IndexCheckResult("error", str(exc)[:200])
    return parse_index_xml(body, page_url)


def format_balance_label(result: Optional[BalanceResult], empty_url: bool) -> str:
    if empty_url:
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
