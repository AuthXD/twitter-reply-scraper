import unittest
from reply_pipeline.filters import classify, passes_retail
from reply_pipeline.models import Reply

THEMES = [
    {"name": "Looking for early calls", "weight": 5,
     "phrases": ["how do you find these", "find coins early", "how to find early"]},
    {"name": "Missed opportunities", "weight": 4,
     "phrases": ["missed another", "missed the pump"]},
]


class TestFilters(unittest.TestCase):
    def test_substring_match(self):
        hit = classify("how do you find these gems?", THEMES, 82)
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "Looking for early calls")

    def test_fuzzy_typo(self):
        hit = classify("missd anethr 10x", THEMES, 78)  # typo of 'missed another'
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "Missed opportunities")

    def test_no_match(self):
        self.assertIsNone(classify("gm ser wagmi", THEMES, 82))

    def test_highest_weight_wins(self):
        hit = classify("how to find early and i missed another", THEMES, 82)
        self.assertEqual(hit[1], 5)

    def test_retail_bounds(self):
        base = dict(reply_id="x", author_handle="a", text="t", caller="c")
        r_mega = Reply(author_followers=500000, **base)
        r_bot = Reply(author_followers=3, **base)
        r_ok = Reply(author_followers=800, **base)
        retail = {"follower_min": 25, "follower_max": 60000, "max_age_days": 0}
        self.assertFalse(passes_retail(r_mega, retail))
        self.assertFalse(passes_retail(r_bot, retail))
        self.assertTrue(passes_retail(r_ok, retail))

    def test_unknown_followers_pass_by_default(self):
        # The browser adapters cannot see follower counts; default is to keep.
        r = Reply(reply_id="x", author_handle="a", text="t", caller="c",
                  author_followers=None)
        retail = {"follower_min": 25, "follower_max": 60000, "max_age_days": 0}
        self.assertTrue(passes_retail(r, retail))

    def test_unknown_followers_dropped_when_required(self):
        r = Reply(reply_id="x", author_handle="a", text="t", caller="c",
                  author_followers=None)
        retail = {"follower_min": 25, "follower_max": 60000, "max_age_days": 0,
                  "require_followers": True}
        self.assertFalse(passes_retail(r, retail))


if __name__ == "__main__":
    unittest.main()
