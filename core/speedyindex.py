"""Submit URLs to SpeedyIndex Google indexer (API v2)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from core.google_index import (
    BalanceResult,
    _normalize_url,
    extract_api_key,
    index_url_for_check,
)

logger = logging.getLogger(__name__)

PROVIDER_SPEEDYINDEX = "speedyindex"
SPEEDYINDEX_API = "https://api.speedyindex.com"
SPEEDYINDEX_MAX_URLS = 10_000
HTTP_TIMEOUT = 45


@dataclass
class SubmitItem:
    donor_id: int
    url: str


@dataclass
class SubmitResult:
    ok: bool
    task_id: str = ""
    error: str = ""
    submitted: int = 0


def _row_get(row, key, default=None):
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def eligible_index_submit_items(donors) -> list[SubmitItem]:
    """HTTP 200, acceptor found, not in Google, not already submitted."""
    items: list[SubmitItem] = []
    for row in donors:
        if _row_get(row, "http_status") != 200:
            continue
        if _row_get(row, "status") != "found":
            continue
        if _row_get(row, "google_indexed") != "not_indexed":
            continue
        if _row_get(row, "index_submitted_at"):
            continue
        url = index_url_for_check(
            str(_row_get(row, "url") or ""),
            str(_row_get(row, "final_url") or ""),
            _row_get(row, "canonical_url"),
        )
        if not url:
            continue
        items.append(SubmitItem(int(_row_get(row, "id") or 0), url))
    return items


def _prefer_https(current: str, candidate: str) -> str:
    if candidate.lower().startswith("https://") and current.lower().startswith(
        "http://"
    ):
        return candidate
    return current


def unique_submit_urls(
    items: list[SubmitItem],
) -> tuple[list[str], dict[str, list[int]]]:
    """Preserve first-seen URL order; collapse www / scheme / trailing slash."""
    urls: list[str] = []
    donor_ids: dict[str, list[int]] = {}
    first_for_norm: dict[str, str] = {}
    for item in items:
        key = _normalize_url(item.url) or item.url
        chosen = first_for_norm.get(key)
        if chosen is None:
            first_for_norm[key] = item.url
            urls.append(item.url)
            donor_ids[item.url] = [item.donor_id]
            continue
        better = _prefer_https(chosen, item.url)
        if better != chosen:
            ids = donor_ids.pop(chosen)
            donor_ids[better] = ids
            urls[urls.index(chosen)] = better
            first_for_norm[key] = better
            chosen = better
        donor_ids[chosen].append(item.donor_id)
    return urls, donor_ids


def index_submit_skip_reason(donors) -> str | None:
    """Why auto-send has nothing to do, or None if silence is fine."""
    index_missing = False
    for row in donors:
        if _row_get(row, "http_status") != 200:
            continue
        if _row_get(row, "status") != "found":
            continue
        indexed = _row_get(row, "google_indexed") or ""
        if indexed not in ("indexed", "not_indexed"):
            index_missing = True
    if index_missing:
        return (
            "Нет результата проверки индекса Google у доноров "
            "с HTTP 200 и найденным акцептором."
        )
    return None


def parse_balance_body(body: str) -> BalanceResult:
    text = (body or "").strip()
    if not text:
        return BalanceResult(ok=False, error="Пустой ответ сервиса")
    try:
        data = json.loads(text)
    except ValueError:
        return BalanceResult(ok=False, error="Некорректный JSON")
    if not isinstance(data, dict):
        return BalanceResult(ok=False, error="Некорректный JSON")
    code = data.get("code")
    if code not in (0, "0", None):
        err = data.get("error") or data.get("message") or f"Код {code}"
        return BalanceResult(ok=False, error=str(err)[:200])
    balance = data.get("balance")
    if isinstance(balance, dict):
        raw = balance.get("tokens")
        if raw in (None, 0, "0"):
            indexer = balance.get("indexer")
            raw = indexer if indexer not in (None,) else raw
    else:
        raw = balance
    if raw is None:
        return BalanceResult(ok=False, error="В ответе нет баланса индексатора")
    try:
        amount = float(raw)
    except (TypeError, ValueError):
        return BalanceResult(ok=False, error="Некорректный баланс")
    return BalanceResult(ok=True, amount=amount)


def format_balance_label(result: BalanceResult | None, empty_key: bool) -> str:
    if empty_key:
        return "Укажите API-ключ, чтобы увидеть баланс"
    if result is None:
        return "Загрузка баланса…"
    if not result.ok:
        return f"Баланс недоступен: {result.error}"
    amount = result.amount if result.amount is not None else 0.0
    text = f"Баланс: {int(amount)} ток."
    if amount <= 0:
        text += " — сервис не будет использован"
    return text


def parse_create_response(body: str, submitted: int = 0) -> SubmitResult:
    text = (body or "").strip()
    if not text:
        return SubmitResult(ok=False, error="Пустой ответ сервиса")
    try:
        data = json.loads(text)
    except ValueError:
        return SubmitResult(ok=False, error="Некорректный JSON")
    if not isinstance(data, dict):
        return SubmitResult(ok=False, error="Некорректный JSON")
    code = data.get("code")
    if code in (1, "1"):
        detail = data.get("message") or data.get("error") or ""
        msg = "Недостаточно средств на балансе SpeedyIndex"
        if detail:
            msg = f"{msg}: {detail}"
        return SubmitResult(ok=False, error=msg[:300])
    if code not in (0, "0"):
        err = data.get("error") or data.get("message") or f"Код {code}"
        return SubmitResult(ok=False, error=str(err)[:200])
    task_id = data.get("task_id") or data.get("id") or ""
    if not task_id:
        result = data.get("result")
        if isinstance(result, dict):
            task_id = result.get("task_id") or result.get("id") or ""
        elif isinstance(result, str):
            task_id = result
    return SubmitResult(ok=True, task_id=str(task_id), submitted=submitted)


def _http_json(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: str | None = None,
) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Разрешены только http/https URL")
    req_headers = {"User-Agent": "BacklinkChecker/1.6"}
    if headers:
        req_headers.update(headers)
    data = body.encode("utf-8") if body else None
    if data is not None:
        req_headers.setdefault("Content-Type", "application/json")
    req = Request(url, data=data, method=method, headers=req_headers)
    try:
        with urlopen(req, timeout=HTTP_TIMEOUT) as resp:  # nosec B310
            return resp.read().decode("utf-8", errors="replace")
    except TimeoutError as exc:
        raise URLError(str(exc) or "timeout") from exc


def _submit_result_from_http_error(exc: HTTPError, submitted: int) -> SubmitResult:
    body = ""
    try:
        raw = exc.read()
        body = raw.decode("utf-8", errors="replace") if raw else ""
    except (OSError, ValueError, AttributeError):
        body = ""
    text = body.strip()
    if text.startswith(("{", "[")):
        parsed = parse_create_response(text, submitted=0)
        if parsed.error or not parsed.ok:
            return parsed
    return SubmitResult(ok=False, error=f"HTTP {exc.code}", submitted=submitted)


def fetch_balance(api_key: str) -> BalanceResult:
    key = extract_api_key(api_key)
    if not key:
        return BalanceResult(ok=False, error="Не указан API-ключ")
    try:
        body = _http_json(
            "GET",
            f"{SPEEDYINDEX_API}/v2/account",
            headers={"Authorization": key},
        )
    except HTTPError as exc:
        return BalanceResult(ok=False, error=f"HTTP {exc.code}")
    except URLError as exc:
        return BalanceResult(ok=False, error=str(exc.reason)[:200])
    except Exception as exc:
        logger.exception("SpeedyIndex balance fetch failed")
        return BalanceResult(ok=False, error=str(exc)[:200])
    return parse_balance_body(body)


def submit_urls(api_key: str, urls: list[str], title: str = "") -> SubmitResult:
    key = extract_api_key(api_key)
    if not urls:
        return SubmitResult(ok=True, submitted=0)
    if not key:
        return SubmitResult(ok=False, error="Не указан API-ключ SpeedyIndex")
    submitted = 0
    last_id = ""
    chunks = [
        urls[start:start + SPEEDYINDEX_MAX_URLS]
        for start in range(0, len(urls), SPEEDYINDEX_MAX_URLS)
    ]
    for index, chunk in enumerate(chunks):
        chunk_title = title if index == 0 else f"{title} ({index + 1})"
        payload = json.dumps(
            {
                "title": chunk_title,
                "urls": chunk,
                "pay_per_indexed": True,
            },
            ensure_ascii=False,
        )
        try:
            body = _http_json(
                "POST",
                f"{SPEEDYINDEX_API}/v2/task/google/indexer/create",
                headers={"Authorization": key},
                body=payload,
            )
        except HTTPError as exc:
            parsed = _submit_result_from_http_error(exc, submitted=len(chunk))
            if submitted:
                parsed.submitted = submitted
                parsed.task_id = last_id
                parsed.error = f"Отправлено {submitted}, далее ошибка: {parsed.error}"
            return parsed
        except URLError as exc:
            err = str(exc.reason)[:200]
            if submitted:
                return SubmitResult(
                    ok=False,
                    task_id=last_id,
                    error=f"Отправлено {submitted}, далее ошибка: {err}",
                    submitted=submitted,
                )
            return SubmitResult(ok=False, error=err)
        except Exception as exc:
            logger.exception("SpeedyIndex submit failed")
            return SubmitResult(ok=False, error=str(exc)[:200], submitted=submitted)
        parsed = parse_create_response(body, submitted=len(chunk))
        if not parsed.ok:
            if submitted:
                parsed.submitted = submitted
                parsed.task_id = last_id
                parsed.error = f"Отправлено {submitted}, далее ошибка: {parsed.error}"
            return parsed
        submitted += len(chunk)
        last_id = parsed.task_id
    return SubmitResult(ok=True, task_id=last_id, submitted=submitted)
