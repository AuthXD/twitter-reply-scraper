"""Pure helpers extracted from the browser adapter so the scroll-stop and
permalink-selection logic can be tested without driving Chromium."""
import unittest
from reply_pipeline.scroll import ScrollTracker, pick_permalink, parse_metric


class TestScrollTracker(unittest.TestCase):
    def test_keeps_going_while_new_items_appear(self):
        t = ScrollTracker(max_stalls=2)
        self.assertFalse(t.record(5))
        self.assertFalse(t.record(12))
        self.assertFalse(t.record(20))

    def test_stops_after_consecutive_stalled_rounds(self):
        t = ScrollTracker(max_stalls=2)
        t.record(10)
        self.assertFalse(t.record(10), "one stalled round is not enough to stop")
        self.assertTrue(t.record(10), "two stalled rounds means the feed is exhausted")

    def test_growth_resets_the_stall_counter(self):
        t = ScrollTracker(max_stalls=2)
        t.record(10)
        t.record(10)          # stall 1
        self.assertFalse(t.record(14))   # growth -> reset
        self.assertFalse(t.record(14))   # stall 1 again
        self.assertTrue(t.record(14))    # stall 2 -> stop


class TestPickPermalink(unittest.TestCase):
    def test_prefers_the_link_wrapping_the_timestamp(self):
        # A quote-tweet article lists the quoted post's permalink first.
        candidates = [("/quoted_author/status/111", False),
                      ("/real_author/status/222", True)]
        self.assertEqual(pick_permalink(candidates), ("222", "real_author"))

    def test_falls_back_to_first_status_link(self):
        candidates = [("/only_author/status/333", False)]
        self.assertEqual(pick_permalink(candidates), ("333", "only_author"))

    def test_ignores_non_status_links(self):
        candidates = [("/i/web/hashtag/foo", False), ("/a/status/444", True)]
        self.assertEqual(pick_permalink(candidates), ("444", "a"))

    def test_no_candidates_yields_nones(self):
        self.assertEqual(pick_permalink([]), (None, None))


class TestParseMetric(unittest.TestCase):
    def test_plain_count(self):
        self.assertEqual(parse_metric("12 replies. Reply"), 12)

    def test_thousands_suffix(self):
        self.assertEqual(parse_metric("1.2K likes. Like"), 1200)

    def test_millions_suffix(self):
        self.assertEqual(parse_metric("3M views"), 3_000_000)

    def test_comma_separated(self):
        self.assertEqual(parse_metric("1,234 replies"), 1234)

    def test_missing_label(self):
        self.assertEqual(parse_metric(None), 0)


if __name__ == "__main__":
    unittest.main()
