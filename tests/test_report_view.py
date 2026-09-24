import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QAbstractItemModel, QEvent, QSortFilterProxyModel, Qt
from PyQt6.QtWidgets import QApplication, QLabel

from db import database as db
from gui.report_view import (
    COL_D_GOOGLE,
    COL_D_INT,
    COL_D_ROBOTS,
    COL_D_URL,
    DonorTableModel,
    ReportView,
    _badge,
    matches_google_filter,
    matches_robots_filter,
)


def _set_filter(view: ReportView, key: str, value: str) -> None:
    combo = view._filter_combos[key]
    combo.setCurrentIndex(combo.findData(value))


def _rows(view: ReportView) -> int:
    return view._donor_proxy.rowCount()


def _cell(view: ReportView, row: int, col: int) -> str:
    return view._donor_proxy.index(row, col).data()


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
        self.assertIn("Статус доноров", html)
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
        self.assertIn("В индексе Google", html)
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

    def test_google_filter_offers_every_state(self):
        view = ReportView()
        view.load_task(self._task_with_google_states())
        combo = view._filter_combos["google"]
        values = {combo.itemData(i) for i in range(combo.count())}
        self.assertEqual(values, {"all", "indexed", "not_indexed", "error", "unchecked"})
        self.assertEqual(combo.currentData(), "all")
        self.assertTrue(view._reset_filters_btn.isHidden())

    def test_google_filter_indexed_shows_only_yes_rows(self):
        view = ReportView()
        view.load_task(self._task_with_google_states())
        self.assertEqual(_rows(view), 4)
        _set_filter(view, "google", "indexed")
        self.assertEqual(_rows(view), 1)
        self.assertEqual(_cell(view, 0, COL_D_GOOGLE), "Да")
        self.assertFalse(view._reset_filters_btn.isHidden())

    def test_google_filter_unchecked_shows_dash_rows(self):
        view = ReportView()
        view.load_task(self._task_with_google_states())
        _set_filter(view, "google", "unchecked")
        self.assertEqual(_rows(view), 1)
        self.assertEqual(_cell(view, 0, COL_D_GOOGLE), "—")

    def test_reset_clears_every_filter(self):
        view = ReportView()
        view.load_task(self._task_with_google_states())
        _set_filter(view, "google", "indexed")
        _set_filter(view, "status", "found")
        view._reset_filters_btn.click()
        self.assertEqual(view._donor_filter_google, "all")
        self.assertEqual(view._filter_combos["status"].currentData(), "all")
        self.assertEqual(_rows(view), 4)

    def test_google_filter_survives_report_refresh(self):
        view = ReportView()
        view.load_task(self._task_with_google_states())
        _set_filter(view, "google", "indexed")
        view.refresh()
        self.assertEqual(view._filter_combos["google"].currentData(), "indexed")
        self.assertEqual(_rows(view), 1)
        self.assertEqual(_cell(view, 0, COL_D_GOOGLE), "Да")

    def test_google_filter_resets_when_opening_another_task(self):
        tid1 = self._task_with_google_states()
        tid2 = db.create_task("other", ["other.com"])
        db.create_donors_bulk(tid2, ["https://other.example/1"])
        view = ReportView()
        view.load_task(tid1)
        _set_filter(view, "google", "indexed")
        view._donor_search.setText("yes.example")
        view.load_task(tid2)
        self.assertEqual(view._donor_filter_google, "all")
        self.assertEqual(view._filter_combos["google"].currentData(), "all")
        self.assertEqual(view._donor_search.text(), "")
        self.assertEqual(_rows(view), 1)

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
        _set_filter(view, "index", "unchecked")
        self.assertEqual(_rows(view), 1)
        self.assertEqual(_cell(view, 0, COL_D_ROBOTS), "—")

    def test_donor_row_stores_html_snippet_for_menu(self):
        tid = db.create_task("html", ["example.com"])
        db.create_donors_bulk(tid, ["https://a.example/1"])
        donor = db.get_donors_for_task(tid)[0]
        db.update_donor(int(donor["id"]), html_snippet="<p>page</p>")
        view = ReportView()
        view.load_task(tid)
        donor = view._donor_at(view._donor_proxy.index(0, COL_D_URL))
        self.assertIsNotNone(donor)
        self.assertEqual(donor["html_snippet"], "<p>page</p>")

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
        _set_filter(view, "status", "pending")
        self.assertEqual(_rows(view), 1)
        self.assertIn("wait.example", _cell(view, 0, COL_D_URL))

    def test_google_filter_survives_se_tab_switch(self):
        view = ReportView()
        view.load_task(self._task_with_google_states())
        _set_filter(view, "google", "error")
        self.assertEqual(_rows(view), 1)
        view._switch_se("yandex")
        self.assertEqual(_rows(view), 1)
        self.assertEqual(_cell(view, 0, COL_D_GOOGLE), "Ошибка")
        header = view._donor_proxy.headerData(COL_D_ROBOTS, Qt.Orientation.Horizontal)
        self.assertEqual(header, "Robots (Яндекс)")
        self.assertTrue(view._se_btns["yandex"].isChecked())
        self.assertFalse(view._se_btns["google"].isChecked())

    def _big_task(self) -> int:
        tid = db.create_task("big", ["example.com"])
        db.create_donors_bulk(tid, [f"https://d{i}.example/p" for i in range(300)])
        with db.get_connection() as conn:
            conn.execute(
                "UPDATE donors SET status = 'found', internal_links = id % 97 WHERE task_id = ?",
                (tid,),
            )
        return tid

    def test_refresh_does_not_leak_donor_models(self):
        view = ReportView()
        view.load_task(self._big_task())
        for _ in range(3):
            view.refresh()
        # Run the deleteLater() of the replaced widgets, as the event loop would.
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        models = [
            m for m in view.findChildren(QAbstractItemModel)
            if isinstance(m, (DonorTableModel, QSortFilterProxyModel))
        ]
        self.assertEqual(len(models), 2)

    def test_refresh_keeps_donor_sort_and_scroll(self):
        view = ReportView()
        view.resize(1200, 800)
        view.show()
        view.load_task(self._big_task())
        view._data_tabs.setCurrentIndex(1)
        self._app.processEvents()
        view._donor_view.sortByColumn(COL_D_INT, Qt.SortOrder.DescendingOrder)
        view._donor_view.verticalScrollBar().setValue(40)
        self._app.processEvents()
        view.refresh()
        self._app.processEvents()
        header = view._donor_view.horizontalHeader()
        self.assertEqual(header.sortIndicatorSection(), COL_D_INT)
        self.assertEqual(header.sortIndicatorOrder(), Qt.SortOrder.DescendingOrder)
        self.assertEqual(view._donor_view.verticalScrollBar().value(), 40)
        view.close()

    def test_opening_another_task_resets_sort(self):
        view = ReportView()
        view.load_task(self._big_task())
        view._donor_view.sortByColumn(COL_D_INT, Qt.SortOrder.DescendingOrder)
        view.load_task(db.create_task("other", ["example.com"]))
        self.assertEqual(view._donor_view.horizontalHeader().sortIndicatorSection(), -1)

    def test_actions_menu_includes_send_to_index(self):
        tid = db.create_task("idx", ["example.com"])
        view = ReportView()
        view.load_task(tid)
        labels = [act.text() for act in view._actions_menu().actions() if act.text()]
        self.assertIn("Отправить на индексацию", labels)


class BadgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_fill_is_a_light_tint_of_the_text_colour(self):
        # "#ffa72618" is ARGB to Qt — it used to paint the badge dark red.
        sheet = _badge("В процессе", "#ffa726").styleSheet()
        self.assertIn("rgba(255, 167, 38, 36)", sheet)
        self.assertIn("color: #ffa726", sheet)

    def test_text_is_plain(self):
        self.assertEqual(_badge("<b>x</b>", "#888888").textFormat(), Qt.TextFormat.PlainText)


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
