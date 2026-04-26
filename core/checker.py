"""
Async checker: Playwright page loading + parsing + indexability per donor URL.
Communicates progress via an asyncio.Queue so the Qt worker can relay signals.
"""

import asyncio
import logging
from typing import Callable

from playwright.async_api import async_playwright, TimeoutError as PWTimeout, Error as PWError

from core.models import CheckConfig, DonorResult
from core.parser import parse_page
from core.indexability import check_indexability
from utils.user_agents import get_profile

logger = logging.getLogger(__name__)


_INFINITE_SCROLL_GROWTH = 1.30  # page grew >30 % → likely infinite pagination


async def _scroll_for_lazy_content(page) -> None:
    """Trigger lazy-loaded content by scrolling down.

    Performs up to two scroll passes.  Aborts after the first pass if the page
    height grows by more than 30 % — a reliable sign of infinite-scroll
    pagination where further scrolling would keep adding new posts indefinitely.
    """
    try:
        prev_h: int = await page.evaluate("document.body.scrollHeight")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.8)

        new_h: int = await page.evaluate("document.body.scrollHeight")
        if new_h >= prev_h * _INFINITE_SCROLL_GROWTH:
            # Infinite scroll detected — one pass is enough, stop here
            return

        # Second pass: stable page, trigger any remaining lazy observers
        if new_h > prev_h:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.5)

    except Exception:
        pass  # non-critical — JS errors on exotic pages must not break checking


async def _check_one(
    page,
    donor_id: int,
    url: str,
    config: CheckConfig,
) -> DonorResult:
    result = DonorResult(donor_id=donor_id, url=url)
    response_headers: dict = {}

    try:
        response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=config.timeout * 1000,
        )

        if response is None:
            result.status = "not_loaded"
            result.error_code = "NO_RESPONSE"
            return result

        result.http_status = response.status

        # Capture headers for X-Robots-Tag
        try:
            response_headers = dict(await response.all_headers())
        except Exception:
            response_headers = {}

        if result.http_status >= 400:
            result.status = "not_loaded"
            result.error_code = f"HTTP_{result.http_status}"
            return result

        await _scroll_for_lazy_content(page)
        html = await page.content()

    except PWTimeout:
        result.status = "not_loaded"
        result.error_code = "TIMEOUT"
        logger.warning("Timeout: %s", url)
        return result
    except PWError as exc:
        msg = str(exc)
        if any(k in msg.lower() for k in ("net::", "err_", "blocked")):
            result.error_code = "NET_ERROR"
        else:
            result.error_code = "PW_ERROR"
        result.status = "not_loaded"
        logger.warning("PWError [%s]: %s", result.error_code, url)
        return result
    except Exception as exc:
        result.status = "not_loaded"
        result.error_code = "UNKNOWN"
        logger.exception("Unexpected error for %s: %s", url, exc)
        return result

    # ── Parse ──────────────────────────────────────────────────────────────
    try:
        parsed = parse_page(html, url, config.target_domains)
        result.title = parsed["title"]
        result.canonical_url = parsed["canonical_url"]
        result.internal_links = parsed["internal_links"]
        result.external_links = parsed["external_links"]
        result.backlinks = parsed["backlinks"]

        # Indexability
        idx = check_indexability(parsed["soup"], response_headers)
        result.indexability = idx

        result.status = "found" if result.backlinks else "not_found"

    except Exception as exc:
        logger.exception("Parse error for %s: %s", url, exc)
        result.status = "not_loaded"
        result.error_code = "PARSE_ERROR"

    return result


async def run_check(
    config: CheckConfig,
    result_callback: Callable[[DonorResult], None],
    progress_callback: Callable[[int, int], None],
    stop_event: asyncio.Event,
) -> None:
    """
    Main async entry point.
    - result_callback(donor_result)  called after each URL is processed
    - progress_callback(done, total) called after each URL
    - stop_event: set() to cancel
    """
    profile = get_profile(config.user_agent_preset, config.custom_user_agent)
    semaphore = asyncio.Semaphore(config.threads)
    total = len(config.donor_urls)
    done_count = 0
    lock = asyncio.Lock()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)

        async def process(donor_id: int, url: str) -> None:
            nonlocal done_count
            if stop_event.is_set():
                return
            async with semaphore:
                if stop_event.is_set():
                    return
                context = await browser.new_context(
                    user_agent=profile.user_agent,
                    viewport={"width": profile.viewport_width, "height": profile.viewport_height},
                    is_mobile=profile.is_mobile,
                )
                page = await context.new_page()
                try:
                    donor_result = await _check_one(page, donor_id, url, config)
                finally:
                    await page.close()
                    await context.close()

                try:
                    result_callback(donor_result)
                except Exception as cb_exc:
                    logger.exception("result_callback error for %s: %s", url, cb_exc)

                async with lock:
                    done_count += 1
                    try:
                        progress_callback(done_count, total)
                    except Exception as cb_exc:
                        logger.exception("progress_callback error: %s", cb_exc)

        tasks = [
            asyncio.create_task(process(donor_id, url))
            for donor_id, url in config.donor_urls
        ]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()
            # Wait for tasks to finish before closing the browser;
            # otherwise pages in flight get a PWError mid-navigation.
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await browser.close()

    logger.info("Check complete: %d/%d", done_count, total)
