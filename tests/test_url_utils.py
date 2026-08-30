import unittest

from utils.url_utils import parse_donor_lines


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


if __name__ == "__main__":
    unittest.main()
