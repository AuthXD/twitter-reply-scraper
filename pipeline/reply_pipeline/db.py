"""SQLite store: dedup by reply_id, resume via per-account cursors, run log.

Writes are batched. The previous implementation committed once per reply (and
again per match), so a 400-reply run meant ~800 fsyncs; rows are now flushed
every ``BATCH`` writes and on ``flush``/``close``. Uncommitted rows are still
visible to this connection, so dedup stays correct between flushes.
"""
import json
import sqlite3

from .scoring import ORDER, rank

BATCH = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS replies (
    reply_id TEXT PRIMARY KEY,
    author_handle TEXT, author_followers INTEGER, created_at TEXT,
    text TEXT, caller TEXT, source_post_id TEXT, url TEXT,
    like_count INTEGER, reply_count INTEGER, fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS matches (
    reply_id TEXT PRIMARY KEY, theme TEXT, matched_phrase TEXT,
    ratio REAL, score INTEGER, intent TEXT,
    FOREIGN KEY(reply_id) REFERENCES replies(reply_id)
);
CREATE TABLE IF NOT EXISTS cursors (
    account TEXT PRIMARY KEY, since_id TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, adapter TEXT,
    started_at TEXT DEFAULT CURRENT_TIMESTAMP, finished_at TEXT,
    fetched INTEGER, matched INTEGER
);
-- Persisted LLM verdicts so a reply is judged once, not once per run.
CREATE TABLE IF NOT EXISTS verdicts (
    reply_id TEXT PRIMARY KEY, is_lead INTEGER, theme TEXT, intent TEXT,
    confidence REAL, reason TEXT, judged_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_matches_score ON matches(score DESC);
"""


class DB:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._pending = 0

    # ---------------------------------------------------------------- #
    # Transaction handling.
    # ---------------------------------------------------------------- #
    def _touch(self):
        self._pending += 1
        if self._pending >= BATCH:
            self.flush()

    def flush(self):
        if self._pending:
            self.conn.commit()
            self._pending = 0

    def close(self):
        self.flush()
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    # ---------------------------------------------------------------- #
    # Replies / matches.
    # ---------------------------------------------------------------- #
    def upsert_reply(self, r):
        """Insert reply; return True if new (not a duplicate).

        One statement instead of SELECT-then-INSERT: ``INSERT OR IGNORE`` sets
        rowcount to 0 when the primary key already exists.
        """
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO replies(reply_id,author_handle,author_followers,
               created_at,text,caller,source_post_id,url,like_count,reply_count)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (r.reply_id, r.author_handle, r.author_followers, r.created_at, r.text,
             r.caller, r.source_post_id, r.url, r.like_count, r.reply_count))
        self._touch()
        return cur.rowcount > 0

    def save_match(self, s):
        self.conn.execute(
            """INSERT OR REPLACE INTO matches(reply_id,theme,matched_phrase,ratio,score,intent)
               VALUES(?,?,?,?,?,?)""",
            (s.reply.reply_id, s.theme, s.matched_phrase, s.ratio, s.score, s.intent))
        self._touch()

    # ---------------------------------------------------------------- #
    # Cursors / run log.
    # ---------------------------------------------------------------- #
    def get_cursor(self, account):
        row = self.conn.execute("SELECT since_id FROM cursors WHERE account=?",
                                (account,)).fetchone()
        return row["since_id"] if row else None

    def set_cursor(self, account, since_id):
        self.conn.execute("INSERT OR REPLACE INTO cursors(account,since_id) VALUES(?,?)",
                          (account, since_id))
        self.flush()   # a cursor is a resume point; never leave it uncommitted

    def start_run(self, adapter):
        cur = self.conn.execute("INSERT INTO runs(adapter) VALUES(?)", (adapter,))
        self.flush()
        return cur.lastrowid

    def finish_run(self, run_id, fetched, matched):
        self.conn.execute(
            "UPDATE runs SET finished_at=CURRENT_TIMESTAMP, fetched=?, matched=? WHERE id=?",
            (fetched, matched, run_id))
        self.flush()

    # ---------------------------------------------------------------- #
    # Reads.
    # ---------------------------------------------------------------- #
    def qualified(self, min_intent="LOW"):
        """Matched replies at or above ``min_intent``, best score first.

        The floor is applied in SQL rather than by the caller, so an export of a
        large store no longer materialises rows it is about to discard.
        """
        keep = [name for name, order in ORDER.items() if order >= rank(min_intent)]
        if not keep:
            return []
        placeholders = ",".join("?" * len(keep))
        return self.conn.execute(
            """SELECT r.*, m.theme, m.matched_phrase, m.ratio, m.score, m.intent
               FROM matches m JOIN replies r ON r.reply_id=m.reply_id
               WHERE UPPER(COALESCE(m.intent,'')) IN (%s)
               ORDER BY m.score DESC""" % placeholders, keep).fetchall()

    # ---------------------------------------------------------------- #
    # LLM verdict cache.
    # ---------------------------------------------------------------- #
    def save_verdict(self, reply_id, verdict):
        self.conn.execute(
            """INSERT OR REPLACE INTO verdicts(reply_id,is_lead,theme,intent,confidence,reason)
               VALUES(?,?,?,?,?,?)""",
            (reply_id, 1 if verdict.get("is_lead") else 0, verdict.get("theme"),
             verdict.get("intent"), verdict.get("confidence"), verdict.get("reason")))
        self._touch()

    def get_verdict(self, reply_id):
        row = self.conn.execute(
            "SELECT is_lead,theme,intent,confidence,reason FROM verdicts WHERE reply_id=?",
            (reply_id,)).fetchone()
        if row is None:
            return None
        return {"is_lead": bool(row["is_lead"]), "theme": row["theme"],
                "intent": row["intent"], "confidence": row["confidence"],
                "reason": row["reason"]}
