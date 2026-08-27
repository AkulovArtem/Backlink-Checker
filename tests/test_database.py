import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
