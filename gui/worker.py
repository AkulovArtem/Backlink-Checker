"""
QThread-based worker that runs the async checker in a dedicated event loop.
Emits Qt signals for progress and per-donor results.
"""

import asyncio
import logging
import sys

from PyQt6.QtCore import QThread, pyqtSignal

from core.models import CheckConfig, DonorResult
from core.checker import run_check
from db import database as db

logger = logging.getLogger(__name__)


class CheckWorker(QThread):
    # Signals
    donor_done = pyqtSignal(object)          # DonorResult
    progress_updated = pyqtSignal(int, int)  # done, total
    finished = pyqtSignal(bool)              # success

    def __init__(self, config: CheckConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._stop_event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def run(self):
        # ProactorEventLoop is required on Windows for subprocess support (Playwright).
        if sys.platform == "win32":
            self._loop = asyncio.ProactorEventLoop()
        else:
            self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop_event = asyncio.Event()

        db.update_task_status(self._config.task_id, "running", 0)

        try:
            self._loop.run_until_complete(
                run_check(
                    config=self._config,
                    result_callback=self._on_donor_result,
                    progress_callback=self._on_progress,
                    stop_event=self._stop_event,
                )
            )
            if self._stop_event.is_set():
                db.update_task_status(self._config.task_id, "pending", 0)
                self.finished.emit(False)
            else:
                db.update_task_status(self._config.task_id, "completed", 100)
                self.finished.emit(True)
        except Exception as exc:
            logger.exception("Worker error: %s", exc)
            db.update_task_status(self._config.task_id, "error", 0)
            self.finished.emit(False)
        finally:
            self._loop.close()

    def stop(self):
        if self._stop_event and self._loop:
            self._loop.call_soon_threadsafe(self._stop_event.set)

    # ── Callbacks (called from async context, safe to emit) ───────────────

    def _on_donor_result(self, result: DonorResult):
        # Persist to DB — isolated so a DB error never suppresses the UI signal
        try:
            db.update_donor(
                result.donor_id,
                http_status=result.http_status,
                title=result.title,
                canonical_url=result.canonical_url,
                internal_links=result.internal_links,
                external_links=result.external_links,
                index_google=result.indexability.google,
                index_yandex=result.indexability.yandex,
                index_bing=result.indexability.bing,
                index_baidu=result.indexability.baidu,
                meta_robots=result.indexability.meta_robots,
                x_robots_tag=result.indexability.x_robots_tag,
                status=result.status,
                error_code=result.error_code,
            )
            db.create_backlinks_bulk(result.donor_id, self._config.task_id, result.backlinks)
        except Exception:
            logger.exception("DB persist error for donor %d (%s)", result.donor_id, result.url)
        # Always update the UI regardless of DB outcome
        self.donor_done.emit(result)

    def _on_progress(self, done: int, total: int):
        pct = int(done / total * 100) if total > 0 else 0
        db.update_task_status(self._config.task_id, "running", pct)
        self.progress_updated.emit(done, total)
