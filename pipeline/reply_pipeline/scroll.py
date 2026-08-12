"""Pure helpers for the browser adapters.

Kept free of Playwright so the stop-scrolling and permalink-selection rules —
the two places the adapter previously got subtly wrong — can be unit tested
without driving a real Chromium.
"""
import re

_STATUS_RE = re.compile(r"/status/(\d+)")
_LEADING_NUM_RE = re.compile(r"([\d.,]+)\s*([KM]?)", re.IGNORECASE)


class ScrollTracker:
    """Decide when a lazily-loaded feed has stopped yielding new items.

    Feed one cumulative "items seen so far" count per scroll; ``record`` returns
    True once ``max_stalls`` consecutive scrolls have failed to surface anything
    new, so the caller can stop early instead of burning its full scroll budget
    (and the randomised pause that comes with each one).
    """

    def __init__(self, max_stalls=2):
        self.max_stalls = max_stalls
        self._last = None
        self._stalls = 0

    def record(self, seen_count):
        if self._last is not None and seen_count <= self._last:
            self._stalls += 1
        else:
            self._stalls = 0
        self._last = seen_count
        return self._stalls >= self.max_stalls


def pick_permalink(candidates):
    """Choose a tweet's own permalink from its article's /status/ links.

    ``candidates`` is an iterable of ``(href, wraps_timestamp)``. A tweet article
    can contain several /status/ links — a quoted tweet's permalink often comes
    first in DOM order — but only the tweet's *own* permalink wraps its
    timestamp, so that one wins. Returns ``(tweet_id, author_handle)``.
    """
    fallback = None
    for href, wraps_timestamp in candidates or []:
        m = _STATUS_RE.search(href or "")
        if not m:
            continue
        parts = (href or "").strip("/").split("/")
        author = parts[0] if parts and parts[0] else None
        found = (m.group(1), author)
        if wraps_timestamp:
            return found
        if fallback is None:
            fallback = found
    return fallback if fallback is not None else (None, None)


def parse_metric(label):
    """Turn an aria-label like '1.2K replies. Reply' into an int, best-effort."""
    if not label:
        return 0
    m = _LEADING_NUM_RE.search(label)
    if not m:
        return 0
    num, suffix = m.group(1).replace(",", ""), m.group(2).upper()
    try:
        val = float(num)
    except ValueError:
        return 0
    if suffix == "K":
        val *= 1_000
    elif suffix == "M":
        val *= 1_000_000
    return int(val)
