import json
import unittest
from unittest.mock import patch

from core.google_index import BalanceResult
from core.speedyindex import (
    PROVIDER_SPEEDYINDEX,
    SPEEDYINDEX_MAX_URLS,
    eligible_index_submit_items,
    fetch_balance,
    format_balance_label,
    parse_balance_body,
    parse_create_response,
    submit_urls,
    unique_submit_urls,
)


class ParseSpeedyBalanceTest(unittest.TestCase):
    def test_indexer_credits(self):
        r = parse_balance_body(
            '{"code": 0, "balance": {"indexer": 10014495, "checker": 12}}'
        )
        self.assertTrue(r.ok)
        self.assertEqual(r.amount, 10014495)
        self.assertTrue(r.is_usable)

    def test_tokens_used_when_indexer_is_zero(self):
        r = parse_balance_body(
            '{"code": 0, "balance": {"tokens": 98, "indexer": 0, "checker": 0}}'
        )
        self.assertTrue(r.ok)
        self.assertEqual(r.amount, 98)
        self.assertTrue(r.is_usable)

    def test_zero_indexer_is_not_usable(self):
        r = parse_balance_body('{"code": 0, "balance": {"indexer": 0, "checker": 50}}')
        self.assertTrue(r.ok)
        self.assertEqual(r.amount, 0)
        self.assertFalse(r.is_usable)

    def test_error_code(self):
        r = parse_balance_body('{"code": 2, "error": "bad key"}')
        self.assertFalse(r.ok)
        self.assertIn("bad key", r.error)

    def test_format_empty_key(self):
        text = format_balance_label(None, empty_key=True)
        self.assertIn("API-ключ", text)

    def test_format_credits(self):
        text = format_balance_label(BalanceResult(True, 42), empty_key=False)
        self.assertIn("42", text)
        self.assertNotIn("₽", text)


class EligibleSubmitTest(unittest.TestCase):
    def _donor(self, **kwargs):
        row = {
            "id": 1,
            "url": "https://donor.example/page",
            "canonical_url": None,
            "http_status": 200,
            "status": "found",
            "google_indexed": "not_indexed",
            "index_submitted_at": None,
        }
        row.update(kwargs)
        return row

    def test_only_200_found_not_indexed(self):
        items = eligible_index_submit_items(
            [
                self._donor(id=1),
                self._donor(id=2, http_status=404, status="not_loaded"),
                self._donor(id=3, status="not_found"),
                self._donor(id=4, google_indexed="indexed"),
                self._donor(id=5, google_indexed="error"),
                self._donor(id=6, http_status=301),
            ]
        )
        self.assertEqual([i.donor_id for i in items], [1])
        self.assertEqual(items[0].url, "https://donor.example/page")

    def test_skips_already_submitted(self):
        items = eligible_index_submit_items(
            [self._donor(index_submitted_at="2026-01-01T00:00:00")]
        )
        self.assertEqual(items, [])

    def test_prefers_absolute_canonical(self):
        items = eligible_index_submit_items(
            [
                self._donor(
                    url="https://donor.example/page",
                    canonical_url="https://donor.example/canonical",
                )
            ]
        )
        self.assertEqual(items[0].url, "https://donor.example/canonical")

    def test_prefers_final_url_when_no_canonical(self):
        items = eligible_index_submit_items(
            [
                self._donor(
                    url="http://donor.example/page",
                    canonical_url=None,
                    final_url="https://www.donor.example/page",
                )
            ]
        )
        self.assertEqual(items[0].url, "https://www.donor.example/page")

    def test_skips_relative_canonical(self):
        items = eligible_index_submit_items(
            [self._donor(canonical_url="/canonical")]
        )
        self.assertEqual(items[0].url, "https://donor.example/page")

    def test_unique_submit_urls_keeps_all_donor_ids(self):
        items = eligible_index_submit_items(
            [
                self._donor(id=1, url="https://a.example/1"),
                self._donor(
                    id=2,
                    url="http://a.example/1",
                    canonical_url="https://a.example/1",
                ),
                self._donor(id=3, url="https://b.example/2"),
            ]
        )
        urls, donor_ids = unique_submit_urls(items)
        self.assertEqual(urls, ["https://a.example/1", "https://b.example/2"])
        self.assertEqual(donor_ids["https://a.example/1"], [1, 2])
        self.assertEqual(donor_ids["https://b.example/2"], [3])

    def test_unique_submit_urls_collapses_www_scheme_and_slash(self):
        items = eligible_index_submit_items(
            [
                self._donor(id=1, url="https://www.a.example/page/"),
                self._donor(id=2, url="http://a.example/page"),
            ]
        )
        urls, donor_ids = unique_submit_urls(items)
        self.assertEqual(len(urls), 1)
        self.assertEqual(sorted(donor_ids[urls[0]]), [1, 2])

    def test_unique_submit_urls_prefers_https(self):
        items = eligible_index_submit_items(
            [
                self._donor(id=1, url="http://a.example/page"),
                self._donor(id=2, url="https://a.example/page"),
            ]
        )
        urls, donor_ids = unique_submit_urls(items)
        self.assertEqual(urls, ["https://a.example/page"])
        self.assertEqual(sorted(donor_ids["https://a.example/page"]), [1, 2])


class ParseCreateResponseTest(unittest.TestCase):
    def test_success_task_id(self):
        r = parse_create_response('{"code": 0, "task_id": "abc"}', submitted=2)
        self.assertTrue(r.ok)
        self.assertEqual(r.task_id, "abc")
        self.assertEqual(r.submitted, 2)

    def test_success_nested_id(self):
        r = parse_create_response('{"code": 0, "id": "xyz"}', submitted=1)
        self.assertTrue(r.ok)
        self.assertEqual(r.task_id, "xyz")

    def test_insufficient_balance(self):
        r = parse_create_response(
            '{"code": 1, "message": "Insufficient token balance. Required: 100 tokens."}',
            submitted=1,
        )
        self.assertFalse(r.ok)
        self.assertIn("баланс", r.error.lower())
        self.assertIn("100", r.error)

    def test_validation_error(self):
        r = parse_create_response('{"code": 2, "error": "urls"}', submitted=1)
        self.assertFalse(r.ok)
        self.assertIn("urls", r.error)


class SubmitUrlsTest(unittest.TestCase):
    @patch("core.speedyindex._http_json")
    def test_posts_pay_per_indexed_google_indexer(self, mock_http):
        mock_http.return_value = '{"code": 0, "task_id": "t1"}'
        result = submit_urls("secret-key", ["https://a.example/1"], title="Job")
        self.assertTrue(result.ok)
        self.assertEqual(result.task_id, "t1")
        self.assertEqual(result.submitted, 1)
        args, kwargs = mock_http.call_args
        self.assertEqual(kwargs.get("method") or args[0], "POST")
        url = kwargs.get("url") or args[1]
        self.assertIn("/v2/task/google/indexer/create", url)
        headers = kwargs.get("headers") or args[2]
        self.assertEqual(headers["Authorization"], "secret-key")
        payload = json.loads(kwargs.get("body") or args[3])
        self.assertEqual(payload["urls"], ["https://a.example/1"])
        self.assertTrue(payload["pay_per_indexed"])
        self.assertEqual(payload["title"], "Job")

    @patch("core.speedyindex._http_json")
    def test_chunks_over_max(self, mock_http):
        mock_http.return_value = '{"code": 0, "task_id": "t1"}'
        urls = [f"https://ex.com/{i}" for i in range(SPEEDYINDEX_MAX_URLS + 2)]
        result = submit_urls("k", urls, title="big")
        self.assertTrue(result.ok)
        self.assertEqual(result.submitted, len(urls))
        self.assertEqual(mock_http.call_count, 2)

    def test_empty_list(self):
        result = submit_urls("k", [], title="x")
        self.assertTrue(result.ok)
        self.assertEqual(result.submitted, 0)
        self.assertEqual(result.task_id, "")

    @patch("core.speedyindex._http_json")
    def test_http_402_parses_json_body(self, mock_http):
        from io import BytesIO
        from urllib.error import HTTPError

        mock_http.side_effect = HTTPError(
            "https://api.speedyindex.com/v2/task/google/indexer/create",
            402,
            "Payment Required",
            hdrs=None,
            fp=BytesIO(
                b'{"code":1,"message":"Insufficient token balance. Required: 100 tokens."}'
            ),
        )
        result = submit_urls("k", ["https://a.example/1"], title="Job")
        self.assertFalse(result.ok)
        self.assertIn("100", result.error)

    def test_provider_constant(self):
        self.assertEqual(PROVIDER_SPEEDYINDEX, "speedyindex")


class FetchBalanceDispatchTest(unittest.TestCase):
    @patch("core.speedyindex._http_json", return_value='{"code":0,"balance":{"indexer":9,"checker":1}}')
    def test_fetch_balance_uses_account_endpoint(self, mock_http):
        r = fetch_balance("my-key")
        self.assertTrue(r.ok)
        self.assertEqual(r.amount, 9)
        url = mock_http.call_args.kwargs.get("url") or mock_http.call_args.args[1]
        self.assertIn("/v2/account", url)


if __name__ == "__main__":
    unittest.main()
