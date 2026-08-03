import unittest

from app.analysis.io import parse_optional_number, profile_posts_from_csv


class InputTests(unittest.TestCase):
    def test_portuguese_and_international_numbers(self):
        self.assertEqual(parse_optional_number("1.234,5"), 1234.5)
        self.assertEqual(parse_optional_number("42,5%"), 42.5)
        self.assertEqual(parse_optional_number("1,234"), 1234)

    def test_csv_parses_dates_and_booleans(self):
        csv_text = (
            "platform,format,post_id,published_at,captured_at,views,shares,is_paid\n"
            "instagram,reel,p1,2026-08-01T10:00:00-03:00,2026-08-02T10:00:00-03:00,1000,20,false\n"
        )
        rows = profile_posts_from_csv(csv_text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].age_hours, 24)
        self.assertFalse(rows[0].is_paid)


if __name__ == "__main__":
    unittest.main()
