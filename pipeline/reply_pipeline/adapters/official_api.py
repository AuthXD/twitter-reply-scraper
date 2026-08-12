"""Official X API v2 adapter (authorized).

Requires a bearer token with access to recent search (conversation_id):
  export X_BEARER_TOKEN=...    # never hardcode; read from env
Flow per account: resolve id -> recent original tweets (since_id from cursor) ->
recent-search replies via conversation_id -> Reply objects. Handles 429/5xx with
exponential backoff. Resumes from the last tweet id stored per account.
"""
import os
import time
from ..ids import max_id
from ..models import Reply
from .base import Adapter

BASE = "https://api.twitter.com/2"


class OfficialAPIAdapter(Adapter):
    name = "api"

    def __init__(self, tweets_per_account=5, replies_per_post=100, **_):
        self.tweets_per_account = tweets_per_account
        self.replies_per_post = replies_per_post
        self._session = None

    def _client(self):
        import requests  # imported lazily so the manual adapter needs no requests
        if self._session is None:
            token = os.environ.get("X_BEARER_TOKEN")
            if not token:
                raise SystemExit("Set X_BEARER_TOKEN (official API bearer token).")
            self._session = requests.Session()
            self._session.headers["Authorization"] = f"Bearer {token}"
        return self._session

    def _get(self, path, params, log, tries=5):
        s = self._client()
        for attempt in range(tries):
            resp = s.get(f"{BASE}{path}", params=params, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = min(2 ** attempt, 60)
                # honor reset header when present
                reset = resp.headers.get("x-rate-limit-reset")
                if resp.status_code == 429 and reset:
                    wait = max(wait, int(reset) - int(time.time()) + 1)
                log.warning("[api] %s -> %s, backoff %ss", path, resp.status_code, wait)
                time.sleep(max(1, wait))
                continue
            raise RuntimeError(f"[api] {path} {resp.status_code}: {resp.text[:200]}")
        raise RuntimeError(f"[api] {path} failed after {tries} tries")

    def _user_id(self, handle, log):
        d = self._get(f"/users/by/username/{handle}", {}, log)
        return d.get("data", {}).get("id")

    def fetch(self, cfg, db, log):
        for handle in cfg.accounts:
            handle = handle.lstrip("@")
            uid = self._user_id(handle, log)
            if not uid:
                log.warning("[api] no user id for @%s", handle)
                continue
            since = db.get_cursor(handle)
            params = {"max_results": self.tweets_per_account,
                      "tweet.fields": "conversation_id,created_at",
                      "exclude": "replies,retweets"}
            if since:
                params["since_id"] = since
            posts = self._get(f"/users/{uid}/tweets", params, log).get("data", [])
            for post in posts:
                yield from self._replies(post, handle, log)
            # Numeric comparison — ids of differing length sort wrongly as strings.
            newest = max_id([since] + [p.get("id") for p in posts])
            if newest:
                db.set_cursor(handle, newest)

    def _replies(self, post, caller, log):
        params = {
            "query": f"conversation_id:{post['id']}",
            "max_results": min(self.replies_per_post, 100),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id",
            "expansions": "author_id",
            "user.fields": "public_metrics,username",
        }
        data = self._get("/tweets/search/recent", params, log)
        users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
        for tw in data.get("data", []):
            u = users.get(tw.get("author_id"), {})
            pm = tw.get("public_metrics", {})
            uname = u.get("username", "")
            yield Reply(
                reply_id=tw["id"],
                author_handle=uname,
                text=tw.get("text", ""),
                caller=caller,
                url=f"https://x.com/{uname}/status/{tw['id']}" if uname else "",
                author_followers=u.get("public_metrics", {}).get("followers_count"),
                created_at=tw.get("created_at"),
                source_post_id=post["id"],
                like_count=pm.get("like_count", 0),
                reply_count=pm.get("reply_count", 0),
            )
