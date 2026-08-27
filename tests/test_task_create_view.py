import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from gui.task_create_view import TaskCreateView  # noqa: E402

_TASK = {
    "id": 7,
    "name": "Проверка example.com",
    "target_domains": '["example.com", "shop.example.com"]',
    "user_agent": "desktop_chrome",
    "custom_user_agent": None,
    "threads": 8,
    "timeout": 45,
}


class TaskCreateAppendModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

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

    def test_reset_returns_to_create_mode(self):
        view = TaskCreateView()
        view.enter_append_mode(_TASK, existing_count=12)
        view.reset()

        self.assertIsNone(view._edit_task_id)
        self.assertEqual(view._heading_lbl.text(), "Создать задание")
        self.assertEqual(view._submit_btn.text(), "Создать")
        self.assertFalse(view._targets_edit.isReadOnly())
        self.assertTrue(view._existing_lbl.isHidden())


if __name__ == "__main__":
    unittest.main()
