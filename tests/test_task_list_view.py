import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QApplication

from db import database as db
from gui import task_list_view
from gui.task_list_view import TaskListView


class DateToFollowsTodayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_path = db.DB_PATH
        db.DB_PATH = Path(self._tmp.name) / "test.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._old_path
        self._tmp.cleanup()

    def test_new_day_task_stays_visible_after_midnight(self):
        yesterday = QDate.currentDate().addDays(-1)
        with patch.object(task_list_view, "_today", return_value=yesterday):
            view = TaskListView()
        self.assertEqual(view._date_to.date(), yesterday)

        # The app stayed open past midnight; a task is created "today".
        db.create_task("after midnight", ["example.com"])
        view.refresh()

        self.assertEqual(view._date_to.date(), QDate.currentDate())
        self.assertEqual(view._proxy.rowCount(), 1)

    def test_user_chosen_end_date_is_kept(self):
        view = TaskListView()
        picked = QDate.currentDate().addDays(-10)
        view._date_to.setDate(picked)
        view.refresh()
        self.assertEqual(view._date_to.date(), picked)


if __name__ == "__main__":
    unittest.main()
