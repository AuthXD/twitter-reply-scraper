#!/usr/bin/env python3
"""Stage 2: LLM refinement of the keyword output.

Reads qualified.csv (the cheap keyword pass), sends each row to the configured
LLM (NVIDIA NIM by default), keeps only the ones the model confirms are real
leads, and writes a clean leads.csv — then rebuilds Leads.xlsx from it.

This is the 'sort through the good ones' step: it kills sarcasm/negation/
commentary that keywords can't see ("glad I missed that rug" -> dropped).

Verdicts are cached in the SQLite store, keyed by reply_id. qualified.csv is
cumulative — it re-exports every match ever made — so without the cache each run
re-sent the entire backlog to the API. Only rows never judged before cost a call.

Setup (NVIDIA NIM):
    1) Get a key at https://build.nvidia.com
    2) set the key:  (Windows)  setx NVIDIA_API_KEY "nvapi-..."
    3) in config.yaml: llm.enabled: true
Run:
    py -3 leads.py                 # qualified.csv -> leads.csv (+ sheet)
    py -3 leads.py --in qualified.csv --out leads.csv
    py -3 leads.py --refresh       # ignore cached verdicts and re-judge
"""
import argparse
import csv
import logging
import subprocess
import sys

from reply_pipeline.config import Config
from reply_pipeline.db import DB
from reply_pipeline.llm_filter import LLMFilter
from reply_pipeline.scoring import rank


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _load_cached(db, rows, refresh):
    """Return (verdicts, todo_indexes) — cached verdicts, and what still needs judging."""
    verdicts = [None] * len(rows)
    todo = []
    for i, r in enumerate(rows):
        rid = (r.get("reply_id") or "").strip()
        cached = None if (refresh or not rid) else db.get_verdict(rid)
        if cached is None:
            todo.append(i)
        else:
            verdicts[i] = cached
    return verdicts, todo


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default="qualified.csv")
    ap.add_argument("--out", dest="out", default="leads.csv")
    ap.add_argument("--sheet", default="Leads.xlsx")
    ap.add_argument("--refresh", action="store_true",
                    help="ignore cached verdicts and re-judge every row")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args(argv)

    cfg = Config.load(args.config)
    try:
        llm = LLMFilter.from_config(cfg)
    except ValueError as e:
        print(f"LLM not configured: {e}", file=sys.stderr)
        return 2
    if not llm.enabled:
        print("llm.enabled is false in config.yaml — nothing to refine. "
              "Set it true to build leads.csv.", file=sys.stderr)
        return 2

    try:
        with open(args.src, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        print(f"{args.src} not found — run a scrape first.", file=sys.stderr)
        return 1
    if not rows:
        print(f"{args.src} is empty — run a scrape first.", file=sys.stderr)
        return 1

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log = logging.getLogger("leads")
    names = [t["name"] for t in cfg.themes]

    with DB(cfg["database"]) as db:
        verdicts, todo = _load_cached(db, rows, args.refresh)
        cached_count = len(rows) - len(todo)
        if todo:
            print(f"Refining {len(todo)} new candidate(s) via {llm.label} "
                  f"({cached_count} already judged) ...")
            fresh = llm.classify_batch([rows[i].get("quote", "") for i in todo], names, log)
            for i, v in zip(todo, fresh):
                verdicts[i] = v
                rid = (rows[i].get("reply_id") or "").strip()
                if v is not None and rid:
                    db.save_verdict(rid, v)   # never cache a "no opinion" outage
        else:
            print(f"All {cached_count} candidate(s) already judged — no API calls needed.")

    kept = []
    vetoed = no_opinion = 0
    for r, v in zip(rows, verdicts):
        if v is None:                 # backend down / low confidence -> keep (fail-open)
            no_opinion += 1
        elif not v["is_lead"]:
            vetoed += 1
            continue
        else:
            r["intent"] = v["intent"]
            r["theme"] = v["theme"] or r.get("theme", "")
            r["llm_reason"] = v["reason"]
        kept.append(r)

    fields = list(rows[0].keys())
    if "llm_reason" not in fields:
        fields.append("llm_reason")
    kept.sort(key=lambda x: (-rank(x.get("intent")), -_int(x.get("score"))))
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in kept:
            r.setdefault("llm_reason", "")
            w.writerow(r)

    err = ""
    if llm.failed_batches:
        err = (f"  [!] {llm.failed_batches}/{llm.batches_attempted} batches failed -> "
               f"{llm.rows_unjudged_by_error} row(s) kept UNJUDGED; re-run without "
               f"--refresh to retry only those")
    print(f"kept={len(kept)}  llm_vetoed={vetoed}  no_opinion_kept={no_opinion}{err}"
          f"  -> {args.out}")

    # rebuild the sheet from the clean leads
    try:
        subprocess.run([sys.executable, "build_lead_sheet.py", args.out, args.sheet],
                       check=False)
    except Exception as e:
        print(f"(sheet rebuild skipped: {e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
