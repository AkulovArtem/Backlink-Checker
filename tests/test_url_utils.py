import unittest

from utils.url_utils import (
    decode_donor_file,
    get_domain,
    normalize_domain,
    parse_donor_lines,
    same_page,
)


class ParseDonorLinesTest(unittest.TestCase):
    def test_keeps_unique_http_urls_in_order(self):
        text = (
            "https://a.example/1\n"
            "http://b.example/2\n"
            "https://a.example/1\n"
            "  https://c.example/3  \n"
        )
        valid, invalid = parse_donor_lines(text)
        self.assertEqual(
            valid,
            [
                "https://a.example/1",
                "http://b.example/2",
                "https://c.example/3",
            ],
        )
        self.assertEqual(invalid, 0)

    def test_counts_lines_without_scheme(self):
        text = "example.com/page\nhttps://ok.example/\nftp://nope.example/\n"
        valid, invalid = parse_donor_lines(text)
        self.assertEqual(valid, ["https://ok.example/"])
        self.assertEqual(invalid, 2)

    def test_does_not_drop_urls_over_limit(self):
        """Caller must see the extras so it can warn instead of silently truncating."""
        text = "\n".join(f"https://example.com/{i}" for i in range(5))
        valid, invalid = parse_donor_lines(text)
        self.assertEqual(len(valid), 5)
        self.assertEqual(invalid, 0)

    def test_empty_and_blank_lines(self):
        valid, invalid = parse_donor_lines("\n  \n\n")
        self.assertEqual(valid, [])
        self.assertEqual(invalid, 0)


class DecodeDonorFileTest(unittest.TestCase):
    TEXT = "https://a.example/1\r\nhttps://пример.рф/страница\r\n"

    def _urls(self, data: bytes) -> list[str]:
        valid, invalid = parse_donor_lines(decode_donor_file(data))
        self.assertEqual(invalid, 0)
        return valid

    def test_utf8_with_and_without_bom(self):
        expected = ["https://a.example/1", "https://пример.рф/страница"]
        self.assertEqual(self._urls(self.TEXT.encode("utf-8")), expected)
        self.assertEqual(self._urls(self.TEXT.encode("utf-8-sig")), expected)

    def test_utf16_notepad_unicode(self):
        self.assertEqual(len(self._urls(self.TEXT.encode("utf-16"))), 2)

    def test_windows_1251(self):
        self.assertEqual(
            self._urls(self.TEXT.encode("cp1251"))[1], "https://пример.рф/страница"
        )


class SamePageTest(unittest.TestCase):
    def test_browser_normalisation_is_not_a_redirect(self):
        self.assertTrue(same_page("https://site.ru", "https://site.ru/"))
        self.assertTrue(same_page(
            "https://site.ru/статья?q=тест",
            "https://site.ru/%D1%81%D1%82%D0%B0%D1%82%D1%8C%D1%8F?q=%D1%82%D0%B5%D1%81%D1%82",
        ))
        self.assertTrue(same_page("https://Пример.рф/", "https://xn--e1afmkfd.xn--p1ai/"))
        self.assertTrue(same_page("HTTPS://SITE.ru/x#top", "https://site.ru/x"))

    def test_real_redirects_are_kept(self):
        self.assertFalse(same_page("http://site.ru/", "https://site.ru/"))
        self.assertFalse(same_page("https://site.ru/", "https://www.site.ru/"))
        self.assertFalse(same_page("https://site.ru/old", "https://site.ru/new"))
        self.assertFalse(same_page("https://site.ru/Page", "https://site.ru/page"))


class NormalizeDomainTest(unittest.TestCase):
    def test_strips_scheme_www_and_path(self):
        self.assertEqual(
            normalize_domain("https://www.Example.com/blog/page?x=1"),
            "example.com",
        )
        self.assertEqual(normalize_domain("example.com/blog"), "example.com")
        self.assertEqual(normalize_domain("shop.example.com"), "shop.example.com")

    def test_strips_port_and_trailing_dot(self):
        self.assertEqual(normalize_domain("example.com:8080"), "example.com")
        self.assertEqual(normalize_domain("https://www.example.com./"), "example.com")


class GetDomainTest(unittest.TestCase):
    def test_ignores_port_userinfo_and_trailing_dot(self):
        self.assertEqual(get_domain("https://Example.com:443/x"), "example.com")
        self.assertEqual(get_domain("http://user:pw@www.example.com/"), "example.com")
        self.assertEqual(get_domain("http://example.com./"), "example.com")

    def test_idn_and_punycode_are_the_same_host(self):
        self.assertEqual(
            get_domain("http://xn--e1afmkfd.xn--p1ai/x"), get_domain("https://Пример.рф/")
        )
        self.assertEqual(normalize_domain("пример.рф"), normalize_domain("xn--e1afmkfd.xn--p1ai"))

    def test_invalid_or_relative(self):
        self.assertEqual(get_domain("/relative/path"), "")
        self.assertEqual(get_domain("http://[::1"), "")


if __name__ == "__main__":
    unittest.main()
