"""Manual / assisted-collection adapter.

Ingests replies you (or an assistant) pull human-in-the-loop — e.g. the Week-1
method of reading caller threads on your own logged-in session and exporting the
rows. This is the compliant bridge until official API access lands: a person
collects at human pace, the pipeline does the filtering/scoring/export.

Input: a CSV or JSON file. Expected columns/keys (extras ignored):
  reply_id (or url), author_handle, text, caller,
  author_followers, created_at, source_post_id, url, like_count, reply_count
"""
import csv
import json
import os
from ..models import Reply
from .base import Adapter


def _to_reply(row):
    rid = str(row.get("reply_id") or row.get("url") or "").strip()
    if not rid:
        return None
    def i(k):
        v = row.get(k)
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0
    return Reply(
        reply_id=rid,
        author_handle=str(row.get("author_handle", "")).lstrip("@"),
        text=row.get("text", "") or "",
        caller=str(row.get("caller", "")).lstrip("@"),
        url=row.get("url", "") or "",
        author_followers=i("author_followers") or None,
        created_at=row.get("created_at") or None,
        source_post_id=str(row.get("source_post_id", "")),
        like_count=i("like_count"),
        reply_count=i("reply_count"),
    )


class ManualIngestAdapter(Adapter):
    name = "manual"

    def __init__(self, input_path=None, **_):
        self.input_path = input_path

    def fetch(self, cfg, db, log):
        path = self.input_path
        if not path or not os.path.exists(path):
            raise SystemExit(f"[manual] input file not found: {path!r} (pass --input)")
        log.info("[manual] reading %s", path)
        if path.lower().endswith(".json"):
            rows = json.load(open(path, encoding="utf-8"))
        else:
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        for row in rows:
            r = _to_reply(row)
            if r:
                yield r
