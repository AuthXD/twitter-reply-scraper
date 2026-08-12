"""LLM intent gate (optional, fail-open) — OpenAI-compatible, provider-neutral.

Keyword matching is context-blind: it flags "I missed the pump" (a real lead) and
"Glad I missed that pump, what a rug" (NOT a lead) identically. This module sends a
keyword *candidate* to an OpenAI-compatible chat endpoint and asks it to judge intent
with a strict-JSON reply. It runs as a GATE after the rapidfuzz match, so a run is a
few dozen calls, not thousands.

Fail-open: if disabled, unreachable, or malformed, `classify` returns None and the
caller keeps the keyword verdict — a hiccup never zeroes a run.

Default target is NVIDIA NIM (https://integrate.api.nvidia.com/v1), but any
OpenAI-compatible server works (Groq, your dev server) by changing base_url/model.
The API key is read from an env var (never hardcode it in a repo):

    NVIDIA:  setx NVIDIA_API_KEY "nvapi-..."
    config:  llm.enabled: true

Quick check:  python -m reply_pipeline.llm_filter "glad i missed that rug lol"
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
NVIDIA_URL = "https://integrate.api.nvidia.com/v1"
RETRY_CAP = 30.0


def retry_delay(retry_after, attempt, cap=RETRY_CAP):
    """Seconds to wait before retrying, capped.

    RFC 9110 allows Retry-After to be either a delay in seconds *or* an
    HTTP-date. Calling float() on a date raises, and that exception would escape
    the retry handler and abandon a whole batch of candidates, so anything
    unparseable falls back to exponential backoff.
    """
    try:
        secs = float(retry_after)
    except (TypeError, ValueError):
        secs = float(2 ** attempt)
    return min(max(secs, 0.0), cap)

SYSTEM = (
    "You qualify X/Twitter posts as sales leads for the product being marketed — a "
    "Solana memecoin alpha tool that helps traders find tokens early, track "
    "whale/smart-money wallets, and avoid rugs. A LEAD is a real person expressing, "
    "in first person and present intent, a pain the product solves — FOMO/regret "
    "about missing runners, asking how to "
    "find gems early, wanting to track wallets, tool/scanner fatigue, or rug/KOL "
    "distrust.\n"
    "Reject, with is_lead=false, every one of the following:\n"
    "1. SARCASM/NEGATION — jokes, or someone GLAD they avoided or dodged a coin.\n"
    "2. PROMOTION — shilling a coin, presale, call channel, or invite link; "
    "bragging about gains.\n"
    "3. COMPETITOR — anyone marketing their OWN tool, bot, scanner or service "
    "('we built', 'try our', 'link in bio', 'free beta'). Someone SELLING a "
    "solution is never someone who needs one.\n"
    "4. OFF-TOPIC — the post is not about crypto/memecoin trading at all. Intent "
    "words appear in unrelated contexts: 'best bot' in a medical or personal "
    "update, 'what tool do you use' from a software developer discussing "
    "unrelated software. If the subject is not crypto trading, it is not a lead "
    "no matter how well the phrasing matches.\n"
    "5. HATEFUL — any post attacking or demeaning people by race, ethnicity, "
    "religion, nationality, gender, sexuality or disability, including slurs. "
    "Always reject these, even if the same post also expresses genuine buying "
    "intent. Set theme to null and reason to 'hateful content'.\n"
    "6. COMMENTARY — price talk, or talk about other people rather than their "
    "own need.\n"
    "7. ANNOUNCING — the author is broadcasting a result rather than seeking "
    "anything: a launch, a win, a called shot, an exit, a position update. The "
    "test is direction. A lead is ASKING (a question, a request, or a "
    "first-person statement of need or regret); an announcement is TELLING. "
    "'missed another 10x, need a better way' is asking; 'called it, up 40x' is "
    "announcing. Pain the author does not claim as their own ('he keeps "
    "missing these') is commentary, not demand.\n"
    "Read negation and sarcasm carefully. Reply with STRICT JSON only, no prose."
)

FEWSHOT = [
    ("Glad I missed that $WIF pump lol, what a rug 😂",
     '{"is_lead": false, "theme": null, "intent": "LOW", "confidence": 0.95, "reason": "sarcastic, glad he avoided it"}'),
    ("how do you guys actually find these gems before they run? feel like im always late",
     '{"is_lead": true, "theme": "Looking for early calls", "intent": "HIGH", "confidence": 0.92, "reason": "first-person help-seeking"}'),
    ("smart money is loading up on $PONS, flows look strong",
     '{"is_lead": false, "theme": null, "intent": "LOW", "confidence": 0.85, "reason": "market commentary, not a need"}'),
    ("man I keep fumbling every runner, need a better way to catch them early",
     '{"is_lead": true, "theme": "Missed opportunities", "intent": "HIGH", "confidence": 0.9, "reason": "regret + wants a solution"}'),
    ("we just shipped a solana wallet tracker — free beta, link in bio",
     '{"is_lead": false, "theme": null, "intent": "LOW", "confidence": 0.94, "reason": "marketing a competing tool"}'),
    ("mums scan came back clear today, best bot of news all year",
     '{"is_lead": false, "theme": null, "intent": "LOW", "confidence": 0.96, "reason": "not about crypto trading"}'),
    ("what tool do you all use for kubernetes log aggregation?",
     '{"is_lead": false, "theme": null, "intent": "LOW", "confidence": 0.93, "reason": "unrelated software question"}'),
    ("called it again — up 40x on that play, told you all",
     '{"is_lead": false, "theme": null, "intent": "LOW", "confidence": 0.94, "reason": "announcing a win, not seeking"}'),
    ("he keeps missing every runner lol",
     '{"is_lead": false, "theme": null, "intent": "LOW", "confidence": 0.88, "reason": "about someone else, not own need"}'),
]

USER_TMPL = (
    "Themes: {themes}.\n\n"
    "Post:\n\"\"\"{text}\"\"\"\n\n"
    "Return JSON exactly: {{\"is_lead\": true|false, \"theme\": <one theme name or "
    "null>, \"intent\": \"HIGH\"|\"MED\"|\"LOW\", \"confidence\": 0.0-1.0, "
    "\"reason\": \"<=12 words\"}}"
)


class LLMFilter:
    def __init__(self, enabled=False, base_url=NVIDIA_URL,
                 model="meta/llama-3.1-8b-instruct", api_key=None,
                 timeout=45, min_confidence=0.5, fail_open=True, json_mode=True,
                 batch_size=20, requests_per_min=35):
        self.enabled = bool(enabled)
        self.batch_size = int(batch_size)
        self.requests_per_min = int(requests_per_min)
        self._req_times = []
        self.base_url = (base_url or NVIDIA_URL).rstrip("/")
        self.model = model or "meta/llama-3.1-8b-instruct"
        self.api_key = api_key
        self.timeout = timeout
        self.min_confidence = float(min_confidence)
        self.fail_open = bool(fail_open)
        self.json_mode = bool(json_mode)
        self._cache = {}
        self._warned = False
        # Fail-open means an endpoint error is INVISIBLE in the output: the row
        # is simply kept with the keyword verdict. Warning once per run hid how
        # much of a run that covered, so count it and let the caller report it.
        self.batches_attempted = 0
        self.failed_batches = 0
        self.rows_unjudged_by_error = 0
        self.label = f"{self.base_url} ({self.model})"
        if self.enabled and not self.api_key:
            raise ValueError("llm.enabled but no API key — set NVIDIA_API_KEY env var "
                             "(or llm.api_key in config.yaml)")

    @classmethod
    def from_config(cls, cfg):
        c = (cfg.get("llm") or {}) if hasattr(cfg, "get") else {}
        env_name = c.get("api_key_env", "NVIDIA_API_KEY")
        api_key = (c.get("api_key") or os.environ.get(env_name)
                   or os.environ.get("NVIDIA_API_KEY") or os.environ.get("GROQ_API_KEY"))
        return cls(
            enabled=c.get("enabled", False),
            base_url=c.get("base_url", NVIDIA_URL),
            model=c.get("model", "meta/llama-3.1-8b-instruct"),
            api_key=api_key,
            timeout=c.get("timeout", 45),
            min_confidence=c.get("min_confidence", 0.5),
            fail_open=c.get("fail_open", True),
            json_mode=c.get("json_mode", True),
            batch_size=c.get("batch_size", 20),
            requests_per_min=c.get("requests_per_min", 35),
        )

    def _messages(self, text, theme_names):
        msgs = [{"role": "system", "content": SYSTEM}]
        for ex_in, ex_out in FEWSHOT:
            msgs.append({"role": "user", "content": USER_TMPL.format(
                themes=", ".join(theme_names), text=ex_in)})
            msgs.append({"role": "assistant", "content": ex_out})
        msgs.append({"role": "user", "content": USER_TMPL.format(
            themes=", ".join(theme_names), text=text[:1000])})
        return msgs

    def _body(self, messages, max_tokens=200):
        payload = {"model": self.model, "temperature": 0, "max_tokens": max_tokens,
                   "messages": messages}
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        return json.dumps(payload).encode("utf-8")

    def _throttle(self):
        """Block as needed to stay under requests_per_min for this key."""
        if not self.requests_per_min:
            return
        now = time.time()
        self._req_times = [t for t in self._req_times if now - t < 60]
        if len(self._req_times) >= self.requests_per_min:
            sleep = 60 - (now - self._req_times[0]) + 0.2
            if sleep > 0:
                time.sleep(sleep)
            now = time.time()
            self._req_times = [t for t in self._req_times if now - t < 60]
        self._req_times.append(time.time())

    def _post(self, messages, max_tokens=200):
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {self.api_key}"}
        for attempt in range(4):
            self._throttle()
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=self._body(messages, max_tokens), headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:
                # Some models reject response_format -> retry once without it.
                if e.code == 400 and self.json_mode:
                    self.json_mode = False
                    continue
                if e.code in (429, 500, 502, 503) and attempt < 3:
                    time.sleep(retry_delay(e.headers.get("retry-after"), attempt))
                    continue
                raise
        raise RuntimeError("llm: exhausted retries")

    def classify(self, text, theme_names, log=None):
        """{is_lead, theme, intent, confidence, reason} or None (= no opinion)."""
        if not self.enabled or not (text or "").strip():
            return None
        key = (text.strip(), tuple(theme_names))
        if key in self._cache:
            return self._cache[key]
        try:
            verdict = self._parse(self._post(self._messages(text.strip(), theme_names)))
        except Exception as exc:
            if log and not self._warned:
                log.warning("[llm] endpoint error (%s); falling back to keyword only%s",
                            exc, "" if self.fail_open else " and dropping candidates")
                self._warned = True
            verdict = None
        if verdict is not None and verdict.get("confidence", 1.0) < self.min_confidence:
            verdict = None
        self._cache[key] = verdict
        return verdict

    # ------------------------------------------------------------------ #
    # Batched classification — many posts per request (rate-limit friendly).
    # ------------------------------------------------------------------ #
    def _batch_messages(self, texts, theme_names):
        listing = "\n".join(f"{i+1}. {t[:500]}" for i, t in enumerate(texts))
        instr = (
            f"Themes: {', '.join(theme_names)}.\n\n"
            "Classify EACH numbered post below as a lead or not. Apply the same "
            "rules (sarcasm/negation/commentary are NOT leads). Return STRICT JSON:\n"
            '{\"results\": [{\"i\": <post number>, \"is_lead\": true|false, '
            '\"theme\": <one theme name or null>, \"intent\": \"HIGH\"|\"MED\"|\"LOW\", '
            '\"confidence\": 0.0-1.0, \"reason\": \"<=12 words\"}, ...]} '
            "with one object for every post number.\n\nPosts:\n" + listing
        )
        return [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": instr}]

    def classify_batch(self, texts, theme_names, log=None):
        """Classify many posts with few calls. Returns list aligned to `texts`
        of verdict dicts (or None = no opinion -> keep). Uses cache + batching."""
        results = [None] * len(texts)
        todo = []
        for idx, t in enumerate(texts):
            key = ((t or "").strip(), tuple(theme_names))
            if not (t or "").strip():
                continue
            if key in self._cache:
                results[idx] = self._cache[key]
            else:
                todo.append(idx)

        for start in range(0, len(todo), self.batch_size):
            idxs = todo[start:start + self.batch_size]
            chunk = [texts[j] for j in idxs]
            self.batches_attempted += 1
            try:
                raw = self._post(self._batch_messages(chunk, theme_names),
                                 max_tokens=90 * len(chunk) + 200)
                parsed = self._parse_batch(raw, len(chunk))
            except Exception as exc:
                self.failed_batches += 1
                self.rows_unjudged_by_error += len(chunk)
                if log and not self._warned:
                    log.warning("[llm] endpoint error (%s); remaining kept via keyword%s. "
                                "Later batch errors are counted, not logged — see the "
                                "summary line for the total.",
                                exc, "" if self.fail_open else " and dropped")
                    self._warned = True
                parsed = None
            for local, j in enumerate(idxs):
                v = parsed[local] if parsed else None
                if v is not None and v.get("confidence", 1.0) < self.min_confidence:
                    v = None
                self._cache[((texts[j] or "").strip(), tuple(theme_names))] = v
                results[j] = v
            if log:
                done = min(start + self.batch_size, len(todo))
                log.info("[llm] batched %d/%d candidates", done, len(todo))
        return results

    @staticmethod
    def _parse_batch(content, n):
        """Parse {"results":[{i,...}]} into a list length n (index by i, 1-based)."""
        if not content:
            return None
        try:
            obj = json.loads(content)
        except (ValueError, TypeError):
            m = _JSON_RE.search(content or "")
            if not m:
                return None
            try:
                obj = json.loads(m.group(0))
            except (ValueError, TypeError):
                return None
        rows = obj.get("results") if isinstance(obj, dict) else obj
        if not isinstance(rows, list):
            return None
        out = [None] * n
        for r in rows:
            if not isinstance(r, dict):
                continue
            # Guard per row: one post with a junk field (e.g. "confidence":
            # "high") must not discard the other 19 verdicts in the batch.
            try:
                i = int(r.get("i", 0)) - 1
                if 0 <= i < n:
                    out[i] = LLMFilter._coerce(r)
            except (TypeError, ValueError):
                continue
        return out

    @staticmethod
    def _coerce(obj):
        """Normalise one raw verdict dict; never raises on model junk."""
        intent = str(obj.get("intent", "MED") or "MED").strip().upper()
        if intent not in ("HIGH", "MED", "LOW"):
            intent = "MED"
        try:
            confidence = float(obj.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        return {
            "is_lead": bool(obj.get("is_lead")),
            "theme": obj.get("theme") or None,
            "intent": intent,
            "confidence": confidence,
            "reason": (obj.get("reason") or "").strip(),
        }

    @staticmethod
    def _parse(content):
        if not content:
            return None
        try:
            obj = json.loads(content)
        except (ValueError, TypeError):
            m = _JSON_RE.search(content or "")
            if not m:
                return None
            try:
                obj = json.loads(m.group(0))
            except (ValueError, TypeError):
                return None
        if not isinstance(obj, dict):
            return None
        return LLMFilter._coerce(obj)


if __name__ == "__main__":
    import sys
    from .config import Config
    text = " ".join(sys.argv[1:]) or "how do you find these gems so early?"
    cfg = Config.load("config.yaml")
    f = LLMFilter.from_config(cfg)
    if not f.enabled:
        print("llm.enabled is false in config.yaml — set it true to test."); raise SystemExit(0)
    print("endpoint:", f.label)
    import logging; logging.basicConfig(level=logging.INFO)
    print(json.dumps(f.classify(text, [t["name"] for t in cfg.themes],
                                logging.getLogger("llm")), indent=2))
