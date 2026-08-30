import unittest

from core.google_index import (
    PROVIDER_RIVER,
    PROVIDER_STOCK,
    BalanceResult,
    IndexProvider,
    build_index_request_url,
    canonical_search_endpoint,
    parse_balance_body,
    parse_index_xml,
    parse_user_key,
    pick_provider,
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
        url = build_index_request_url(p, "https://ex.com/x")
        self.assertIn("site%3A", url)
        self.assertIn("nfpr=1", url)

    def test_canonical_stock_path(self):
        ep = canonical_search_endpoint(
            PROVIDER_STOCK, "https://xmlstock.com/?user=1&key=a"
        )
        self.assertIn("/google/xml/", ep)


class UrlMatchTest(unittest.TestCase):
    def test_match(self):
        self.assertTrue(
            urls_match("https://www.A.com/p/", "http://a.com/p")
        )
        self.assertFalse(urls_match("https://a.com/p", "https://a.com/q"))


if __name__ == "__main__":
    unittest.main()
