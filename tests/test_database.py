import json
import tempfile
import unittest
from pathlib import Path

from core.models import HTML_SNIPPET_MAX, clip_html_snippet
from db import database as db


class AddDonorsToTaskTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_path = db.DB_PATH
        db.DB_PATH = Path(self._tmp.name) / "test.db"
        db.init_db()
        self.task_id = db.create_task("t", ["example.com"])
        db.create_donors_bulk(
            self.task_id,
            ["https://a.example/1", "https://b.example/2"],
        )

    def tearDown(self):
        db.DB_PATH = self._old_path
        self._tmp.cleanup()

    def test_inserts_only_new_urls(self):
        result = db.add_donors_to_task(
            self.task_id,
            [
                "https://b.example/2",
                "https://c.example/3",
                "https://c.example/3",
            ],
        )
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["skipped_dup"], 2)
        self.assertEqual(result["skipped_cap"], 0)
        self.assertEqual(result["urls"], ["https://c.example/3"])
        self.assertEqual(db.count_task_donors(self.task_id), 3)

    def test_leaves_existing_donor_status_intact(self):
        donors = db.get_donors_for_task(self.task_id)
        db.update_donor(int(donors[0]["id"]), status="found")
        db.add_donors_to_task(self.task_id, ["https://c.example/3"])
        refreshed = {
            d["url"]: d["status"] for d in db.get_donors_for_task(self.task_id)
        }
        self.assertEqual(refreshed["https://a.example/1"], "found")
        self.assertEqual(refreshed["https://b.example/2"], "pending")
        self.assertEqual(refreshed["https://c.example/3"], "pending")

    def test_pending_query_returns_only_unchecked(self):
        donors = db.get_donors_for_task(self.task_id)
        db.update_donor(int(donors[0]["id"]), status="found")
        db.add_donors_to_task(self.task_id, ["https://c.example/3"])
        pending_urls = [d["url"] for d in db.get_pending_donors_for_task(self.task_id)]
        self.assertEqual(pending_urls, ["https://b.example/2", "https://c.example/3"])

    def test_enforces_max_total_cap(self):
        result = db.add_donors_to_task(
            self.task_id,
            ["https://c.example/3", "https://d.example/4", "https://e.example/5"],
            max_total=3,
        )
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["skipped_cap"], 2)
        self.assertEqual(result["urls"], ["https://c.example/3"])
        self.assertEqual(db.count_task_donors(self.task_id), 3)

    def test_all_duplicates_adds_nothing(self):
        result = db.add_donors_to_task(
            self.task_id,
            ["https://a.example/1", "https://b.example/2"],
        )
        self.assertEqual(result["added"], 0)
        self.assertEqual(result["skipped_dup"], 2)
        self.assertEqual(db.count_task_donors(self.task_id), 2)

    def test_update_task_fields_changes_name_and_threads(self):
        db.update_task_fields(self.task_id, name="renamed", threads=8)
        task = db.get_task(self.task_id)
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task["name"], "renamed")
        self.assertEqual(task["threads"], 8)

    def test_update_task_fields_rejects_unknown_column(self):
        with self.assertRaises(ValueError):
            db.update_task_fields(self.task_id, status="completed")

    def test_google_index_columns(self):
        tid = db.create_task("idx", ["example.com"], check_google_index=True)
        task = db.get_task(tid)
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task["check_google_index"], 1)
        db.create_donors_bulk(tid, ["https://a.example/1"])
        donor = db.get_donors_for_task(tid)[0]
        db.update_donor(int(donor["id"]), google_indexed="indexed")
        refreshed = db.get_donors_for_task(tid)[0]
        self.assertEqual(refreshed["google_indexed"], "indexed")

    def test_html_snippet_roundtrip(self):
        donors = db.get_donors_for_task(self.task_id)
        db.update_donor(int(donors[0]["id"]), html_snippet="<p>hi</p>")
        refreshed = db.get_donors_for_task(self.task_id)[0]
        self.assertEqual(refreshed["html_snippet"], "<p>hi</p>")

    def test_format_task_created_treats_naive_sqlite_time_as_utc(self):
        from datetime import datetime, timezone

        utc = datetime(2026, 1, 1, 21, 0, 0, tzinfo=timezone.utc)
        expected = utc.astimezone().strftime("%d.%m.%Y %H:%M")
        self.assertEqual(
            db.format_task_created("2026-01-01 21:00:00"),
            expected,
        )

    def test_parse_target_domains_rejects_non_list(self):
        self.assertEqual(db.parse_target_domains('["example.com"]'), ["example.com"])
        with self.assertRaises(TypeError):
            db.parse_target_domains('"example.com"')
        with self.assertRaises(json.JSONDecodeError):
            db.parse_target_domains("{not-json")

    def test_clip_html_snippet_truncates(self):
        self.assertEqual(clip_html_snippet("abc"), "abc")
        self.assertEqual(clip_html_snippet(None), "")
        long = "x" * (HTML_SNIPPET_MAX + 20)
        self.assertEqual(len(clip_html_snippet(long)), HTML_SNIPPET_MAX)


if __name__ == "__main__":
    unittest.main()
