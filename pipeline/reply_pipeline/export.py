"""Export qualified replies (>= export_min_intent) to CSV for the target sheet."""
import csv
from .db import DB

COLUMNS = ["reply_id", "handle", "profile_url", "source_post_url", "created_at",
           "followers", "quote", "caller", "theme", "matched_phrase", "intent", "score"]


def to_csv(cfg, out_path):
    """Write every match at or above `export_min_intent` to `out_path`.

    The intent floor is applied by the query (see DB.qualified), so this no
    longer pulls rows out of SQLite only to drop them here.
    """
    min_intent = cfg.get("export_min_intent", "MED")
    n = 0
    with DB(cfg["database"]) as db, \
            open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in db.qualified(min_intent):
            handle = r["author_handle"] or ""
            w.writerow({
                # reply_id travels with the row so stage 2 can cache its LLM
                # verdict per reply instead of re-judging the whole file.
                "reply_id": r["reply_id"],
                "handle": "@" + handle,
                "profile_url": f"https://x.com/{handle}",
                "source_post_url": r["url"],
                "created_at": (r["created_at"] or "")[:10],
                "followers": r["author_followers"],
                "quote": (r["text"] or "").replace("\n", " ").strip(),
                "caller": "@" + (r["caller"] or ""),
                "theme": r["theme"],
                "matched_phrase": r["matched_phrase"],
                "intent": r["intent"],
                "score": r["score"],
            })
            n += 1
    return n
