import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QPushButton

from core.google_index import BalanceResult
from db import database as db
from gui.confirm import make_confirm_dialog
from gui.settings_dialog import (
    SETTING_RIVER_URL,
    SETTING_STOCK_URL,
    SettingsDialog,
)
from gui.task_create_view import TaskCreateView
from utils.url_utils import MAX_DONORS, MAX_TARGETS

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

    def test_append_mode_keeps_existing_urls_empty_and_unlocks_targets(self):
        view = TaskCreateView()
        view.enter_append_mode(_TASK, existing_count=12)

        self.assertEqual(view._edit_task_id, 7)
        self.assertEqual(view._heading_lbl.text(), "Добавить ссылки")
        self.assertEqual(view._submit_btn.text(), "Добавить и проверить")
        self.assertEqual(view._name_edit.text(), "Проверка example.com")
        self.assertFalse(view._targets_edit.isReadOnly())
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

    def test_append_saves_new_acceptors_without_donors_or_recheck(self):
        tid = db.create_task("t", ["example.com"])
        db.create_donors_bulk(tid, ["https://a.example/1"])
        db.update_donor(int(db.get_donors_for_task(tid)[0]["id"]), status="found")
        task = db.get_task(tid)
        view = TaskCreateView()
        fake = _FakeApp()
        view.set_app(fake)
        view.enter_append_mode(task, existing_count=1)
        view._targets_edit.setPlainText("example.com\nnew.com")
        view._submit()
        saved = db.parse_target_domains(db.get_task(tid)["target_domains"])
        self.assertEqual(saved, ["example.com", "new.com"])
        self.assertEqual(fake.started, [])
        self.assertEqual(fake.reports, [tid])
        self.assertEqual(db.get_donors_for_task(tid)[0]["status"], "found")

    def test_append_caps_acceptors_at_max_targets(self):
        tid = db.create_task("t", ["example.com"])
        task = db.get_task(tid)
        view = TaskCreateView()
        view.set_app(_FakeApp())
        view.enter_append_mode(task, existing_count=0)
        view._targets_edit.setPlainText(
            "\n".join(f"d{i}.example" for i in range(MAX_TARGETS + 5))
        )
        view._submit()
        self.assertFalse(view._warn_lbl.isHidden())
        self.assertIn(str(MAX_TARGETS), view._warn_lbl.text())
        view._submit()
        saved = db.parse_target_domains(db.get_task(tid)["target_domains"])
        self.assertEqual(len(saved), MAX_TARGETS)

    def test_append_errors_when_new_acceptor_exceeds_cap(self):
        domains = [f"d{i}.example" for i in range(MAX_TARGETS)]
        tid = db.create_task("t", domains)
        task = db.get_task(tid)
        view = TaskCreateView()
        view.set_app(_FakeApp())
        view.enter_append_mode(task, existing_count=0)
        view._targets_edit.setPlainText("\n".join(domains + ["new.example"]))
        view._submit()
        saved = db.parse_target_domains(db.get_task(tid)["target_domains"])
        self.assertEqual(saved, domains)
        self.assertFalse(view._error_lbl.isHidden())
        self.assertIn(str(MAX_TARGETS), view._error_lbl.text())

    def test_append_errors_when_nothing_new(self):
        tid = db.create_task("t", ["example.com"])
        task = db.get_task(tid)
        view = TaskCreateView()
        view.set_app(_FakeApp())
        view.enter_append_mode(task, existing_count=1)
        view._submit()
        self.assertFalse(view._error_lbl.isHidden())
        self.assertIn("донор", view._error_lbl.text().lower())

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


class _FakeApp:
    def __init__(self):
        self.started: list[int] = []
        self.reports: list[int] = []

    def start_task(self, task_id: int):
        self.started.append(task_id)

    def show_report(self, task_id: int):
        self.reports.append(task_id)

    def show_list(self):
        pass


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

    def test_dialog_buttons_are_russian_cancel_then_save(self):
        dlg = SettingsDialog()
        self.assertEqual(dlg._cancel_btn.text(), "Отмена")
        self.assertEqual(dlg._save_btn.text(), "Сохранить")
        self.assertEqual(dlg._wipe_btn.text(), "Очистить базу")
        row = dlg._button_row
        widgets = [
            row.itemAt(i).widget()
            for i in range(row.count())
            if row.itemAt(i).widget() is not None
        ]
        self.assertEqual(
            [w.text() for w in widgets if isinstance(w, QPushButton)],
            ["Очистить базу", "Отмена", "Сохранить"],
        )
        dlg.close()

    def test_confirm_dialog_cancel_then_ok(self):
        dlg = make_confirm_dialog(
            None, "Удалить", "Точно?", ok_label="Да", cancel_label="Отмена"
        )
        self.assertEqual(dlg._cancel_btn.text(), "Отмена")
        self.assertEqual(dlg._ok_btn.text(), "Да")
        row = dlg._button_row
        texts = [
            row.itemAt(i).widget().text()
            for i in range(row.count())
            if row.itemAt(i).widget() is not None
        ]
        self.assertEqual(texts, ["Отмена", "Да"])
        dlg.close()


if __name__ == "__main__":
    unittest.main()
