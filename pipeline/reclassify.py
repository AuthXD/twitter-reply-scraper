#!/usr/bin/env python3
"""Re-run the filters over replies already in the DB, rebuild the matches table,
and re-export qualified.csv — no re-scrape needed. (The LLM refinement is a
separate stage: leads.py.)

This is how an existing lead list gets cleaned retroactively: tighten the veto
lists in config.yaml, re-run, and every stored reply is re-judged against them.

    py -3 reclassify.py
    py -3 reclassify.py --vetoed-out vetoed.csv   # audit what was removed, and why
"""
import argparse
import csv
import logging
import sys
from collections import Counter

from reply_pipeline.config import Config
from reply_pipeline.db import DB
from reply_pipeline.models import Reply, Scored
from reply_pipeline.filters import classify, passes_retail
from reply_pipeline.scoring import score, bucket
from reply_pipeline.veto import Veto
from reply_pipeline import export


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--out", default="qualified.csv")
    ap.add_argument("--vetoed-out", dest="vetoed_out",
                    help="write every vetoed reply here with its category and trigger")
    args = ap.parse_args(argv)

    cfg = Config.load(args.config)
    th = cfg["fuzzy_threshold"]
    mc = cfg.get("min_reply_chars", 0); mw = cfg.get("min_reply_words", 0)
    ex = {h.lstrip("@").lower() for h in cfg.get("exclude_handles", [])}
    veto = Veto.from_config(cfg)
    log = logging.getLogger("reclassify")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not (cfg.get("veto") or {}):
        log.warning("[veto] no `veto:` block in config — hate, promo, competitor "
                    "and announcement filtering are ALL inactive, and both "
                    "positive gates are off. Copy the block from "
                    "config.example.yaml.")
    if not veto.has_hate_filter:
        log.warning("[veto] no hate terms configured — stage-1 hate filtering is "
                    "INACTIVE. Set veto.hate_terms_file in config.yaml.")

    kept = 0
    vetoed = Counter()
    audit = []
    # Closing the store commits the rebuilt matches; export.to_csv opens its own
    # connection and would otherwise not see them.
    with DB(cfg["database"]) as db:
        rows = db.conn.execute("SELECT * FROM replies").fetchall()
        db.conn.execute("DELETE FROM matches")
        for r in rows:
            reply = Reply(reply_id=r["reply_id"], author_handle=r["author_handle"], text=r["text"],
                          caller=r["caller"], url=r["url"], author_followers=r["author_followers"],
                          created_at=r["created_at"], source_post_id=r["source_post_id"],
                          like_count=r["like_count"] or 0, reply_count=r["reply_count"] or 0)
            if not passes_retail(reply, cfg["retail"]):
                continue
            t = (reply.text or "").strip()
            if len(t) < mc or len(t.split()) < mw:
                continue
            if (reply.author_handle or "").lstrip("@").lower() in ex:
                continue
            drop = veto.check(t)
            if drop:
                category, detail = drop
                vetoed[category] += 1
                audit.append({"reply_id": reply.reply_id,
                              "handle": "@" + (reply.author_handle or ""),
                              "url": reply.url, "category": category,
                              "trigger": detail,
                              "quote": t.replace("\n", " ")})
                continue
            hit = classify(reply.text, cfg.themes, th)
            if not hit:
                continue
            theme, weight, phrase, ratio = hit
            s = score(weight, reply.text, reply.like_count, cfg)
            db.save_match(Scored(reply, theme, phrase, ratio, s, bucket(s, cfg)))
            kept += 1

    if args.vetoed_out:
        with open(args.vetoed_out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["reply_id", "handle", "url",
                                              "category", "trigger", "quote"])
            w.writeheader()
            w.writerows(audit)
        print(f"wrote {len(audit)} vetoed row(s) -> {args.vetoed_out}")

    n = export.to_csv(cfg, args.out)
    floor = cfg.get("export_min_intent", "MED")
    detail = "".join(f" {k}={v}" for k, v in sorted(vetoed.items()))
    print(f"replies={len(rows)} kept={kept} vetoed={sum(vetoed.values())}{detail} "
          f"exported(>={floor})={n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
