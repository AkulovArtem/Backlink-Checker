import unittest

from core.models import ANCHOR_TEXT_MAX
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

    def test_page_level_robots_none_makes_links_nofollow(self):
        html = (
            '<html><head><meta name="robots" content="none"></head><body>'
            '<a href="https://example.com/page">t</a>'
            '</body></html>'
        )
        parsed = parse_page(html, "https://donor.example/", ["example.com"])
        self.assertEqual(parsed["backlinks"][0].rel_type, "nofollow")

    def test_page_level_nofollow_is_a_whole_directive(self):
        html = (
            '<html><head><meta name="robots" content="index, follow"></head><body>'
            '<a href="https://example.com/page">t</a>'
            '</body></html>'
        )
        parsed = parse_page(html, "https://donor.example/", ["example.com"])
        self.assertEqual(parsed["backlinks"][0].rel_type, "dofollow")


class AnchorTextTest(unittest.TestCase):
    def _anchor(self, inner: str) -> str:
        html = f'<a href="https://example.com/">{inner}</a>'
        return parse_page(html, "https://donor.example/", ["example.com"])["backlinks"][0].anchor_text

    def test_words_around_nested_tags_keep_their_spaces(self):
        self.assertEqual(self._anchor("купить <b>слона</b> недорого"), "купить слона недорого")

    def test_line_break_and_blocks_separate_words(self):
        self.assertEqual(self._anchor("строка1<br>строка2"), "строка1 строка2")
        self.assertEqual(self._anchor("<div>Заголовок</div><div>Описание</div>"), "Заголовок Описание")

    def test_whitespace_is_collapsed_so_equal_anchors_group(self):
        self.assertEqual(self._anchor("  много   пробелов\n и перенос "), "много пробелов и перенос")

    def test_inline_tags_without_space_stay_joined(self):
        # Rendered as one word by the browser.
        self.assertEqual(self._anchor("<span>Back</span><span>link</span>"), "Backlink")

    def test_comments_and_scripts_are_not_anchor_text(self):
        self.assertEqual(self._anchor("текст<!-- скрыто --><script>var x;</script>"), "текст")

    def test_image_alt_when_no_text(self):
        html = '<a href="https://example.com/"> <img src="x" alt=" Лого "> </a>'
        bl = parse_page(html, "https://donor.example/", ["example.com"])["backlinks"][0]
        self.assertEqual((bl.anchor_text, bl.anchor_type), ("Лого", "image"))

    def test_huge_anchor_is_clipped(self):
        anchor = self._anchor("слово " * 5000)
        self.assertLessEqual(len(anchor), ANCHOR_TEXT_MAX)
        self.assertTrue(anchor.endswith("…"))

    def test_title_whitespace_is_collapsed(self):
        html = "<title>\n  Страница\n  — Сайт </title>"
        self.assertEqual(parse_page(html, "https://d.example/", [])["title"], "Страница — Сайт")


class ParseTargetMatchTest(unittest.TestCase):
    def test_link_with_explicit_port_matches_target(self):
        html = '<a href="https://Example.com:443/x">a</a>'
        parsed = parse_page(html, "https://donor.example/", ["example.com"])
        self.assertEqual(len(parsed["backlinks"]), 1)

    def test_non_http_links_are_not_counted(self):
        html = (
            '<a href="MAILTO:a@example.com">m</a>'
            '<a href="JavaScript:void(0)">j</a>'
            '<a href="Tel:+100">t</a>'
            '<a href="https://other.example/">o</a>'
            '<a href="/local">l</a>'
        )
        parsed = parse_page(html, "https://donor.example/", ["example.com"])
        self.assertEqual(parsed["external_links"], 1)
        self.assertEqual(parsed["internal_links"], 1)
        self.assertEqual(parsed["backlinks"], [])

    def test_cyrillic_target_matches_punycode_link(self):
        html = '<a href="http://xn--e1afmkfd.xn--p1ai/x">a</a><a href="https://пример.рф/">b</a>'
        for target in ("пример.рф", "xn--e1afmkfd.xn--p1ai"):
            parsed = parse_page(html, "https://donor.example/", [target])
            self.assertEqual(len(parsed["backlinks"]), 2, target)

    def test_malformed_href_does_not_break_page(self):
        html = '<a href="http://[bad">x</a><a href="https://example.com/">y</a>'
        parsed = parse_page(html, "https://donor.example/", ["example.com"])
        self.assertEqual(len(parsed["backlinks"]), 1)


if __name__ == "__main__":
    unittest.main()
