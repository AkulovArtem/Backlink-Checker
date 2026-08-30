import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel

from db import database as db
from gui.report_view import ReportView, matches_google_filter, matches_robots_filter


class ReportViewLoadTest(unittest.TestCase):
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

    def test_corrupt_target_domains_does_not_crash(self):
        tid = db.create_task("broken", ["example.com"])
        with db.get_connection() as conn:
            conn.execute(
                "UPDATE tasks SET target_domains = ? WHERE id = ?",
                ("{not-json", tid),
            )
        view = ReportView()
        view.load_task(tid)
        labels = view.findChildren(QLabel)
        self.assertTrue(any("повреждены" in (lbl.text() or "") for lbl in labels))

    def test_donor_status_card_includes_pending_queue(self):
        tid = db.create_task("p", ["example.com"])
        db.create_donors_bulk(
            tid,
            ["https://done.example/1", "https://wait.example/2"],
        )
        donors = db.get_donors_for_task(tid)
        db.update_donor(int(donors[0]["id"]), status="found")
        view = ReportView()
        view.load_task(tid)
        html = " ".join(lbl.text() for lbl in view.findChildren(QLabel))
        self.assertIn("СТАТУС ДОНОРОВ", html)
        self.assertIn("■ В очереди", html)
        self.assertIn("<b>1</b>", html)

    def test_pending_status_badge_uses_six_digit_hex(self):
        tid = db.create_task("p", ["example.com"])
        view = ReportView()
        view.load_task(tid)
        sheets = [
            lbl.styleSheet()
            for lbl in view.findChildren(QLabel)
            if "В очереди" in (lbl.text() or "")
        ]
        self.assertTrue(sheets)
        self.assertIn("#888888", sheets[0])
        self.assertNotIn("#88818", sheets[0])

    def test_google_index_card_counts_yes_no_error_and_skip(self):
        tid = db.create_task("idx", ["example.com"], check_google_index=True)
        db.create_donors_bulk(
            tid,
            [
                "https://a.example/1",
                "https://b.example/2",
                "https://c.example/3",
                "https://d.example/4",
            ],
        )
        donors = db.get_donors_for_task(tid)
        db.update_donor(int(donors[0]["id"]), status="found", google_indexed="indexed")
        db.update_donor(int(donors[1]["id"]), status="found", google_indexed="not_indexed")
        db.update_donor(
            int(donors[2]["id"]),
            status="found",
            google_indexed="error",
            google_index_error="110",
        )
        view = ReportView()
        view.load_task(tid)
        html = " ".join(lbl.text() for lbl in view.findChildren(QLabel))
        self.assertIn("В ИНДЕКСЕ GOOGLE", html)
        self.assertIn("Не проверялось", html)
        self.assertIn("<b>1</b>", html)

    def _task_with_google_states(self) -> int:
        tid = db.create_task("gfilter", ["example.com"], check_google_index=True)
        db.create_donors_bulk(
            tid,
            [
                "https://yes.example/1",
                "https://no.example/2",
                "https://err.example/3",
                "https://skip.example/4",
            ],
        )
        donors = db.get_donors_for_task(tid)
        db.update_donor(int(donors[0]["id"]), status="found", google_indexed="indexed")
        db.update_donor(int(donors[1]["id"]), status="found", google_indexed="not_indexed")
        db.update_donor(
            int(donors[2]["id"]),
            status="found",
            google_indexed="error",
            google_index_error="110",
        )
        return tid

    def test_google_filter_buttons_exist_next_to_robots(self):
        view = ReportView()
        view.load_task(self._task_with_google_states())
        btns = getattr(view, "_google_btns", {})
        self.assertEqual(
            set(btns),
            {"all", "indexed", "not_indexed", "error", "unchecked"},
        )
        self.assertTrue(btns["all"].isChecked())

    def test_google_filter_indexed_shows_only_yes_rows(self):
        view = ReportView()
        view.load_task(self._task_with_google_states())
        self.assertEqual(view._donor_table.rowCount(), 4)
        btns = getattr(view, "_google_btns", {})
        self.assertIn("indexed", btns)
        btns["indexed"].click()
        self.assertEqual(view._donor_table.rowCount(), 1)
        self.assertEqual(view._donor_table.item(0, 2).text(), "Да")

    def test_google_filter_unchecked_shows_dash_rows(self):
        view = ReportView()
        view.load_task(self._task_with_google_states())
        btns = getattr(view, "_google_btns", {})
        self.assertIn("unchecked", btns)
        btns["unchecked"].click()
        self.assertEqual(view._donor_table.rowCount(), 1)
        self.assertEqual(view._donor_table.item(0, 2).text(), "—")

    def test_google_filter_survives_report_refresh(self):
        view = ReportView()
        view.load_task(self._task_with_google_states())
        view._google_btns["indexed"].click()
        view.refresh()
        self.assertTrue(view._google_btns["indexed"].isChecked())
        self.assertEqual(view._donor_table.rowCount(), 1)
        self.assertEqual(view._donor_table.item(0, 2).text(), "Да")

    def test_google_filter_resets_when_opening_another_task(self):
        tid1 = self._task_with_google_states()
        tid2 = db.create_task("other", ["other.com"])
        db.create_donors_bulk(tid2, ["https://other.example/1"])
        view = ReportView()
        view.load_task(tid1)
        view._google_btns["indexed"].click()
        view._donor_search.setText("yes.example")
        view.load_task(tid2)
        self.assertEqual(view._donor_filter_google, "all")
        self.assertTrue(view._google_btns["all"].isChecked())
        self.assertEqual(view._donor_search.text(), "")
        self.assertEqual(view._donor_table.rowCount(), 1)

    def test_robots_filter_has_unchecked_and_hides_open_closed(self):
        tid = db.create_task("robots", ["example.com"])
        db.create_donors_bulk(
            tid,
            ["https://open.example/1", "https://skip.example/2"],
        )
        donors = db.get_donors_for_task(tid)
        db.update_donor(int(donors[0]["id"]), status="found", index_google="open")
        view = ReportView()
        view.load_task(tid)
        btns = getattr(view, "_index_btns", {})
        self.assertIn("unchecked", btns)
        btns["unchecked"].click()
        self.assertEqual(view._donor_table.rowCount(), 1)
        self.assertEqual(view._donor_table.item(0, 1).text(), "—")

    def test_donor_row_stores_html_snippet_for_menu(self):
        tid = db.create_task("html", ["example.com"])
        db.create_donors_bulk(tid, ["https://a.example/1"])
        donor = db.get_donors_for_task(tid)[0]
        db.update_donor(int(donor["id"]), html_snippet="<p>page</p>")
        view = ReportView()
        view.load_task(tid)
        item = view._donor_table.item(0, 4)
        self.assertIsNotNone(item)
        self.assertEqual(item.data(Qt.ItemDataRole.UserRole + 1), "<p>page</p>")

    def test_status_filter_pending_shows_only_queue(self):
        tid = db.create_task("st", ["example.com"])
        db.create_donors_bulk(
            tid,
            ["https://done.example/1", "https://wait.example/2"],
        )
        donors = db.get_donors_for_task(tid)
        db.update_donor(int(donors[0]["id"]), status="found")
        view = ReportView()
        view.load_task(tid)
        btns = getattr(view, "_status_btns", {})
        self.assertIn("pending", btns)
        btns["pending"].click()
        self.assertEqual(view._donor_table.rowCount(), 1)
        url_widget = view._donor_table.cellWidget(0, 0)
        self.assertIn("wait.example", url_widget.text() if url_widget else "")

    def test_google_filter_survives_se_tab_switch(self):
        view = ReportView()
        view.load_task(self._task_with_google_states())
        getattr(view, "_google_btns", {})["error"].click()
        self.assertEqual(view._donor_table.rowCount(), 1)
        view._switch_se("yandex")
        self.assertEqual(view._donor_table.rowCount(), 1)
        self.assertEqual(view._donor_table.item(0, 2).text(), "Ошибка")


class MatchesGoogleFilterTest(unittest.TestCase):
    def test_all_keeps_every_value(self):
        for value in ("indexed", "not_indexed", "error", None, ""):
            self.assertTrue(matches_google_filter(value, "all"))

    def test_indexed_only(self):
        self.assertTrue(matches_google_filter("indexed", "indexed"))
        self.assertFalse(matches_google_filter("not_indexed", "indexed"))
        self.assertFalse(matches_google_filter(None, "indexed"))

    def test_unchecked_treats_empty_as_skip(self):
        self.assertTrue(matches_google_filter(None, "unchecked"))
        self.assertTrue(matches_google_filter("", "unchecked"))
        self.assertFalse(matches_google_filter("error", "unchecked"))


class MatchesRobotsFilterTest(unittest.TestCase):
    def test_all_keeps_every_value(self):
        for value in ("open", "closed", None, ""):
            self.assertTrue(matches_robots_filter(value, "all"))

    def test_open_only(self):
        self.assertTrue(matches_robots_filter("open", "open"))
        self.assertFalse(matches_robots_filter("closed", "open"))
        self.assertFalse(matches_robots_filter(None, "open"))

    def test_unchecked_treats_empty_as_skip(self):
        self.assertTrue(matches_robots_filter(None, "unchecked"))
        self.assertTrue(matches_robots_filter("", "unchecked"))
        self.assertFalse(matches_robots_filter("open", "unchecked"))


if __name__ == "__main__":
    unittest.main()
