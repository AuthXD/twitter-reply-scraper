"""Negative filters — drop a reply outright, whatever its keyword score.

Keyword themes decide what looks like a lead. This module decides what can
never be one, and runs *before* scoring so a vetoed reply never reaches the
sheet at all.

Categories, checked in this order:

``hate``         hateful content. Checked first and unconditionally: a post that
                 qualifies here is dropped even if it also reads as a perfect
                 lead. Terms come from the operator's private list (see
                 ``hate_terms_file``) — none ship in this repo.
``promo``        shilling: presales, invite links, pasted contract addresses.
``competitor``   accounts marketing a rival product rather than needing one.
``announcement`` broadcasting rather than asking — launches, "called it", gain
                 brags. Someone performing a win is not someone with a problem.
``off_topic``    a positive gate. Correct intent language in the wrong universe
                 — a medical update matching "best bot", a developer asking
                 which tool to use for something unrelated. No blocklist catches
                 these, because nothing in the text is bad; the post simply has
                 to be about the domain to count.
``not_asking``   the second positive gate: the reply has to read as someone
                 *seeking*. Kept separate from ``announcement`` on purpose — a
                 drop here means the ask vocabulary is too narrow, a drop there
                 means the broadcast list is too wide, and the two fixes are
                 opposite. Collapsing them would make the audit trail useless.

Matching is word-bounded. Substring matching would flag "class" for containing
"ass" and, on a hate list, silently discard innocent replies.
"""
import os
import re

from .textmatch import match_phrases

# Pasted addresses and invite links are the most reliable shill tells; X strips
# most other URLs. Tune these in config via `veto.patterns` if they overreach.
EVM_ADDRESS = r"\b0x[a-fA-F0-9]{40}\b"
SOLANA_ADDRESS = r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b"
TELEGRAM_INVITE = r"\bt\.me/\S+"
DISCORD_INVITE = r"\bdiscord\.gg/\S+"

DEFAULT_PATTERNS = (EVM_ADDRESS, SOLANA_ADDRESS, TELEGRAM_INVITE, DISCORD_INVITE)

# "$WIF" — a cashtag is on its own enough to place a post in the domain.
CASHTAG = re.compile(r"\$[A-Za-z]{2,10}\b")

# --- announcing -------------------------------------------------------------
# Results-posting, in the two shapes no word list catches: a bare gain
# ("up 40x", "did 300%") and a victory lap referencing one's own call.
GAIN_BRAG = r"\b(?:up|did|hit|made|took)\s+(?:another\s+)?\d+(?:[.,]\d+)?\s*(?:x|%)"
CALL_BRAG = r"\b\d+(?:[.,]\d+)?x\b[^?!.]{0,25}\b(?:call|called|entry|from my|off my)\b"

DEFAULT_ANNOUNCEMENT_PATTERNS = (GAIN_BRAG, CALL_BRAG)

# --- asking -----------------------------------------------------------------
# A lead is someone with the problem, not someone performing a win. Two shapes
# count as asking, and the second is the one that is easy to get wrong: a
# first-person statement of need or regret ("keep missing these", "wish i
# aped") contains no question mark at all, yet it is precisely the pain the
# product solves. Gating on "?" alone would silently delete the Regret,
# Missed-opportunity and FOMO themes wholesale — the highest-intent replies in
# the sheet — so first-person need counts as asking.
#
# Deliberately NOT here: third-person commentary ("he keeps missing these",
# "everyone fumbled that"). Someone narrating another trader's pain is a
# spectator, not a buyer, which is why every pain pattern below is anchored to
# a first-person subject.
DEFAULT_ASK_PATTERNS = (
    r"\?",
    r"\b(?:how|what|which|where|when|why|who)\b[^?!.]{0,40}"
    r"\b(?:do|does|did|is|are|can|could|should|would|to|u|you)\b",
    r"\b(?:any|anyone|anybody|someone)\b[^?!.]{0,30}"
    r"\b(?:know|knows|got|use|using|recommend|recommendations?|tips?|advice|help|good|decent|worth)\b",
    r"\b(?:recommend|recommendations?|recs|suggestions?)\b",
    r"\b(?:looking for|need help|help me|advice on|tips on|point me|"
    r"where do i|where can i|how do i|how do you|how to)\b",
    r"\bi\s*(?:'|’)?\s*(?:m|am)?\s*(?:really |just |always |still )?"
    r"(?:need|needing|want|wanting|looking)\b",
    r"\bi\s+(?:keep|kept|always|never|cant|can(?:'|’)?t|couldn(?:'|’)?t|"
    r"missed|miss|fumbled|hesitated|jeeted|sold)\b",
    r"\bi(?:'|’)?m\b[^?!.]{0,25}"
    r"\b(?:too late|late|lost|stuck|confused|new|struggling|done)\b",
    r"\bwish i\b",
    r"\bshould(?:n(?:'|’)?t)?\s+have\b",
    r"\b(?:tired|sick) of\b",
    r"\bhow are (?:you|u|ppl|people|yall|y'all)\b",
    r"\b(?:new to|just started|getting into)\b",
)

# Pain phrasing, matched FUZZILY. These carry no question mark and often no
# pronoun ("missed another 10x again smh"), but they are the Regret and
# Missed-opportunity themes — the highest-intent replies in the sheet.
#
# Fuzzy, because theme matching is fuzzy: a typo'd lead ("missd anethr runner
# ugh") is exactly what the fuzzy layer exists to catch, and an exact-match
# gate placed in front of it would delete that lead before it was ever scored.
DEFAULT_ASK_PHRASES = (
    "missed", "missed another", "missed the pump", "missed the run",
    "keep missing", "always miss", "too late", "priced out", "sidelined",
    "fumbled", "fumbled the bag", "sold too early", "paper handed", "jeeted",
    "got rugged", "keep getting rugged", "rugged again", "sick of", "tired of",
    "wish i", "should have", "need a better way", "dont want to miss",
    "cant find", "struggling", "no idea how",
)

# The ask gate errs loose on purpose. A false positive here merely keeps a
# reply that the announcement filters and the stage-2 LLM gate still screen; a
# false negative deletes a lead permanently. 75 clears the typo'd archetype
# ("missd anethr" scores 83 against "missed") while theme matching stays at 86.
DEFAULT_ASK_FUZZY_THRESHOLD = 75

# Who the pain belongs to. "i keep missing these" is a buyer; "he keeps missing
# these" is a spectator narrating someone else's trade, and scores identically
# on the pain vocabulary above — so the fuzzy route checks the subject.
FIRST_PERSON = re.compile(r"\b(?:i|i(?:'|’)?m|im|i(?:'|’)?ve|ive|my|me|mine|we|our|us)\b", re.I)
THIRD_PERSON = re.compile(
    r"\b(?:he|she|they|him|her|them|his|their|theyre|everyone|everybody|"
    r"nobody|people|bro|dude|guys|yall|y(?:'|’)all|this guy|these guys)\b", re.I)


def _terms_re(terms):
    """Word-bounded alternation over a term list, or None if the list is empty."""
    cleaned = [re.escape(str(t).strip().lower()) for t in (terms or []) if str(t).strip()]
    if not cleaned:
        return None
    return re.compile(r"\b(?:" + "|".join(cleaned) + r")\b", re.IGNORECASE)


def load_terms_file(path):
    """Read one term per line; blank lines and # comments ignored.

    Raises if the file is configured but unreadable. A hate filter that quietly
    disables itself because of a typo'd path is worse than a failed run.
    """
    if not os.path.exists(path):
        raise ValueError(
            f"veto.hate_terms_file {path!r} not found. Point it at your term list "
            "or remove the setting — it must not fail silently.")
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f
                if line.strip() and not line.lstrip().startswith("#")]


class Veto:
    def __init__(self, hate_terms=(), promo_markers=(), competitor_markers=(),
                 patterns=None, domain_terms=(), require_domain=False,
                 announcement_markers=(), announcement_patterns=None,
                 ask_markers=(), ask_patterns=None, require_ask=False,
                 ask_phrases=None, ask_fuzzy_threshold=DEFAULT_ASK_FUZZY_THRESHOLD):
        self._hate = _terms_re(hate_terms)
        self._promo = _terms_re(promo_markers)
        self._competitor = _terms_re(competitor_markers)
        self._patterns = [re.compile(p, re.I) for p in
                          (DEFAULT_PATTERNS if patterns is None else tuple(patterns))]
        self._domain = _terms_re(domain_terms)
        self._announcement = _terms_re(announcement_markers)
        self._announcement_patterns = [
            re.compile(p, re.I) for p in
            (DEFAULT_ANNOUNCEMENT_PATTERNS if announcement_patterns is None
             else tuple(announcement_patterns))]
        # Config-supplied ask vocabulary widens the built-in patterns; it only
        # replaces them if `ask_patterns` is given outright.
        self._ask = [re.compile(p, re.I) for p in
                     (DEFAULT_ASK_PATTERNS if ask_patterns is None else tuple(ask_patterns))]
        extra_ask = _terms_re(ask_markers)
        if extra_ask is not None:
            self._ask.append(extra_ask)
        self._ask_phrases = list(DEFAULT_ASK_PHRASES if ask_phrases is None else ask_phrases)
        self._ask_threshold = ask_fuzzy_threshold
        # With no domain vocabulary the gate would veto everything, so it only
        # engages once terms exist.
        self.require_domain = bool(require_domain) and self._domain is not None
        self.require_ask = bool(require_ask)

    @classmethod
    def from_config(cls, cfg):
        get = cfg.get if hasattr(cfg, "get") else (lambda k, d=None: d)
        v = get("veto") or {}
        hate = list(v.get("hate_terms") or [])
        terms_file = v.get("hate_terms_file")
        if terms_file:
            hate += load_terms_file(terms_file)
        return cls(
            hate_terms=hate,
            promo_markers=v.get("promo_markers") or [],
            competitor_markers=v.get("competitor_markers") or [],
            patterns=v.get("patterns"),
            domain_terms=v.get("domain_terms") or get("domain_terms") or [],
            require_domain=v.get("require_domain", get("require_domain", False)),
            announcement_markers=v.get("announcement_markers") or [],
            announcement_patterns=v.get("announcement_patterns"),
            ask_markers=v.get("ask_markers") or [],
            ask_patterns=v.get("ask_patterns"),
            require_ask=v.get("require_ask", get("require_ask", False)),
            ask_phrases=v.get("ask_phrases"),
            ask_fuzzy_threshold=v.get("ask_fuzzy_threshold",
                                      DEFAULT_ASK_FUZZY_THRESHOLD),
        )

    @property
    def has_hate_filter(self):
        """False when no hate vocabulary is configured.

        The repo ships an empty list on purpose — slurs do not belong in source
        control — which means this filter is inert until the operator supplies
        one. Callers should say so out loud rather than let it pass unnoticed.
        """
        return self._hate is not None

    def check(self, text):
        """Return ``(category, detail)`` to drop the reply, or None to keep it."""
        t = (text or "").strip()
        if not t:
            return None
        if self._hate is not None:
            m = self._hate.search(t)
            if m:
                return ("hate", m.group(0).lower())
        if self._promo is not None:
            m = self._promo.search(t)
            if m:
                return ("promo", m.group(0).lower())
        for rx in self._patterns:
            m = rx.search(t)
            if m:
                return ("promo", m.group(0)[:32])
        if self._competitor is not None:
            m = self._competitor.search(t)
            if m:
                return ("competitor", m.group(0).lower())
        if self._announcement is not None:
            m = self._announcement.search(t)
            if m:
                return ("announcement", m.group(0).lower())
        for rx in self._announcement_patterns:
            m = rx.search(t)
            if m:
                return ("announcement", m.group(0)[:32])
        if self.require_domain and not self._in_domain(t):
            return ("off_topic", "")
        if self.require_ask and not self.is_asking(t):
            return ("not_asking", "")
        return None

    def _in_domain(self, text):
        if self._domain is not None and self._domain.search(text):
            return True
        return bool(CASHTAG.search(text))

    def is_asking(self, text):
        """True when the reply reads as seeking rather than broadcasting.

        Two routes. A structural one — a question, an interrogative, an explicit
        request, a first-person need — and a fuzzy pain route for the regret and
        missed-opportunity phrasing that never asks anything outright.

        The pain route is subject-checked: pain the author does not claim as
        their own ("he keeps missing these") is commentary, not demand.
        """
        t = (text or "").strip()
        if not t:
            return False
        if any(rx.search(t) for rx in self._ask):
            return True
        if not self._ask_phrases:
            return False
        if not match_phrases(t, self._ask_phrases, self._ask_threshold):
            return False
        # Pain matched. It counts only if the author owns it.
        return bool(FIRST_PERSON.search(t)) or not THIRD_PERSON.search(t)
