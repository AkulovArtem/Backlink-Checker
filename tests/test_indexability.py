import unittest

from bs4 import BeautifulSoup

from core.indexability import check_indexability


def _check(html: str, headers: dict | None = None):
    return check_indexability(BeautifulSoup(html, "lxml"), headers or {})


class IndexabilityTest(unittest.TestCase):
    def test_open_by_default(self):
        self.assertEqual(_check("<p>x</p>").google, "open")

    def test_meta_noindex(self):
        self.assertEqual(_check('<meta name="robots" content="noindex">').google, "closed")

    def test_second_robots_meta_does_not_hide_noindex(self):
        r = _check(
            '<meta name="robots" content="noindex">'
            '<meta name="robots" content="max-image-preview:large">'
        )
        self.assertEqual(r.google, "closed")
        self.assertIn("noindex", r.meta_robots)

    def test_meta_none_means_noindex(self):
        self.assertEqual(_check('<meta name="robots" content="none">').google, "closed")

    def test_header_none_means_noindex(self):
        r = _check("", {"X-Robots-Tag": "none"})
        self.assertEqual(r.google, "closed")

    def test_bot_specific_meta(self):
        r = _check('<meta name="yandexbot" content="noindex">')
        self.assertEqual(r.yandex, "closed")
        self.assertEqual(r.google, "open")


if __name__ == "__main__":
    unittest.main()
