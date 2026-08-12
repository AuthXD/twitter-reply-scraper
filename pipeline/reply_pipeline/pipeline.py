"""Orchestrate: fetch (adapter) -> dedup store -> veto -> filter+score -> persist."""
import logging
from collections import Counter

from .db import DB
from .filters import classify, passes_retail
from .scoring import score, bucket
from .models import Scored
from .veto import Veto

log = logging.getLogger("reply_scraper")


def run(cfg, adapter):
    threshold = cfg["fuzzy_threshold"]
    fetched = matched = 0
    vetoed = Counter()

    min_chars = cfg.get("min_reply_chars", 0)
    min_words = cfg.get("min_reply_words", 0)
    exclude = {h.lstrip("@").lower() for h in cfg.get("exclude_handles", [])}
    veto = Veto.from_config(cfg)
    if not (cfg.get("veto") or {}):
        log.warning("[veto] no `veto:` block in config — hate, promo, competitor "
                    "and announcement filtering are ALL inactive, and both "
                    "positive gates are off. Copy the block from "
                    "config.example.yaml.")
    if not veto.has_hate_filter:
        log.warning("[veto] no hate terms configured — stage-1 hate filtering is "
                    "INACTIVE. Set veto.hate_terms_file in config.yaml. Until then "
                    "only the stage-2 LLM gate screens for hateful content.")

    # `with` guarantees the final partial batch is committed and the connection
    # closed even if an adapter raises mid-run.
    with DB(cfg["database"]) as db:
        run_id = db.start_run(adapter.name)
        for reply in adapter.fetch(cfg, db, log):
            is_new = db.upsert_reply(reply)      # dedup
            if not is_new:
                continue
            fetched += 1
            if not passes_retail(reply, cfg["retail"]):
                continue
            text = (reply.text or "").strip()
            # Drop thin, low-signal replies ("gem", "yo", "King") before matching.
            if len(text) < min_chars or len(text.split()) < min_words:
                continue
            if (reply.author_handle or "").lstrip("@").lower() in exclude:
                continue
            # Negative filters run before scoring: hate, promo, competitor,
            # announcements, off-topic and non-asking replies must never reach
            # the sheet, whatever they score. Each drop is logged with its
            # category and trigger so the lead list stays auditable.
            drop = veto.check(text)
            if drop:
                category, detail = drop
                vetoed[category] += 1
                log.info("[veto:%s] @%s %r%s", category, reply.author_handle,
                         text[:100], " <- %s" % detail if detail else "")
                continue
            hit = classify(reply.text, cfg.themes, threshold)   # accounts already filtered by adapter
            if not hit:
                continue
            theme, weight, phrase, ratio = hit
            s = score(weight, reply.text, reply.like_count, cfg)
            db.save_match(Scored(reply, theme, phrase, ratio, s, bucket(s, cfg)))
            matched += 1

        db.finish_run(run_id, fetched, matched)

    log.info("run complete: %d new replies, %d qualified%s", fetched, matched,
             _veto_summary(vetoed))
    return {"fetched": fetched, "matched": matched, "vetoed": dict(vetoed),
            "db": cfg["database"]}


def _veto_summary(vetoed):
    if not vetoed:
        return ""
    return " | vetoed: " + ", ".join(f"{k}={v}" for k, v in sorted(vetoed.items()))
