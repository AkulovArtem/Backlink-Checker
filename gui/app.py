"""
Main application window — routes between the three screens.
"""

import json
import logging

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QStackedWidget, QFileDialog,
    QHBoxLayout, QVBoxLayout, QApplication, QMessageBox,
)

from db import database as db
from core.models import CheckConfig
from gui.theme import DARK_QSS, LIGHT_QSS
from gui.theme_toggle import ThemeToggle
from gui.task_list_view import TaskListView
from gui.task_create_view import TaskCreateView
from gui.report_view import ReportView
from gui.worker import CheckWorker
from export.excel_export import export_to_excel

logger = logging.getLogger(__name__)

SCREEN_LIST   = 0
SCREEN_CREATE = 1
SCREEN_REPORT = 2


class MainApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Backlink Checker - проверка обратных ссылок | Version 1.0.1")
        self.setMinimumSize(1200, 700)
        self.resize(1400, 800)

        self._dark_mode = db.get_setting("theme", "dark") == "dark"
        self._workers: dict[int, CheckWorker] = {}

        # Throttle report refresh to at most once per second during active checks
        self._report_refresh_timer = QTimer(self)
        self._report_refresh_timer.setSingleShot(True)
        self._report_refresh_timer.setInterval(1000)
        self._report_refresh_timer.timeout.connect(self._report_view_refresh_now)

        # Stacked widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Theme toggle button (top-right)
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 4, 12, 0)
        top_bar.addStretch()
        self._theme_btn = ThemeToggle(self._dark_mode)
        self._theme_btn.toggled.connect(self._toggle_theme)
        top_bar.addWidget(self._theme_btn)
        main_layout.addLayout(top_bar)

        # Screens
        self._stack = QStackedWidget()
        main_layout.addWidget(self._stack)

        self._list_view = TaskListView()
        self._list_view.set_app(self)

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

    def start_task(self, task_id: int):
        task = db.get_task(task_id)
        if not task:
            return

        donors = db.get_donors_for_task(task_id)
        try:
            target_domains = json.loads(task["target_domains"])
        except (json.JSONDecodeError, TypeError):
            logger.error("Corrupted target_domains for task %d", task_id)
            return

        config = CheckConfig(
            task_id=task_id,
            donor_urls=[(int(d["id"]), str(d["url"])) for d in donors],
            target_domains=target_domains,
            user_agent_preset=task["user_agent"],
            custom_user_agent=task["custom_user_agent"] or "",
            threads=task["threads"],
            timeout=task["timeout"],
        )

        worker = CheckWorker(config)
        self._workers[task_id] = worker
        self._wire_worker(worker, task_id)
        logger.info("Task %d started", task_id)

    # ── Worker lifecycle helpers ──────────────────────────────────────────

    def _wire_worker(self, worker: CheckWorker, task_id: int) -> None:
        worker.progress_updated.connect(
            lambda done, total, tid=task_id: self._on_progress(tid, done, total)
        )
        worker.donor_done.connect(
            lambda result, tid=task_id: self._list_view.update_task_row(tid)
        )
        worker.finished.connect(
            lambda ok, tid=task_id: self._on_finished(tid, ok)
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

    def retry_task(self, task_id: int):
        if task_id in self._workers:
            self._stop_worker(self._workers.pop(task_id))
        db.reset_task(task_id)
        self.start_task(task_id)
        self._list_view.refresh()

    def retry_failed_task(self, task_id: int):
        """Re-run only donors that previously failed to load (status = not_loaded)."""
        if task_id in self._workers:
            self._stop_worker(self._workers.pop(task_id))

        task = db.get_task(task_id)
        if not task:
            return
        failed = db.get_failed_donors_for_task(task_id)
        if not failed:
            logger.info("Task %d: no failed donors to retry", task_id)
            return

        db.reset_failed_donors(task_id)
        try:
            target_domains = json.loads(task["target_domains"])
        except (json.JSONDecodeError, TypeError):
            logger.error("Corrupted target_domains for task %d", task_id)
            return
        config = CheckConfig(
            task_id=task_id,
            donor_urls=[(int(d["id"]), str(d["url"])) for d in failed],
            target_domains=target_domains,
            user_agent_preset=task["user_agent"],
            custom_user_agent=task["custom_user_agent"] or "",
            threads=task["threads"],
            timeout=task["timeout"],
        )
        worker = CheckWorker(config)
        self._workers[task_id] = worker
        self._wire_worker(worker, task_id)
        self._list_view.refresh()
        logger.info("Task %d: retrying %d failed donor(s)", task_id, len(failed))

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

    def delete_task(self, task_id: int):
        if task_id in self._workers:
            self._stop_worker(self._workers.pop(task_id))
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
        reply = QMessageBox.question(
            parent,
            "Удалить задание",
            f"Удалить задание «{name}»?\n\nВсе доноры и бэклинки будут удалены безвозвратно.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.delete_task(task_id)

    def export_task(self, task_id: int):
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить Excel", f"task_{task_id}.xlsx", "Excel (*.xlsx)"
        )
        if not path:
            return
        try:
            export_to_excel(task_id, path)
            logger.info("Exported task %d to %s", task_id, path)
        except Exception as exc:
            logger.exception("Export error: %s", exc)
            QMessageBox.critical(
                self,
                "Ошибка экспорта",
                f"Не удалось сохранить файл:\n{exc}\n\nПодробности — в лог-файле.",
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
            self._report_view.refresh()

    def _on_finished(self, task_id: int, success: bool):
        self._workers.pop(task_id, None)
        self._report_refresh_timer.stop()   # cancel any pending throttled refresh
        self._list_view.update_task_row(task_id)
        if (self._stack.currentIndex() == SCREEN_REPORT
                and self._report_view._task_id == task_id):
            self._report_view.refresh()     # always refresh on completion
        logger.info("Task %d finished, success=%s", task_id, success)

    # ── Theme ─────────────────────────────────────────────────────────────

    def _toggle_theme(self, checked: bool):
        self._dark_mode = checked
        db.set_setting("theme", "dark" if self._dark_mode else "light")
        self._apply_theme()

    def _apply_theme(self):
        QApplication.instance().setStyleSheet(DARK_QSS if self._dark_mode else LIGHT_QSS)

    # ── Graceful shutdown ─────────────────────────────────────────────────

    def closeEvent(self, event):
        # Signal all workers to stop simultaneously, then wait for each
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
        event.accept()
