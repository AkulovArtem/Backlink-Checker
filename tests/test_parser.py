import unittest

from core.parser import parse_page


class ParseRelTypeTest(unittest.TestCase):
    def test_rel_nofollow_is_case_insensitive(self):
        html = (
            '<html><body>'
            '<a href="https://example.com/page" rel="NOFOLLOW">t</a>'
            '</body></html>'
        )
        parsed = parse_page(html, "https://donor.example/", ["example.com"])
        self.assertEqual(len(parsed["backlinks"]), 1)
        self.assertEqual(parsed["backlinks"][0].rel_type, "nofollow")

    def test_canonical_rel_is_case_insensitive(self):
        html = (
            '<html><head>'
            '<link rel="CANONICAL" href="https://ex.com/a">'
            '</head><body></body></html>'
        )
        parsed = parse_page(html, "https://donor.example/", ["example.com"])
        self.assertEqual(parsed["canonical_url"], "https://ex.com/a")

    def test_rel_sponsored_mixed_case(self):
        html = (
            '<html><body>'
            '<a href="https://example.com/page" rel="Sponsored nofollow">t</a>'
            '</body></html>'
        )
        parsed = parse_page(html, "https://donor.example/", ["example.com"])
        self.assertEqual(parsed["backlinks"][0].rel_type, "sponsored")


if __name__ == "__main__":
    unittest.main()
