"""Keyword + fuzzy matching. Uses rapidfuzz if installed, else stdlib difflib."""
from difflib import SequenceMatcher

try:
    from rapidfuzz import fuzz

    def _partial(a, b, threshold=0.0):
        # score_cutoff lets rapidfuzz abandon a comparison as soon as it cannot
        # reach the cutoff; it returns 0 in that case, which callers discard
        # anyway since they only keep ratios at or above the threshold.
        return fuzz.partial_ratio(a, b, score_cutoff=threshold)

except ImportError:  # stdlib fallback — no external dependency required

    def _partial(a, b, threshold=0.0):
        if not a or not b:
            return 0.0
        if len(a) > len(b):
            a, b = b, a
        n, best = len(a), 0.0
        floor = max(0.0, threshold)
        # Hold the phrase as seq2: SequenceMatcher caches its index of seq2, so
        # only the cheap side is rebuilt for each window of the reply text.
        sm = SequenceMatcher(None)
        sm.set_seq2(a)
        for i in range(0, len(b) - n + 1):
            sm.set_seq1(b[i:i + n])
            # real_quick_ratio/quick_ratio are cheap *upper bounds* on ratio(),
            # so a window that cannot beat the best-so-far (or clear the
            # threshold) can be skipped without changing the result.
            target = max(best, floor)
            if sm.real_quick_ratio() * 100 < target or sm.quick_ratio() * 100 < target:
                continue
            r = sm.ratio() * 100
            if r > best:
                best = r
            if best >= 100:
                break
        return best


def match_phrases(text, phrases, threshold):
    """Return list of (phrase, ratio) matching text (substring = 100, else fuzzy).

    Returns immediately on an exact substring hit: callers keep the highest
    ratio and nothing beats 100, so fuzzy-scoring the remaining phrases is pure
    waste — and each one costs an O(len(text) x len(phrase)) comparison.
    """
    t = (text or "").lower()
    if not t:
        return []
    hits = []
    for p in phrases:
        pl = p.lower()
        if pl in t:
            return [(p, 100.0)]
        # Fuzzy only when the text is long enough to plausibly contain the
        # phrase. Without this, a 3-char reply ("gem") scores ~100 against a
        # long phrase ("where do you find gems") because partial matching
        # aligns the short text inside the phrase — a false positive.
        if len(t) >= len(pl) * 0.9:
            r = _partial(pl, t, threshold)
            if r >= threshold:
                hits.append((p, round(float(r), 1)))
    return hits
