"""Turn a theme weight + signals into an intent bucket."""


def score(weight, text, likes, cfg):
    s = weight
    sc = cfg["scoring"]
    if "?" in (text or ""):
        s += sc["question_bonus"]
    if (likes or 0) >= 5:
        s += sc["engagement_ge_5"]
    if (likes or 0) >= 50:
        s += sc["engagement_ge_50"]
    return s


def bucket(s, cfg):
    sc = cfg["scoring"]
    if s >= sc["high_cutoff"]:
        return "HIGH"
    if s >= sc["med_cutoff"]:
        return "MED"
    return "LOW"


ORDER = {"LOW": 0, "MED": 1, "HIGH": 2}
UNKNOWN = -1


def rank(intent):
    """Numeric rank of an intent label; unknown/missing sorts below LOW."""
    return ORDER.get(str(intent or "").strip().upper(), UNKNOWN)


def meets_min(intent, min_intent):
    """True if ``intent`` is at least ``min_intent``.

    Tolerant on both sides: a NULL or unrecognised intent column must not raise
    mid-export, and a lowercase `export_min_intent` in config.yaml must not
    either. An unrecognised floor keeps everything rather than dropping the run.
    """
    return rank(intent) >= rank(min_intent)
