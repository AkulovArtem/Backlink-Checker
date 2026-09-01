"""Live API checks. Skipped unless JSONSEO_KEY / SPEEDYINDEX_KEY are set."""

import os
import unittest
import uuid

from core.google_index import (
    PROVIDER_JSONSEO,
    IndexProvider,
    check_url_indexed,
    fetch_balance,
)
from core.speedyindex import fetch_balance as fetch_speedy_balance
from core.speedyindex import submit_urls

JSONSEO_KEY = os.environ.get("JSONSEO_KEY", "").strip()
SPEEDYINDEX_KEY = os.environ.get("SPEEDYINDEX_KEY", "").strip()


@unittest.skipUnless(JSONSEO_KEY, "JSONSEO_KEY is not set")
class LiveJsonSeoTest(unittest.TestCase):
    def test_balance_positive(self):
        result = fetch_balance(PROVIDER_JSONSEO, JSONSEO_KEY)
        self.assertTrue(result.ok, result.error)
        self.assertIsNotNone(result.amount)
        assert result.amount is not None
        self.assertGreater(result.amount, 0)

    def test_wikipedia_is_indexed(self):
        provider = IndexProvider(
            PROVIDER_JSONSEO,
            f"https://jsonseo.ru/api/google/xml?key={JSONSEO_KEY}",
        )
        result = check_url_indexed("https://www.wikipedia.org/", provider)
        err = (result.error or "").lower()
        if result.status == "error" and any(
            marker in err for marker in ("недоступен", "timeout", "timed out")
        ):
            self.skipTest(f"JSON SEO transient: {result.error}")
        self.assertEqual(result.status, "indexed", result.error)


@unittest.skipUnless(SPEEDYINDEX_KEY, "SPEEDYINDEX_KEY is not set")
class LiveSpeedyIndexTest(unittest.TestCase):
    def test_balance_positive(self):
        result = fetch_speedy_balance(SPEEDYINDEX_KEY)
        self.assertTrue(result.ok, result.error)
        self.assertIsNotNone(result.amount)
        assert result.amount is not None
        self.assertGreater(result.amount, 0)

    def test_create_indexer_task(self):
        balance = fetch_speedy_balance(SPEEDYINDEX_KEY)
        if not balance.ok or (balance.amount or 0) < 100:
            self.skipTest(
                f"Google indexer needs 100 tokens, balance is {balance.amount}"
            )
        url = f"https://example.com/backlink-checker-live-{uuid.uuid4().hex}"
        result = submit_urls(
            SPEEDYINDEX_KEY,
            [url],
            title="Backlink Checker live test",
        )
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.submitted, 1)
        self.assertTrue(result.task_id)


if __name__ == "__main__":
    unittest.main()
