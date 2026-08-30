import unittest

from core.google_index import (
    PROVIDER_RIVER,
    PROVIDER_STOCK,
    BalanceResult,
    IndexProvider,
    build_index_request_url,
    canonical_search_endpoint,
    index_url_for_check,
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


class ParseUserKeyTest(unittest.TestCase):
    def test_full_url(self):
        url = "http://xmlriver.com/search/xml?user=12&key=abc&groupby=10"
        self.assertEqual(parse_user_key(url), ("12", "abc"))

    def test_query_only(self):
        self.assertEqual(parse_user_key("user=9&key=zz"), ("9", "zz"))

    def test_missing(self):
        self.assertIsNone(parse_user_key(""))
        self.assertIsNone(parse_user_key("http://xmlriver.com/search/xml"))


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

    def test_none_amount_has_explicit_notice(self):
        p, notices = pick_provider(
            "http://xmlriver.com/search/xml?user=1&key=a",
            BalanceResult(True, None),
            "",
            None,
        )
        self.assertIsNone(p)
        self.assertTrue(any("прочитать сумму" in n for n in notices))


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
        self.assertEqual(site_query_target("https://www.wikipedia.org/"), "www.wikipedia.org")

    def test_canonical_stock_path(self):
        ep = canonical_search_endpoint(
            PROVIDER_STOCK, "https://xmlstock.com/?user=1&key=a"
        )
        self.assertIn("/google/xml/", ep)


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


if __name__ == "__main__":
    unittest.main()
