"""Tests for the standalone twscrape scraper at the repo root.

x_scraper imports its config at module scope, so a stub is installed before the
import. Run from the repo root:  python -m unittest discover -s tests -v
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _install_stub_config():
    mod = types.ModuleType("scraper_config")
    mod.CALLERS = ["BigCaller", "another_caller"]      # bare handles, as shipped
    mod.EXCLUDE_EXTRA = {"@spambot"}                   # ...and an @-prefixed one
    mod.LANGUAGE_PATTERNS = [(r"missed the pump", "Missed opportunities", 4)]
    mod.SEARCH_QUERIES = []
    mod.FILTERS = {"follower_min": 25, "follower_max": 60000,
                   "skip_verified_org": True, "require_recent_days": 45}
    mod.SCORE_BUCKETS = {"HIGH": 6, "MED": 3}
    mod.REPLY_TEMPLATES = {}
    sys.modules["scraper_config"] = mod


_install_stub_config()
import x_scraper  # noqa: E402


def _row(handle, score=5):
    return {"handle": handle, "score": score}


class TestHandleNormalisation(unittest.TestCase):
    def test_strips_at_and_lowercases(self):
        self.assertEqual(x_scraper.norm_handle("@BigCaller"), "bigcaller")
        self.assertEqual(x_scraper.norm_handle("BigCaller"), "bigcaller")

    def test_tolerates_none_and_whitespace(self):
        self.assertEqual(x_scraper.norm_handle(None), "")
        self.assertEqual(x_scraper.norm_handle("  @Foo  "), "foo")


class TestDedupe(unittest.TestCase):
    def test_caller_accounts_are_excluded_from_their_own_lead_list(self):
        kept = x_scraper.dedupe([_row("@BigCaller", 9), _row("@realLead", 5)], set())
        self.assertEqual([r["handle"] for r in kept], ["@realLead"])

    def test_extra_exclusions_match_regardless_of_at_prefix(self):
        kept = x_scraper.dedupe([_row("@spambot"), _row("@realLead")], set())
        self.assertEqual([r["handle"] for r in kept], ["@realLead"])

    def test_duplicate_handles_collapse_keeping_highest_score(self):
        kept = x_scraper.dedupe([_row("@dupe", 3), _row("@dupe", 9)], set())
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["score"], 9)

    def test_already_seen_handles_are_skipped_in_either_form(self):
        self.assertEqual(x_scraper.dedupe([_row("@known")], {"known"}), [])


if __name__ == "__main__":
    unittest.main()
