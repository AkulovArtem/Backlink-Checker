import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from core.google_index import BalanceResult, PROVIDER_RIVER  # noqa: E402
from db import database as db  # noqa: E402
from gui.settings_dialog import SettingsDialog  # noqa: E402


class SettingsDialogCloseTest(unittest.TestCase):
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

    def test_refresh_after_close_does_not_start_worker(self):
        dlg = SettingsDialog()
        dlg._closed = True
        before = dlg._workers.get(PROVIDER_RIVER)
        dlg._river_edit.setText("http://xmlriver.com/search/xml?user=1&key=a")
        dlg._refresh_balance(PROVIDER_RIVER)
        after = dlg._workers.get(PROVIDER_RIVER)
        self.assertIs(after, before)
        dlg.close()

    @patch(
        "gui.settings_dialog.fetch_balance",
        return_value=BalanceResult(ok=False, error="x"),
    )
    def test_second_refresh_detaches_previous_worker(self, _mock):
        dlg = SettingsDialog()
        dlg._river_edit.setText("http://xmlriver.com/search/xml?user=1&key=a")
        dlg._refresh_balance(PROVIDER_RIVER)
        first = dlg._workers[PROVIDER_RIVER]
        dlg._refresh_balance(PROVIDER_RIVER)
        second = dlg._workers[PROVIDER_RIVER]
        self.assertIsNot(first, second)
        self.assertIsNone(first.parent())
        first.wait(2000)
        dlg.close()
        second.wait(2000)


if __name__ == "__main__":
    unittest.main()
