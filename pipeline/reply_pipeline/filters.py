"""Classify a reply to its strongest keyword theme, and apply retail filters."""
from datetime import datetime, timezone, timedelta
from .textmatch import match_phrases


def classify(text, themes, threshold):
    """Return (theme_name, weight, matched_phrase, ratio) for the best theme, or None."""
    best = None
    for th in themes:
        hits = match_phrases(text, th["phrases"], threshold)
        if not hits:
            continue
        phrase, ratio = max(hits, key=lambda h: h[1])
        cand = (th["name"], int(th["weight"]), phrase, ratio)
        if best is None or cand[1] > best[1] or (cand[1] == best[1] and cand[3] > best[3]):
            best = cand
    return best


def passes_retail(reply, retail):
    f = reply.author_followers
    if f is None:
        # The browser adapters cannot read follower counts off a thread view, so
        # the follower bounds silently do not apply to them. Opt into dropping
        # those replies with `retail.require_followers: true`.
        if retail.get("require_followers"):
            return False
    elif f < retail["follower_min"] or f > retail["follower_max"]:
        return False
    days = retail.get("max_age_days", 0)
    if days and reply.created_at:
        try:
            dt = datetime.fromisoformat(reply.created_at.replace("Z", "+00:00"))
            if dt < datetime.now(timezone.utc) - timedelta(days=days):
                return False
        except ValueError:
            pass
    return True
