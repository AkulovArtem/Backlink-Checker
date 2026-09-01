import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from db import database as db
from gui.app import MainApp


class _FakeWorker:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True

    def wait(self, _ms):
        return True

    def terminate(self):
        pass


class AppLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_path = db.DB_PATH
        db.DB_PATH = Path(self._tmp.name) / "test.db"
        db.init_db()
        self.window = MainApp()

    def tearDown(self):
        self.window.close()
        db.DB_PATH = self._old_path
        self._tmp.cleanup()

    def test_stale_finished_does_not_drop_new_worker(self):
        tid = db.create_task("t", ["example.com"])
        old, new = _FakeWorker(), _FakeWorker()
        self.window._workers[tid] = new
        self.window._on_finished(tid, False, old)
        self.assertIs(self.window._workers.get(tid), new)

    @patch("gui.app.QMessageBox.information")
    def test_retry_failed_without_failures_does_not_stop_running(self, _info):
        tid = db.create_task("t", ["example.com"])
        db.create_donors_bulk(tid, ["https://a.example/1"])
        db.update_donor(db.get_donors_for_task(tid)[0]["id"], status="found")
        worker = _FakeWorker()
        self.window._workers[tid] = worker
        self.window.retry_failed_task(tid)
        self.assertFalse(worker.stopped)
        self.assertIs(self.window._workers.get(tid), worker)

    @patch("gui.app.QMessageBox.information")
    def test_retry_failed_with_failures_stops_then_restarts(self, _info):
        tid = db.create_task("t", ["example.com"])
        db.create_donors_bulk(tid, ["https://a.example/1"])
        db.update_donor(
            db.get_donors_for_task(tid)[0]["id"], status="not_loaded"
        )
        worker = _FakeWorker()
        self.window._workers[tid] = worker
        with patch.object(self.window, "start_task") as start:
            self.window.retry_failed_task(tid)
        self.assertTrue(worker.stopped)
        start.assert_called_once_with(tid)
        pending = db.get_pending_donors_for_task(tid)
        self.assertEqual(len(pending), 1)

    @patch("gui.app.submit_urls")
    @patch("gui.app.QMessageBox.information")
    def test_auto_submit_on_success_sends_only_eligible(self, _info, mock_submit):
        from gui.settings_dialog import SETTING_SPEEDYINDEX_KEY

        mock_submit.return_value = type(
            "R", (), {"ok": True, "task_id": "t1", "submitted": 1, "error": ""}
        )()
        db.set_setting(SETTING_SPEEDYINDEX_KEY, "k")
        tid = db.create_task(
            "t",
            ["example.com"],
            send_to_index=True,
            index_submitter="speedyindex",
        )
        db.create_donors_bulk(
            tid,
            ["https://ok.example/1", "https://skip.example/2", "https://idx.example/3"],
        )
        donors = db.get_donors_for_task(tid)
        db.update_donor(
            int(donors[0]["id"]),
            status="found",
            http_status=200,
            google_indexed="not_indexed",
        )
        db.update_donor(
            int(donors[1]["id"]),
            status="not_found",
            http_status=200,
            google_indexed="not_indexed",
        )
        db.update_donor(
            int(donors[2]["id"]),
            status="found",
            http_status=200,
            google_indexed="indexed",
        )
        worker = _FakeWorker()
        self.window._workers[tid] = worker
        self.window._on_finished(tid, True, worker)
        mock_submit.assert_called_once()
        urls = mock_submit.call_args.args[1]
        self.assertEqual(urls, ["https://ok.example/1"])
        self.assertTrue(db.get_donors_for_task(tid)[0]["index_submitted_at"])

    @patch("gui.app.submit_urls")
    @patch("gui.app.QMessageBox.information")
    def test_auto_submit_sends_final_url_after_redirect(self, _info, mock_submit):
        from gui.settings_dialog import SETTING_SPEEDYINDEX_KEY

        mock_submit.return_value = type(
            "R", (), {"ok": True, "task_id": "t1", "submitted": 1, "error": ""}
        )()
        db.set_setting(SETTING_SPEEDYINDEX_KEY, "k")
        tid = db.create_task(
            "t",
            ["example.com"],
            send_to_index=True,
            index_submitter="speedyindex",
        )
        db.create_donors_bulk(tid, ["http://ok.example/1"])
        db.update_donor(
            int(db.get_donors_for_task(tid)[0]["id"]),
            status="found",
            http_status=200,
            google_indexed="not_indexed",
            final_url="https://www.ok.example/1",
        )
        worker = _FakeWorker()
        self.window._workers[tid] = worker
        self.window._on_finished(tid, True, worker)
        mock_submit.assert_called_once()
        self.assertEqual(mock_submit.call_args.args[1], ["https://www.ok.example/1"])

    @patch("gui.app.submit_urls")
    @patch("gui.app.QMessageBox.warning")
    def test_auto_submit_warns_when_index_was_not_checked(self, mock_warn, mock_submit):
        from gui.settings_dialog import SETTING_SPEEDYINDEX_KEY

        db.set_setting(SETTING_SPEEDYINDEX_KEY, "k")
        tid = db.create_task(
            "t",
            ["example.com"],
            send_to_index=True,
            index_submitter="speedyindex",
        )
        db.create_donors_bulk(tid, ["https://ok.example/1"])
        db.update_donor(
            int(db.get_donors_for_task(tid)[0]["id"]),
            status="found",
            http_status=200,
        )
        worker = _FakeWorker()
        self.window._workers[tid] = worker
        self.window._on_finished(tid, True, worker)
        mock_submit.assert_not_called()
        mock_warn.assert_called_once()
        text = mock_warn.call_args.args[2].lower()
        self.assertIn("индекс", text)
        self.assertNotIn("автоотправка", text)

    @patch("gui.app.submit_urls")
    @patch("gui.app.QMessageBox.warning")
    def test_manual_send_index_missing_warning_is_not_auto_worded(
        self, mock_warn, mock_submit
    ):
        from gui.settings_dialog import SETTING_SPEEDYINDEX_KEY

        db.set_setting(SETTING_SPEEDYINDEX_KEY, "k")
        tid = db.create_task("t", ["example.com"])
        db.create_donors_bulk(tid, ["https://ok.example/1"])
        db.update_donor(
            int(db.get_donors_for_task(tid)[0]["id"]),
            status="found",
            http_status=200,
        )
        self.window.send_task_to_index(tid, auto=False)
        mock_submit.assert_not_called()
        text = mock_warn.call_args.args[2].lower()
        self.assertIn("индекс", text)
        self.assertNotIn("автоотправка", text)

    @patch("gui.app.submit_urls")
    @patch("gui.app.ask_confirm", return_value=False)
    def test_manual_send_cancel_does_not_submit(self, _confirm, mock_submit):
        from gui.settings_dialog import SETTING_SPEEDYINDEX_KEY

        db.set_setting(SETTING_SPEEDYINDEX_KEY, "k")
        tid = db.create_task("t", ["example.com"])
        db.create_donors_bulk(tid, ["https://ok.example/1"])
        db.update_donor(
            int(db.get_donors_for_task(tid)[0]["id"]),
            status="found",
            http_status=200,
            google_indexed="not_indexed",
        )
        self.window.send_task_to_index(tid, auto=False)
        mock_submit.assert_not_called()

    @patch("gui.app.submit_urls")
    def test_finished_without_flag_does_not_submit(self, mock_submit):
        tid = db.create_task("t", ["example.com"])
        db.create_donors_bulk(tid, ["https://ok.example/1"])
        db.update_donor(
            int(db.get_donors_for_task(tid)[0]["id"]),
            status="found",
            http_status=200,
            google_indexed="not_indexed",
        )
        worker = _FakeWorker()
        self.window._workers[tid] = worker
        self.window._on_finished(tid, True, worker)
        mock_submit.assert_not_called()
