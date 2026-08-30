import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialogButtonBox

from core.google_index import BalanceResult
from db import database as db
from gui.settings_dialog import (
    SETTING_RIVER_URL,
    SETTING_STOCK_URL,
    SettingsDialog,
)
from gui.task_create_view import TaskCreateView
from utils.url_utils import MAX_DONORS

_TASK = {
    "id": 7,
    "name": "Проверка example.com",
    "target_domains": '["example.com", "shop.example.com"]',
    "user_agent": "desktop_chrome",
    "custom_user_agent": None,
    "threads": 8,
    "timeout": 45,
    "check_google_index": 1,
    "index_provider": "xmlstock",
}


class TaskCreateAppendModeTest(unittest.TestCase):
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

    def test_append_mode_locks_targets_and_does_not_dump_old_urls(self):
        view = TaskCreateView()
        view.enter_append_mode(_TASK, existing_count=12)

        self.assertEqual(view._edit_task_id, 7)
        self.assertEqual(view._heading_lbl.text(), "Добавить ссылки")
        self.assertEqual(view._submit_btn.text(), "Добавить и проверить")
        self.assertEqual(view._name_edit.text(), "Проверка example.com")
        self.assertTrue(view._targets_edit.isReadOnly())
        self.assertIn("example.com", view._targets_edit.toPlainText())
        self.assertEqual(view._donors_edit.toPlainText(), "")
        self.assertFalse(view._existing_lbl.isHidden())
        self.assertIn("12", view._existing_lbl.text())
        self.assertEqual(view._threads_spin.value(), 8)
        self.assertEqual(view._timeout_spin.value(), 45)
        self.assertTrue(view._index_check.isChecked())
        self.assertTrue(view._stock_radio.isChecked())
        self.assertFalse(view._provider_box.isHidden())

    def test_append_mode_tolerates_corrupt_target_domains(self):
        view = TaskCreateView()
        broken = dict(_TASK)
        broken["target_domains"] = "{not-json"
        view.enter_append_mode(broken, existing_count=1)
        self.assertEqual(view._edit_task_id, 7)
        self.assertEqual(view._targets_edit.toPlainText(), "")

    def test_append_warns_when_over_remaining_cap(self):
        view = TaskCreateView()
        view.enter_append_mode(_TASK, existing_count=MAX_DONORS - 1)
        view._donors_edit.setPlainText("https://a.example/1\nhttps://b.example/2")
        view._submit()
        self.assertFalse(view._warn_lbl.isHidden())
        self.assertIn("лимит", view._warn_lbl.text())
        self.assertTrue(view._skip_confirmed)

    @patch("gui.task_create_view.MAX_DONORS", 2)
    def test_create_warns_when_over_global_cap(self):
        view = TaskCreateView()
        view._donors_edit.setPlainText(
            "https://a.example/1\nhttps://b.example/2\nhttps://c.example/3"
        )
        view._targets_edit.setPlainText("example.com")
        view._submit()
        self.assertFalse(view._warn_lbl.isHidden())
        self.assertIn("лимит", view._warn_lbl.text())
        self.assertTrue(view._skip_confirmed)

    def test_reset_returns_to_create_mode(self):
        view = TaskCreateView()
        view.enter_append_mode(_TASK, existing_count=12)
        view.reset()

        self.assertIsNone(view._edit_task_id)
        self.assertEqual(view._heading_lbl.text(), "Создать задание")
        self.assertEqual(view._submit_btn.text(), "Создать")
        self.assertFalse(view._targets_edit.isReadOnly())
        self.assertTrue(view._existing_lbl.isHidden())
        self.assertFalse(view._index_check.isChecked())
        self.assertTrue(view._provider_box.isHidden())
        self.assertTrue(view._river_radio.isChecked())

    @patch(
        "gui.settings_dialog.fetch_balance",
        return_value=BalanceResult(ok=True, amount=10),
    )
    def test_index_check_selects_stock_when_only_stock_url_configured(self, _mock):
        db.set_setting(SETTING_STOCK_URL, "https://xmlstock.com/google/xml/?user=1&key=a")
        view = TaskCreateView()
        view._index_check.setChecked(True)
        self.assertTrue(view._stock_radio.isChecked())
        for worker in list(view._balance_workers.values()):
            worker.wait(2000)

    @patch(
        "gui.settings_dialog.fetch_balance",
        return_value=BalanceResult(ok=True, amount=10),
    )
    def test_append_keeps_saved_stock_when_both_urls_exist(self, _mock):
        db.set_setting(SETTING_RIVER_URL, "http://xmlriver.com/search/xml?user=1&key=a")
        db.set_setting(SETTING_STOCK_URL, "https://xmlstock.com/google/xml/?user=2&key=b")
        view = TaskCreateView()
        view.enter_append_mode(_TASK, existing_count=1)
        self.assertTrue(view._stock_radio.isChecked())
        for worker in list(view._balance_workers.values()):
            worker.wait(2000)


class SettingsButtonsTest(unittest.TestCase):
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

    def test_dialog_buttons_are_russian(self):
        dlg = SettingsDialog()
        box = dlg.findChild(QDialogButtonBox)
        self.assertIsNotNone(box)
        save_btn = box.button(QDialogButtonBox.StandardButton.Save)
        cancel_btn = box.button(QDialogButtonBox.StandardButton.Cancel)
        self.assertEqual(save_btn.text(), "Сохранить")
        self.assertEqual(cancel_btn.text(), "Отмена")
        dlg.close()


if __name__ == "__main__":
    unittest.main()
