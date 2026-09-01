import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

from core.google_index import (
    PROVIDER_JSONSEO,
    PROVIDER_RIVER,
    PROVIDER_STOCK,
    BalanceResult,
    IndexProvider,
    build_index_request_url,
    canonical_search_endpoint,
    check_url_indexed,
    extract_api_key,
    index_url_for_check,
    needs_balance_fetch,
    parse_balance_body,
    parse_index_xml,
    parse_user_key,
    pick_provider,
    site_query_target,
    urls_match,
)

INDEXED_XML = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0">
  <response>
    <found priority="all">1</found>
    <results>
      <grouping>
        <group>
          <doc>
            <url>https://www.Example.com/Page</url>
          </doc>
        </group>
      </grouping>
    </results>
  </response>
</yandexsearch>
"""

NOT_INDEXED_XML = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0">
  <response date="20120928T103130">
    <error code="15">Искомая комбинация слов нигде не встречается</error>
  </response>
</yandexsearch>
"""

AUTH_ERROR_XML = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0">
  <response>
    <error code="42">Ключ содержит ошибку</error>
  </response>
</yandexsearch>
"""

ZERO_FOUND_XML = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0">
  <response>
    <found priority="all">0</found>
    <results><grouping/></results>
  </response>
</yandexsearch>
"""

FOUND_100_NO_DOCS_XML = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0">
  <response>
    <found priority="all">100</found>
    <results><grouping></grouping></results>
  </response>
</yandexsearch>
"""

SITELINK_ONLY_XML = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0">
  <response>
    <found priority="all">1</found>
    <results>
      <grouping>
        <group>
          <doc>
            <url>https://other.com/</url>
            <sitelinks>
              <sitelink><url>https://example.com/page</url></sitelink>
            </sitelinks>
          </doc>
        </group>
      </grouping>
    </results>
  </response>
</yandexsearch>
"""

RETRYABLE_500_XML = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0">
  <response><error code="500">Выполните перезапрос.</error></response>
</yandexsearch>
"""

UNAVAILABLE_XML = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0">
  <response>
    <error>Сервис временно недоступен. Пожалуйста, повторите попытку позже.</error>
  </response>
</yandexsearch>
"""


class ParseUserKeyTest(unittest.TestCase):
    def test_full_url(self):
        url = "http://xmlriver.com/search/xml?user=12&key=abc&groupby=10"
        self.assertEqual(parse_user_key(url), ("12", "abc"))

    def test_query_only(self):
        self.assertEqual(parse_user_key("user=9&key=zz"), ("9", "zz"))

    def test_missing(self):
        self.assertIsNone(parse_user_key(""))
        self.assertIsNone(parse_user_key("http://xmlriver.com/search/xml"))


class ExtractApiKeyTest(unittest.TestCase):
    def test_raw_key(self):
        self.assertEqual(extract_api_key("rawKeyValue123"), "rawKeyValue123")

    def test_key_from_url(self):
        self.assertEqual(
            extract_api_key("https://jsonseo.ru/api/google/xml?key=abc123&groupby=10"),
            "abc123",
        )

    def test_empty(self):
        self.assertEqual(extract_api_key(""), "")
        self.assertEqual(extract_api_key("   "), "")


class ParseBalanceTest(unittest.TestCase):
    def test_plain_number(self):
        r = parse_balance_body("15.50")
        self.assertTrue(r.ok)
        self.assertEqual(r.amount, 15.5)
        self.assertTrue(r.is_usable)

    def test_zero(self):
        r = parse_balance_body("0")
        self.assertTrue(r.ok)
        self.assertEqual(r.amount, 0.0)
        self.assertFalse(r.is_usable)

    def test_json(self):
        r = parse_balance_body('{"balance": "120,00"}')
        self.assertTrue(r.ok)
        self.assertEqual(r.amount, 120.0)

    def test_error_text(self):
        r = parse_balance_body("ERROR: bad key")
        self.assertFalse(r.ok)

    def test_xmlstock_json_uses_balance_not_limits(self):
        r = parse_balance_body(
            '{"limits":0,"outgo-day":0,"balance":498.97,"days":0}'
        )
        self.assertTrue(r.ok)
        self.assertEqual(r.amount, 498.97)

    def test_json_without_balance_is_not_zero(self):
        r = parse_balance_body('{"error":0,"user_id":83774240,"queries":50}')
        self.assertFalse(r.ok)
        self.assertIsNone(r.amount)

    def test_html_error_page_is_not_a_balance(self):
        r = parse_balance_body("<html><body>error 404</body></html>")
        self.assertFalse(r.ok)
        self.assertIsNone(r.amount)


class ParseIndexXmlTest(unittest.TestCase):
    def test_indexed_ignores_www_and_case(self):
        r = parse_index_xml(INDEXED_XML, "https://example.com/page")
        self.assertEqual(r.status, "indexed")

    def test_error_15_is_not_indexed(self):
        r = parse_index_xml(NOT_INDEXED_XML, "https://example.com/page")
        self.assertEqual(r.status, "not_indexed")

    def test_auth_error(self):
        r = parse_index_xml(AUTH_ERROR_XML, "https://example.com/page")
        self.assertEqual(r.status, "error")
        self.assertIn("Ключ", r.error)

    def test_zero_found(self):
        r = parse_index_xml(ZERO_FOUND_XML, "https://example.com/page")
        self.assertEqual(r.status, "not_indexed")

    def test_found_100_without_docs_is_not_indexed(self):
        r = parse_index_xml(FOUND_100_NO_DOCS_XML, "https://example.com/page")
        self.assertEqual(r.status, "not_indexed")

    def test_sitelink_is_not_organic_hit(self):
        r = parse_index_xml(SITELINK_ONLY_XML, "https://example.com/page")
        self.assertEqual(r.status, "not_indexed")

    def test_error_500_is_retryable(self):
        r = parse_index_xml(RETRYABLE_500_XML, "https://example.com/page")
        self.assertEqual(r.status, "error")
        self.assertTrue(r.retryable)

    def test_temporarily_unavailable_is_retryable(self):
        r = parse_index_xml(UNAVAILABLE_XML, "https://example.com/page")
        self.assertEqual(r.status, "error")
        self.assertTrue(r.retryable)


class PickProviderTest(unittest.TestCase):
    def test_prefers_river_with_balance(self):
        p, notices = pick_provider(
            "http://xmlriver.com/search/xml?user=1&key=a",
            BalanceResult(True, 10),
            "https://xmlstock.com/google/xml/?user=2&key=b",
            BalanceResult(True, 50),
        )
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.name, PROVIDER_RIVER)
        self.assertEqual(notices, [])

    def test_falls_back_to_stock_when_river_empty(self):
        p, notices = pick_provider(
            "http://xmlriver.com/search/xml?user=1&key=a",
            BalanceResult(True, 0),
            "https://xmlstock.com/google/xml/?user=2&key=b",
            BalanceResult(True, 3.5),
        )
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.name, PROVIDER_STOCK)
        self.assertTrue(any("0 ₽" in n for n in notices))

    def test_both_zero(self):
        p, notices = pick_provider(
            "http://xmlriver.com/search/xml?user=1&key=a",
            BalanceResult(True, 0),
            "https://xmlstock.com/google/xml/?user=2&key=b",
            BalanceResult(True, 0),
        )
        self.assertIsNone(p)
        self.assertTrue(any("нулевым балансом" in n for n in notices))

    def test_preferred_stock_even_when_river_has_money(self):
        p, notices = pick_provider(
            "http://xmlriver.com/search/xml?user=1&key=a",
            BalanceResult(True, 10),
            "https://xmlstock.com/google/xml/?user=2&key=b",
            BalanceResult(True, 50),
            preferred=PROVIDER_STOCK,
        )
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.name, PROVIDER_STOCK)
        self.assertEqual(notices, [])

    def test_preferred_river_does_not_fall_back_to_stock(self):
        p, notices = pick_provider(
            "http://xmlriver.com/search/xml?user=1&key=a",
            BalanceResult(True, 0),
            "https://xmlstock.com/google/xml/?user=2&key=b",
            BalanceResult(True, 50),
            preferred=PROVIDER_RIVER,
        )
        self.assertIsNone(p)
        self.assertTrue(any("Выбран XMLRiver" in n for n in notices))

    def test_none_amount_has_explicit_notice(self):
        p, notices = pick_provider(
            "http://xmlriver.com/search/xml?user=1&key=a",
            BalanceResult(True, None),
            "",
            None,
        )
        self.assertIsNone(p)
        self.assertTrue(any("прочитать сумму" in n for n in notices))

    def test_preferred_jsonseo_with_balance(self):
        p, notices = pick_provider(
            "http://xmlriver.com/search/xml?user=1&key=a",
            BalanceResult(True, 10),
            "https://xmlstock.com/google/xml/?user=2&key=b",
            BalanceResult(True, 50),
            preferred=PROVIDER_JSONSEO,
            jsonseo_key="abc",
            jsonseo_balance=BalanceResult(True, 12.5),
        )
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.name, PROVIDER_JSONSEO)
        self.assertIn("jsonseo.ru", p.endpoint)
        self.assertIn("key=abc", p.endpoint)
        self.assertEqual(notices, [])

    def test_preferred_jsonseo_does_not_fall_back_to_river(self):
        p, notices = pick_provider(
            "http://xmlriver.com/search/xml?user=1&key=a",
            BalanceResult(True, 10),
            "",
            None,
            preferred=PROVIDER_JSONSEO,
            jsonseo_key="",
            jsonseo_balance=None,
        )
        self.assertIsNone(p)
        self.assertTrue(any("JSON SEO" in n for n in notices))

    def test_empty_preferred_does_not_auto_pick_jsonseo(self):
        p, notices = pick_provider(
            "",
            None,
            "",
            None,
            jsonseo_key="abc",
            jsonseo_balance=BalanceResult(True, 10),
        )
        self.assertIsNone(p)
        self.assertTrue(any("XMLRiver" in n or "XMLStock" in n for n in notices))


class NeedsBalanceFetchTest(unittest.TestCase):
    def test_preferred_stock_skips_river(self):
        self.assertFalse(needs_balance_fetch(PROVIDER_RIVER, PROVIDER_STOCK))
        self.assertTrue(needs_balance_fetch(PROVIDER_STOCK, PROVIDER_STOCK))

    def test_preferred_river_skips_stock(self):
        self.assertTrue(needs_balance_fetch(PROVIDER_RIVER, PROVIDER_RIVER))
        self.assertFalse(needs_balance_fetch(PROVIDER_STOCK, PROVIDER_RIVER))

    def test_empty_preferred_fetches_both(self):
        self.assertTrue(needs_balance_fetch(PROVIDER_RIVER, ""))
        self.assertTrue(needs_balance_fetch(PROVIDER_STOCK, ""))
        self.assertTrue(needs_balance_fetch(PROVIDER_RIVER, None))

    def test_preferred_jsonseo_skips_river_and_stock(self):
        self.assertFalse(needs_balance_fetch(PROVIDER_RIVER, PROVIDER_JSONSEO))
        self.assertFalse(needs_balance_fetch(PROVIDER_STOCK, PROVIDER_JSONSEO))
        self.assertTrue(needs_balance_fetch(PROVIDER_JSONSEO, PROVIDER_JSONSEO))

    def test_preferred_river_skips_jsonseo(self):
        self.assertFalse(needs_balance_fetch(PROVIDER_JSONSEO, PROVIDER_RIVER))


class RequestUrlTest(unittest.TestCase):
    def test_river_inindex(self):
        p = IndexProvider(
            PROVIDER_RIVER,
            "http://xmlriver.com/search/xml?user=1&key=a",
        )
        url = build_index_request_url(p, "https://ex.com/x")
        self.assertIn("inindex=1", url)
        self.assertIn("strict=1", url)
        self.assertIn("query=", url)
        self.assertIn("groupby=10", url)

    def test_stock_site_query(self):
        p = IndexProvider(
            PROVIDER_STOCK,
            "https://xmlstock.com/google/xml/?user=1&key=a",
        )
        url = build_index_request_url(p, "https://ex.com/x?id=1")
        self.assertIn("site%3A", url)
        self.assertNotIn("https%3A", url.split("query=")[1])
        self.assertIn("id%3D1", url)
        self.assertIn("nfpr=1", url)
        self.assertIn("groupby=10", url)
        self.assertEqual(site_query_target("https://www.wikipedia.org/"), "www.wikipedia.org")

    def test_groupby_10_overrides_account_top100(self):
        p = IndexProvider(
            PROVIDER_RIVER,
            "http://xmlriver.com/search/xml?user=1&key=a&groupby=100",
        )
        url = build_index_request_url(p, "https://ex.com/x")
        self.assertIn("groupby=10", url)
        self.assertNotIn("groupby=100", url)

    def test_canonical_stock_path(self):
        ep = canonical_search_endpoint(
            PROVIDER_STOCK, "https://xmlstock.com/?user=1&key=a"
        )
        self.assertIn("/google/xml/", ep)

    def test_jsonseo_site_query(self):
        p = IndexProvider(
            PROVIDER_JSONSEO,
            "https://jsonseo.ru/api/google/xml?key=abc",
        )
        url = build_index_request_url(p, "https://ex.com/x?id=1")
        self.assertIn("site%3A", url)
        self.assertNotIn("https%3A", url.split("query=")[1])
        self.assertIn("nfpr=1", url)
        self.assertIn("groupby=10", url)
        self.assertIn("key=abc", url)
        self.assertNotIn("inindex=", url)

    def test_canonical_jsonseo_from_raw_key(self):
        ep = canonical_search_endpoint(PROVIDER_JSONSEO, "abc123")
        self.assertEqual(ep, "https://jsonseo.ru/api/google/xml?key=abc123")


class IndexUrlForCheckTest(unittest.TestCase):
    def test_prefers_absolute_canonical(self):
        self.assertEqual(
            index_url_for_check(
                "https://ex.com/a",
                "https://www.ex.com/a/",
                "https://ex.com/a/",
            ),
            "https://ex.com/a/",
        )

    def test_skips_relative_canonical(self):
        self.assertEqual(
            index_url_for_check(
                "https://ex.com/a",
                "https://www.ex.com/a/",
                "/a/",
            ),
            "https://www.ex.com/a/",
        )

    def test_falls_back_to_original(self):
        self.assertEqual(
            index_url_for_check("https://ex.com/a", "", None),
            "https://ex.com/a",
        )


class UrlMatchTest(unittest.TestCase):
    def test_match(self):
        self.assertTrue(
            urls_match("https://www.A.com/p/", "http://a.com/p")
        )
        self.assertFalse(urls_match("https://a.com/p", "https://a.com/q"))

    def test_query_string_is_significant(self):
        self.assertTrue(
            urls_match("https://ex.com/p?id=1", "http://www.ex.com/p?id=1")
        )
        self.assertFalse(
            urls_match("https://ex.com/p?id=1", "https://ex.com/p")
        )
        self.assertTrue(
            urls_match("https://ex.com/p?b=2&a=1", "https://ex.com/p?a=1&b=2")
        )

    def test_fragment_is_ignored(self):
        self.assertTrue(
            urls_match("https://ex.com/p#top", "https://ex.com/p")
        )

    def test_site_query_keeps_query_drops_scheme_and_slash(self):
        self.assertEqual(
            site_query_target("https://ex.com/p?id=1"),
            "ex.com/p?id=1",
        )
        self.assertEqual(
            site_query_target("https://ex.com/foo/"),
            "ex.com/foo",
        )


class CheckUrlIndexedHttpTest(unittest.TestCase):
    @patch("core.google_index._http_get")
    def test_http_403_is_not_retried(self, mock_get):
        mock_get.side_effect = HTTPError(
            "https://jsonseo.ru/api/google/xml",
            403,
            "Forbidden",
            hdrs={},
            fp=BytesIO(b""),
        )
        provider = IndexProvider(
            PROVIDER_JSONSEO, "https://jsonseo.ru/api/google/xml?key=a"
        )
        result = check_url_indexed("https://ex.com/", provider)
        self.assertEqual(result.status, "error")
        self.assertFalse(result.retryable)
        self.assertEqual(mock_get.call_count, 1)

    @patch("core.google_index.time.sleep")
    @patch("core.google_index._http_get")
    def test_http_429_is_retried(self, mock_get, _sleep):
        mock_get.side_effect = HTTPError(
            "https://jsonseo.ru/api/google/xml",
            429,
            "Too Many Requests",
            hdrs={},
            fp=BytesIO(b""),
        )
        provider = IndexProvider(
            PROVIDER_JSONSEO, "https://jsonseo.ru/api/google/xml?key=a"
        )
        result = check_url_indexed("https://ex.com/", provider)
        self.assertEqual(result.status, "error")
        self.assertTrue(result.retryable)
        self.assertEqual(mock_get.call_count, 3)


if __name__ == "__main__":
    unittest.main()
