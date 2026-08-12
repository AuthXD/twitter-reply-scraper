"""Store behaviour: dedup, intent filtering in SQL, and batched commits."""
import os
import tempfile
import unittest

from reply_pipeline.db import DB
from reply_pipeline.models import Reply, Scored


def _reply(rid, text="how do you find these gems?", followers=500):
    return Reply(reply_id=rid, author_handle="someone", text=text, caller="caller",
                 url=f"https://x.com/someone/status/{rid}", author_followers=followers,
                 created_at="2026-07-15T10:00:00Z", source_post_id="900",
                 like_count=1, reply_count=0)


class DBTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.path)
        self.db = DB(self.path)

    def tearDown(self):
        self.db.close()
        if os.path.exists(self.path):
            os.unlink(self.path)


class TestDedup(DBTestCase):
    def test_first_insert_is_new_and_second_is_not(self):
        self.assertTrue(self.db.upsert_reply(_reply("1")))
        self.assertFalse(self.db.upsert_reply(_reply("1")))

    def test_dedup_survives_a_flush(self):
        self.db.upsert_reply(_reply("1"))
        self.db.flush()
        self.assertFalse(self.db.upsert_reply(_reply("1")))


class TestQualifiedFiltersByIntent(DBTestCase):
    def setUp(self):
        super().setUp()
        for rid, intent, sc in (("1", "HIGH", 8), ("2", "MED", 4), ("3", "LOW", 1)):
            r = _reply(rid)
            self.db.upsert_reply(r)
            self.db.save_match(Scored(r, "T", "p", 100.0, sc, intent))
        self.db.flush()

    def test_min_intent_med_excludes_low(self):
        rows = self.db.qualified("MED")
        self.assertEqual({r["intent"] for r in rows}, {"HIGH", "MED"})

    def test_min_intent_high_keeps_only_high(self):
        self.assertEqual([r["intent"] for r in self.db.qualified("HIGH")], ["HIGH"])

    def test_min_intent_low_keeps_everything(self):
        self.assertEqual(len(self.db.qualified("LOW")), 3)

    def test_results_are_ranked_by_score(self):
        self.assertEqual([r["score"] for r in self.db.qualified("LOW")], [8, 4, 1])


class TestVerdictCache(DBTestCase):
    def test_verdict_round_trips(self):
        self.db.save_verdict("1", {"is_lead": True, "theme": "T", "intent": "HIGH",
                                   "confidence": 0.9, "reason": "why"})
        self.db.flush()
        got = self.db.get_verdict("1")
        self.assertTrue(got["is_lead"])
        self.assertEqual(got["intent"], "HIGH")

    def test_unknown_verdict_is_none(self):
        self.assertIsNone(self.db.get_verdict("nope"))


if __name__ == "__main__":
    unittest.main()
