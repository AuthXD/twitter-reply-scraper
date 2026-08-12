import unittest
from reply_pipeline.scoring import score, bucket, meets_min

CFG = {"scoring": {"question_bonus": 2, "engagement_ge_5": 1, "engagement_ge_50": 1,
                   "high_cutoff": 6, "med_cutoff": 3}}


class TestScoring(unittest.TestCase):
    def test_question_and_engagement(self):
        s = score(5, "how do you find these?", 10, CFG)  # 5 +2 (?) +1 (>=5)
        self.assertEqual(s, 8)
        self.assertEqual(bucket(s, CFG), "HIGH")

    def test_low(self):
        s = score(3, "next one soon", 0, CFG)  # 3 -> MED
        self.assertEqual(bucket(s, CFG), "MED")
        s2 = score(2, "too late", 0, CFG)  # 2 -> LOW
        self.assertEqual(bucket(s2, CFG), "LOW")

    def test_meets_min(self):
        self.assertTrue(meets_min("HIGH", "MED"))
        self.assertFalse(meets_min("LOW", "MED"))

    def test_meets_min_is_case_insensitive(self):
        # config.yaml may say `export_min_intent: "med"` — that must not explode.
        self.assertTrue(meets_min("high", "med"))

    def test_meets_min_treats_unknown_intent_as_lowest(self):
        # A NULL/garbage intent column must not raise KeyError mid-export.
        self.assertFalse(meets_min(None, "MED"))
        self.assertFalse(meets_min("WAT", "MED"))

    def test_meets_min_with_unknown_floor_keeps_everything(self):
        self.assertTrue(meets_min("LOW", "???"))


if __name__ == "__main__":
    unittest.main()
