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
