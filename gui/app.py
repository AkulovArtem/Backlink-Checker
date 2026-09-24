"""
Main application window — routes between the three screens.
"""

import json
import logging
import time
from datetime import datetime, timezone

from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.google_index import (
    PROVIDER_JSONSEO,
    PROVIDER_RIVER,
    PROVIDER_STOCK,
    fetch_balance,
    needs_balance_fetch,
    pick_provider,
)
from core.models import CheckConfig
from core.speedyindex import (
    eligible_index_submit_items,
    index_submit_skip_reason,
    submit_urls,
    unique_submit_urls,
)
from core.task_start import (
    bump_generation,
    can_launch_after_balance,
    is_current_generation,
    is_task_busy,
    take_finished_worker,
)
from db import database as db
from export.excel_export import export_filename, export_to_excel
from gui.confirm import ask_confirm
from gui.constants import APP_VERSION
from gui.report_view import ReportView
from gui.settings_dialog import (
    SETTING_JSONSEO_KEY,
    SETTING_RIVER_URL,
    SETTING_SPEEDYINDEX_KEY,
    SETTING_STOCK_URL,
)
from gui.task_create_view import TaskCreateView
from gui.task_list_view import TaskListView
from gui.theme import DARK_QSS, LIGHT_QSS, make_palette
from gui.worker import CheckWorker
from utils.resource_path import resource_path

logger = logging.getLogger(__name__)

SCREEN_LIST   = 0
SCREEN_CREATE = 1
SCREEN_REPORT = 2

# The report rebuilds every widget; on large tasks that takes seconds, so the
# throttle backs off to keep the UI blocked at most ~1/_REFRESH_COST_FACTOR of the time.
_REFRESH_MIN_INTERVAL_MS = 1000
_REFRESH_COST_FACTOR = 4


class _BalanceResolveThread(QThread):
    resolved = pyqtSignal(object, object)

    def __init__(self, preferred: str = "", parent=None):
        super().__init__(parent)
        self._preferred = preferred

    def run(self):
        river_url = db.get_setting(SETTING_RIVER_URL, "")
        stock_url = db.get_setting(SETTING_STOCK_URL, "")
        jsonseo_key = db.get_setting(SETTING_JSONSEO_KEY, "")
        river_bal = (
            fetch_balance(PROVIDER_RIVER, river_url)
            if river_url and needs_balance_fetch(PROVIDER_RIVER, self._preferred)
            else None
        )
        stock_bal = (
            fetch_balance(PROVIDER_STOCK, stock_url)
            if stock_url and needs_balance_fetch(PROVIDER_STOCK, self._preferred)
            else None
        )
        jsonseo_bal = (
            fetch_balance(PROVIDER_JSONSEO, jsonseo_key)
            if jsonseo_key and needs_balance_fetch(PROVIDER_JSONSEO, self._preferred)
            else None
        )
        self.resolved.emit(*pick_provider(
            river_url, river_bal, stock_url, stock_bal, preferred=self._preferred,
            jsonseo_key=jsonseo_key, jsonseo_balance=jsonseo_bal,
        ))


class _ExportThread(QThread):
    """Writes the .xlsx off the GUI thread: 100k donors take ~10 s."""

    failed = pyqtSignal(str)

    def __init__(self, task_id: int, path: str, parent=None):
        super().__init__(parent)
        self._task_id = task_id
        self._path = path

    def run(self):
        try:
            export_to_excel(self._task_id, self._path)
            logger.info("Exported task %d to %s", self._task_id, self._path)
        except Exception as exc:
            logger.exception("Export error")
            self.failed.emit(str(exc) or type(exc).__name__)


class MainApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(
            f"Backlink Checker - проверка обратных ссылок | Version {APP_VERSION}"
        )
        self.setWindowIcon(QIcon(resource_path("icon.ico")))
        self.setMinimumSize(1200, 700)
        self.resize(1400, 800)

        self._dark_mode = db.get_setting("theme", "light") == "dark"
        self._workers: dict[int, CheckWorker] = {}
        self._starting: set[int] = set()
        self._stopping: set[int] = set()
        self._start_gen: dict[int, int] = {}
        self._balance_threads: list[_BalanceResolveThread] = []
        self._export_threads: list[_ExportThread] = []
        self._closing = False

        # Throttle report refresh during active checks (see _report_view_refresh_now)
        self._report_refresh_timer = QTimer(self)
        self._report_refresh_timer.setSingleShot(True)
        self._report_refresh_timer.setInterval(_REFRESH_MIN_INTERVAL_MS)
        self._report_refresh_timer.timeout.connect(self._report_view_refresh_now)

        # Stacked widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Screens
        self._stack = QStackedWidget()
        main_layout.addWidget(self._stack)

        self._list_view = TaskListView(dark_mode=self._dark_mode)
        self._list_view.set_app(self)
        self._theme_btn = self._list_view.theme_toggle()
        self._theme_btn.toggled.connect(self._toggle_theme)

        self._create_view = TaskCreateView()
        self._create_view.set_app(self)

        self._report_view = ReportView()
        self._report_view.set_app(self)

        self._stack.addWidget(self._list_view)   # 0
        self._stack.addWidget(self._create_view) # 1
        self._stack.addWidget(self._report_view) # 2

        self._apply_theme()

    # ── Navigation ────────────────────────────────────────────────────────

    def show_list(self):
        self._list_view.refresh()
        self._stack.setCurrentIndex(SCREEN_LIST)

    def show_create(self):
        self._create_view.reset()
        self._stack.setCurrentIndex(SCREEN_CREATE)

    def show_report(self, task_id: int):
        self._report_view.load_task(task_id)
        self._stack.setCurrentIndex(SCREEN_REPORT)

    # ── Task actions ──────────────────────────────────────────────────────

    def _is_busy(self, task_id: int) -> bool:
        return is_task_busy(
            closing=self._closing,
            has_worker=task_id in self._workers,
            is_starting=task_id in self._starting,
            is_stopping=task_id in self._stopping,
        )

    def _mark_running_in_ui(self, task_id: int) -> None:
        db.update_task_status(task_id, "running", 0)
        self._list_view.update_task_row(task_id)

    def _revert_orphan_running(self, task_id: int) -> None:
        if task_id in self._workers:
            return
        task = db.get_task(task_id)
        if task and task["status"] == "running":
            db.update_task_status(task_id, "pending", 0)
            self._list_view.update_task_row(task_id)

    def start_task(self, task_id: int):
        """Check pending donors for the task. Leaves already-checked rows intact."""
        if self._is_busy(task_id):
            logger.warning("Task %d is already running", task_id)
            return

        task = db.get_task(task_id)
        if not task:
            return

        donors = db.get_pending_donors_for_task(task_id)
        if not donors:
            logger.info("Task %d: no pending donors to check", task_id)
            return

        try:
            target_domains = db.parse_target_domains(task["target_domains"])
        except (json.JSONDecodeError, TypeError):
            logger.error("Corrupted target_domains for task %d", task_id)
            return

        check_index = False
        try:
            check_index = bool(task["check_google_index"])
        except (KeyError, IndexError):
            check_index = False

        donor_urls = [(int(d["id"]), str(d["url"])) for d in donors]
        if check_index:
            preferred = ""
            try:
                preferred = str(task["index_provider"] or "")
            except (KeyError, IndexError):
                preferred = ""
            gen = bump_generation(self._start_gen, task_id)
            self._starting.add(task_id)
            self._mark_running_in_ui(task_id)
            thread = _BalanceResolveThread(preferred, self)
            thread.resolved.connect(
                lambda provider, notices, tid=task_id, urls=donor_urls, t=task, domains=target_domains, g=gen:
                self._on_index_provider_ready(
                    tid, urls, t, domains, provider, notices, g
                )
            )
            thread.finished.connect(lambda t=thread: self._reap_balance_thread(t))
            self._balance_threads.append(thread)
            thread.start()
            return

        self._launch_check_worker(
            task_id, donor_urls, task, target_domains, False, None
        )

    def _on_index_provider_ready(
        self, task_id, donor_urls, task, target_domains, provider, notices, gen
    ):
        self._starting.discard(task_id)
        if notices and is_current_generation(self._start_gen, task_id, gen) and not self._closing:
            QMessageBox.warning(
                self, "Проверка индексации", "\n\n".join(notices)
            )
        if not can_launch_after_balance(
            closing=self._closing,
            gen_current=is_current_generation(self._start_gen, task_id, gen),
            task_exists=db.get_task(task_id) is not None,
            has_worker=task_id in self._workers,
        ):
            if (
                is_current_generation(self._start_gen, task_id, gen)
                and task_id not in self._workers
            ):
                self._revert_orphan_running(task_id)
            return
        self._launch_check_worker(
            task_id, donor_urls, task, target_domains, provider is not None, provider
        )

    def _launch_check_worker(
        self, task_id, donor_urls, task, target_domains, check_index, provider
    ):
        config = CheckConfig(
            task_id=task_id,
            donor_urls=donor_urls,
            target_domains=target_domains,
            user_agent_preset=task["user_agent"],
            custom_user_agent=task["custom_user_agent"] or "",
            threads=task["threads"],
            timeout=task["timeout"],
            check_google_index=check_index,
            index_provider=provider,
        )
        db.update_task_status(task_id, "running", 0)
        worker = CheckWorker(config)
        self._workers[task_id] = worker
        self._wire_worker(worker, task_id)
        self._list_view.update_task_row(task_id)
        logger.info("Task %d started (%d pending donor(s))", task_id, len(donor_urls))

    # ── Worker lifecycle helpers ──────────────────────────────────────────

    def _wire_worker(self, worker: CheckWorker, task_id: int) -> None:
        worker.progress_updated.connect(
            lambda done, total, tid=task_id: self._on_progress(tid, done, total)
        )
        worker.donor_done.connect(
            lambda result, tid=task_id: self._list_view.update_task_row(tid)
        )
        worker.finished.connect(
            lambda ok, tid=task_id, w=worker: self._on_finished(tid, ok, w)
        )
        worker.start()

    def _stop_worker(self, worker: CheckWorker) -> None:
        """Signal worker to stop and wait without freezing the GUI event loop."""
        worker.stop()
        step, limit, elapsed = 50, 5000, 0
        while elapsed < limit:
            if worker.wait(step):
                return
            QApplication.processEvents()
            elapsed += step
        worker.terminate()
        worker.wait(1000)

    def _reap_balance_thread(self, thread: _BalanceResolveThread) -> None:
        try:
            self._balance_threads.remove(thread)
        except ValueError:
            pass

    def _stop_and_reap_worker(self, task_id: int) -> None:
        """Stop a running worker while keeping the task busy for the UI."""
        worker = self._workers.get(task_id)
        if worker is None:
            return
        self._stopping.add(task_id)
        try:
            self._stop_worker(worker)
        finally:
            self._workers.pop(task_id, None)
            self._stopping.discard(task_id)

    def continue_task(self, task_id: int):
        """Resume pending donors without wiping already-checked rows."""
        if self._is_busy(task_id):
            QMessageBox.information(
                self,
                "Задание выполняется",
                "Дождитесь окончания проверки.",
            )
            return
        pending = db.get_pending_donors_for_task(task_id)
        if not pending:
            QMessageBox.information(
                self,
                "Нет доноров в очереди",
                "Все доноры уже проверены. «Повторить неудачные» перезапустит ошибки загрузки.",
            )
            return
        self.start_task(task_id)
        self._list_view.refresh()

    def retry_task(self, task_id: int):
        self._cancel_start(task_id)
        self._stop_and_reap_worker(task_id)
        db.reset_task(task_id)
        self.start_task(task_id)
        self._list_view.refresh()

    def retry_failed_task(self, task_id: int):
        """Re-run donors that failed to load or whose Google index check failed."""
        failed = db.get_failed_donors_for_task(task_id)
        if not failed:
            QMessageBox.information(
                self,
                "Нет неудачных доноров",
                "Нет доноров со статусом «Не загружено» или с ошибкой "
                "проверки индекса Google. «Продолжить проверку» возьмёт "
                "оставшихся в очереди.",
            )
            return

        self._cancel_start(task_id)
        self._stop_and_reap_worker(task_id)
        db.reset_failed_donors(task_id)
        self.start_task(task_id)
        self._list_view.refresh()
        logger.info("Task %d: retrying %d failed donor(s)", task_id, len(failed))

    def edit_task(self, task_id: int):
        """Open the create form in append mode for an existing (not running) task."""
        if self._is_busy(task_id):
            QMessageBox.information(
                self,
                "Задание выполняется",
                "Дождитесь окончания проверки, затем добавьте ссылки.",
            )
            return
        task = db.get_task(task_id)
        if not task:
            return
        count = db.count_task_donors(task_id)
        self._create_view.enter_append_mode(task, count)
        self._stack.setCurrentIndex(SCREEN_CREATE)
        logger.info("Task %d opened for appending donors", task_id)

    def clone_task(self, task_id: int):
        """Open the Create-task form pre-filled with an existing task's data."""
        task = db.get_task(task_id)
        if not task:
            return
        donors = db.get_donors_for_task(task_id)
        self._create_view.reset()
        self._create_view.prefill(task, donors)
        self._stack.setCurrentIndex(SCREEN_CREATE)
        logger.info("Task %d cloned into create form", task_id)

    def _cancel_start(self, task_id: int) -> None:
        if task_id in self._starting:
            bump_generation(self._start_gen, task_id)
            self._starting.discard(task_id)
            self._revert_orphan_running(task_id)

    def delete_task(self, task_id: int):
        self._cancel_start(task_id)
        self._stop_and_reap_worker(task_id)
        db.delete_task(task_id)
        # If we're viewing this task's report — go back to list
        if (self._stack.currentIndex() == SCREEN_REPORT
                and self._report_view._task_id == task_id):
            self._report_view._task_id = None
            self.show_list()
        else:
            self._list_view.refresh()
        logger.info("Task %d deleted", task_id)

    def confirm_and_delete_task(self, task_id: int, parent) -> None:
        task = db.get_task(task_id)
        name = task["name"] if task else f"#{task_id}"
        if ask_confirm(
            parent,
            "Удалить задание",
            f"Удалить задание «{name}»?\n\n"
            "Все доноры и бэклинки будут удалены безвозвратно.",
        ):
            self.delete_task(task_id)

    def wipe_check_data(self) -> None:
        """Stop all checks and delete every task. Settings are kept."""
        for task_id in list(self._starting):
            self._cancel_start(task_id)
        for task_id in list(self._workers):
            self._stop_and_reap_worker(task_id)
        db.wipe_check_data()
        self._report_view._task_id = None
        self.show_list()
        logger.info("All tasks wiped")

    def export_task(self, task_id: int):
        task = db.get_task(task_id)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить Excel",
            export_filename(task["name"] if task else "", task_id),
            "Excel (*.xlsx)",
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"  # a file without the extension will not open on double-click
        # Modal busy dialog: the window stays responsive (no "not responding")
        # while the task cannot be changed or deleted mid-export.
        progress = QProgressDialog("Сохранение Excel…", "", 0, 0, self)
        progress.setWindowTitle("Экспорт")
        progress.setCancelButton(None)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        thread = _ExportThread(task_id, path, self)
        thread.failed.connect(self._on_export_failed)
        thread.finished.connect(lambda t=thread, d=progress: self._on_export_done(t, d))
        self._export_threads.append(thread)
        thread.start()

    def _on_export_done(self, thread: _ExportThread, progress: QProgressDialog) -> None:
        progress.close()
        progress.deleteLater()
        if thread in self._export_threads:
            self._export_threads.remove(thread)
        thread.deleteLater()

    def _on_export_failed(self, message: str) -> None:
        if self._closing:
            return
        QMessageBox.critical(
            self,
            "Ошибка экспорта",
            f"Не удалось сохранить файл:\n{message}\n\nПодробности — в лог-файле.",
        )

    # ── Worker callbacks ──────────────────────────────────────────────────

    def _on_progress(self, task_id: int, done: int, total: int):
        self._list_view.update_task_row(task_id)
        if (self._stack.currentIndex() == SCREEN_REPORT
                and self._report_view._task_id == task_id
                and not self._report_refresh_timer.isActive()):
            self._report_refresh_timer.start()

    def _report_view_refresh_now(self):
        """Called by the throttle timer — rebuilds the report if still visible."""
        if self._stack.currentIndex() == SCREEN_REPORT:
            started = time.monotonic()
            self._report_view.refresh()
            cost_ms = (time.monotonic() - started) * 1000
            self._report_refresh_timer.setInterval(
                max(_REFRESH_MIN_INTERVAL_MS, int(cost_ms * _REFRESH_COST_FACTOR))
            )

    def _on_finished(self, task_id: int, success: bool, worker=None):
        if worker is None:
            worker = self.sender()
        if not take_finished_worker(self._workers, task_id, worker):
            return
        self._report_refresh_timer.stop()   # cancel any pending throttled refresh
        self._list_view.update_task_row(task_id)
        if (self._stack.currentIndex() == SCREEN_REPORT
                and self._report_view._task_id == task_id):
            self._report_view.refresh()     # always refresh on completion
        logger.info("Task %d finished, success=%s", task_id, success)
        if success and not self._closing:
            self._maybe_auto_submit_index(task_id)

    def _maybe_auto_submit_index(self, task_id: int) -> None:
        task = db.get_task(task_id)
        if not task:
            return
        try:
            send = bool(task["send_to_index"])
        except (KeyError, IndexError):
            send = False
        if send:
            self.send_task_to_index(task_id, auto=True)

    def send_task_to_index(self, task_id: int, auto: bool = False) -> None:
        """Send eligible donor URLs to SpeedyIndex."""
        if not auto and self._is_busy(task_id):
            QMessageBox.information(
                self,
                "Задание выполняется",
                "Дождитесь окончания проверки, затем отправьте на индексацию.",
            )
            return
        key = (db.get_setting(SETTING_SPEEDYINDEX_KEY, "") or "").strip()
        if not key:
            if not auto:
                QMessageBox.warning(
                    self,
                    "SpeedyIndex",
                    "Укажите API-ключ SpeedyIndex в Настройках.",
                )
            else:
                QMessageBox.warning(
                    self,
                    "SpeedyIndex",
                    "Автоотправка пропущена: не указан API-ключ SpeedyIndex.",
                )
            return
        task = db.get_task(task_id)
        donors = db.get_donors_for_index_submit(task_id)
        items = eligible_index_submit_items(donors)
        if not items:
            reason = index_submit_skip_reason(donors)
            if reason:
                QMessageBox.warning(self, "SpeedyIndex", reason)
            elif not auto:
                QMessageBox.information(
                    self,
                    "Отправка на индексацию",
                    "Нет URL для отправки: нужны HTTP 200, найденный акцептор "
                    "и отсутствие в индексе Google. Уже отправленные пропускаются.",
                )
            return
        urls, donor_ids = unique_submit_urls(items)
        if not auto and not ask_confirm(
            self,
            "Отправить на индексацию",
            f"Отправить {len(urls)} URL в SpeedyIndex "
            "(Google indexer, оплата за проиндексированные)?\n"
            "Уже отправленные URL не включаются.",
            ok_label="Отправить",
        ):
            return
        title = task["name"] if task else f"Задание {task_id}"
        try:
            result = submit_urls(key, urls, title=title)
        except Exception as exc:
            logger.exception("SpeedyIndex submit failed")
            QMessageBox.warning(
                self,
                "SpeedyIndex",
                f"Не удалось отправить URL:\n{exc}",
            )
            return
        if result.submitted:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            stamped: list[int] = []
            for url in urls[: result.submitted]:
                stamped.extend(donor_ids.get(url, []))
            db.mark_donors_submitted(stamped, now)
            if (
                self._stack.currentIndex() == SCREEN_REPORT
                and self._report_view._task_id == task_id
            ):
                self._report_view.refresh()
        if result.ok:
            QMessageBox.information(
                self,
                "SpeedyIndex",
                f"Отправлено {result.submitted} URL на индексацию в Google.",
            )
        else:
            extra = (
                f"\nУже отправлено: {result.submitted}." if result.submitted else ""
            )
            QMessageBox.warning(
                self,
                "SpeedyIndex",
                f"{result.error}{extra}",
            )

    # ── Theme ─────────────────────────────────────────────────────────────

    def _toggle_theme(self, checked: bool):
        self._dark_mode = checked
        db.set_setting("theme", "dark" if self._dark_mode else "light")
        self._apply_theme()

    def _apply_theme(self):
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        # Palette first: custom-painted bars and rich-text links read it; QSS does not.
        app.setPalette(make_palette(self._dark_mode))
        app.setStyleSheet(DARK_QSS if self._dark_mode else LIGHT_QSS)

    # ── Graceful shutdown ─────────────────────────────────────────────────

    def closeEvent(self, event):
        self._closing = True
        for thread in list(self._balance_threads):
            try:
                thread.resolved.disconnect()
            except TypeError:
                pass
        for task_id in list(self._starting):
            self._revert_orphan_running(task_id)
        self._starting.clear()
        workers = list(self._workers.values())
        for w in workers:
            w.stop()
        for w in workers:
            step, elapsed = 50, 0
            while elapsed < 5000:
                if w.wait(step):
                    break
                QApplication.processEvents()
                elapsed += step
            else:
                w.terminate()
                w.wait(1000)
        # An export in progress is left to finish, or the .xlsx would be truncated.
        for thread in list(self._export_threads):
            while not thread.wait(50):
                QApplication.processEvents()
        for thread in list(self._balance_threads):
            step, elapsed = 50, 0
            while elapsed < 8000:
                if thread.wait(step):
                    break
                QApplication.processEvents()
                elapsed += step
        event.accept()
