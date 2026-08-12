"""LLM response parsing must be resilient: one malformed row must not
discard the whole batch, and a bad Retry-After must not escape the retry loop."""
import json
import unittest
from reply_pipeline.llm_filter import LLMFilter, retry_delay


class TestBatchParsing(unittest.TestCase):
    def test_one_bad_confidence_does_not_lose_the_whole_batch(self):
        raw = json.dumps({"results": [
            {"i": 1, "is_lead": True, "theme": "T", "intent": "HIGH", "confidence": 0.9, "reason": "ok"},
            {"i": 2, "is_lead": True, "theme": "T", "intent": "HIGH", "confidence": "very high", "reason": "bad"},
            {"i": 3, "is_lead": False, "theme": None, "intent": "LOW", "confidence": 0.8, "reason": "ok"},
        ]})
        out = LLMFilter._parse_batch(raw, 3)
        self.assertIsNotNone(out, "a single malformed row must not nuke the batch")
        self.assertIsNotNone(out[0])
        self.assertIsNotNone(out[2])
        self.assertEqual(out[0]["confidence"], 0.9)
        self.assertFalse(out[2]["is_lead"])

    def test_missing_row_stays_none(self):
        raw = json.dumps({"results": [
            {"i": 1, "is_lead": True, "theme": "T", "intent": "HIGH", "confidence": 0.9, "reason": "ok"},
        ]})
        out = LLMFilter._parse_batch(raw, 3)
        self.assertIsNotNone(out[0])
        self.assertIsNone(out[1])
        self.assertIsNone(out[2])

    def test_single_parse_survives_bad_confidence(self):
        raw = json.dumps({"is_lead": True, "theme": "T", "intent": "HIGH",
                          "confidence": "high", "reason": "r"})
        out = LLMFilter._parse(raw)
        self.assertIsNotNone(out)
        self.assertTrue(out["is_lead"])
        self.assertIsInstance(out["confidence"], float)


class TestRetryDelay(unittest.TestCase):
    def test_numeric_retry_after_is_honoured(self):
        self.assertEqual(retry_delay("5", attempt=0), 5.0)

    def test_http_date_retry_after_falls_back_to_backoff(self):
        # RFC allows an HTTP-date here; float() would raise on it.
        self.assertEqual(retry_delay("Wed, 21 Oct 2026 07:28:00 GMT", attempt=2), 4.0)

    def test_missing_retry_after_uses_exponential_backoff(self):
        self.assertEqual(retry_delay(None, attempt=3), 8.0)

    def test_delay_is_capped(self):
        self.assertEqual(retry_delay("99999", attempt=0), 30.0)


class TestEndpointFailureIsCounted(unittest.TestCase):
    """Fail-open keeps the row when a call errors, so a broken stage 2 produces
    output that looks like a clean run with nothing vetoed. The failure has to
    be counted or it is invisible: warning once per run hid how many batches
    actually died, and a run where every call timed out reported the same way
    as one where every call succeeded and found nothing.
    """

    def _exploding(self, batch_size):
        f = LLMFilter(enabled=False, batch_size=batch_size)
        def boom(*args, **kwargs):
            raise RuntimeError("HTTP Error 504: Gateway Timeout")
        f._post = boom
        return f

    def test_counters_start_at_zero(self):
        f = LLMFilter(enabled=False)
        self.assertEqual(f.batches_attempted, 0)
        self.assertEqual(f.failed_batches, 0)
        self.assertEqual(f.rows_unjudged_by_error, 0)

    def test_every_failed_batch_and_row_is_counted(self):
        f = self._exploding(batch_size=2)
        out = f.classify_batch(["a", "b", "c"], ["Theme"])
        # fail-open: the caller still gets a verdict slot per input, all empty
        self.assertEqual(out, [None, None, None])
        self.assertEqual(f.batches_attempted, 2)     # 2 + 1
        self.assertEqual(f.failed_batches, 2)
        self.assertEqual(f.rows_unjudged_by_error, 3)

    def test_a_healthy_run_counts_batches_but_no_failures(self):
        f = LLMFilter(enabled=False, batch_size=2)
        f._post = lambda *a, **kw: json.dumps({"results": [
            {"i": 1, "is_lead": True, "theme": "Theme", "intent": "HIGH",
             "confidence": 0.9, "reason": "ok"},
            {"i": 2, "is_lead": False, "theme": None, "intent": "LOW",
             "confidence": 0.9, "reason": "no"},
        ]})
        f.classify_batch(["a", "b"], ["Theme"])
        self.assertEqual(f.batches_attempted, 1)
        self.assertEqual(f.failed_batches, 0)
        self.assertEqual(f.rows_unjudged_by_error, 0)


if __name__ == "__main__":
    unittest.main()
