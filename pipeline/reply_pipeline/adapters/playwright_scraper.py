"""Browser-automation adapter for authorized X (Twitter) reply collection.

This adapter drives a real Chromium instance (via Playwright + playwright-stealth)
to read the public reply threads under a configured set of caller accounts. It is
intended only for accounts you are authorized to monitor.

Design notes
------------
* ``Adapter.fetch`` is a *synchronous* generator, but Playwright's API here is
  async. We therefore keep a single event loop and a single browser/context alive
  for the whole run, scrape one account at a time inside ``loop.run_until_complete``,
  and yield its ``Reply`` objects back to the pipeline before moving on. That lets
  us honour the per-account cursor (resume) contract while reusing one browser.
* Authentication is never done with a username/password here. Instead we load a
  pre-authenticated ``x_session.json`` (produced by ``setup_session`` below) as the
  browser context's ``storage_state`` so the session cookies are injected directly.
* Extraction relies on stable ``data-testid`` hooks (``tweet``, ``User-Name``,
  ``tweetText``, ``reply``, ``like``) rather than brittle nested ``div`` classes,
  because X rewrites its CSS class names constantly.
* Any per-account failure is logged and swallowed so one bad account cannot crash
  the whole run.

Setup (run once, interactively)::

    python -m reply_pipeline.adapters.playwright_scraper
    # or: from ...playwright_scraper import setup_session; asyncio.run(setup_session())
"""
import asyncio
import os
import random
from urllib.parse import quote

from ..ids import id_leq, max_id
from ..models import Reply
from ..scroll import ScrollTracker, parse_metric, pick_permalink
from .base import Adapter

# Where the injected, pre-authenticated cookies live. Overridable via env so the
# file can sit outside the repo.
SESSION_FILE = os.environ.get("X_SESSION_FILE", "x_session.json")

# Throttle bounds (seconds). Randomised waits between scrolls / thread opens make
# the traffic look like human reading and keep us under rate limits.
THROTTLE_MIN = 2.0
THROTTLE_MAX = 5.5

# How far to scroll a profile / thread before giving up on lazy-loaded content.
MAX_PROFILE_SCROLLS = 8
MAX_THREAD_SCROLLS = 12
MAX_SEARCH_SCROLLS = 12

# Consecutive scrolls that surface nothing new before we call a feed exhausted.
MAX_STALLED_SCROLLS = 2


async def _human_pause():
    """Sleep a randomised human-like interval."""
    await asyncio.sleep(random.uniform(THROTTLE_MIN, THROTTLE_MAX))


class PlaywrightAdapter(Adapter):
    """Scrape public reply threads for authorized caller accounts via a browser."""

    name = "playwright"

    def __init__(self, posts_per_account=5, headless=True,
                 session_file=SESSION_FILE, **_):
        self.posts_per_account = posts_per_account
        self.headless = headless
        self.session_file = session_file

    # ------------------------------------------------------------------ #
    # Sync entry point required by the Adapter contract.
    # ------------------------------------------------------------------ #
    def fetch(self, cfg, db, log):
        """Yield Reply objects for every account in ``cfg.accounts``.

        Keeps one event loop + browser alive for the whole run, scraping each
        account to completion before yielding so the per-account cursor can be
        advanced between accounts.
        """
        if not os.path.exists(self.session_file):
            log.error("[playwright] session file %r not found; run setup_session() "
                      "first. Skipping run.", self.session_file)
            return

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            pw, browser, context = loop.run_until_complete(self._start_browser(log))
            if context is None:
                return
            try:
                log.info("[playwright] starting run over %d account(s)", len(cfg.accounts))
                for handle in cfg.accounts:
                    handle = str(handle).lstrip("@")
                    since = db.get_cursor(handle)
                    log.info("[playwright] scraping @%s ...", handle)
                    try:
                        replies, newest_id = loop.run_until_complete(
                            self._scrape_account(context, handle, since, log))
                    except Exception as exc:  # never let one account kill the loop
                        log.warning("[playwright] @%s failed, skipping: %s", handle, exc)
                        continue
                    log.info("[playwright] @%s: %d reply(ies) collected", handle, len(replies))
                    for r in replies:
                        yield r
                    if newest_id:
                        db.set_cursor(handle, newest_id)
            finally:
                loop.run_until_complete(self._stop_browser(pw, browser, context, log))
        finally:
            loop.close()

    # ------------------------------------------------------------------ #
    # Browser lifecycle.
    # ------------------------------------------------------------------ #
    async def _start_browser(self, log):
        from playwright.async_api import async_playwright

        pw = await async_playwright().start()
        try:
            browser = await pw.chromium.launch(headless=self.headless)
            # Inject the pre-authenticated cookies via storage_state — no typing
            # of any username/password anywhere.
            context = await browser.new_context(storage_state=self.session_file)
            await self._apply_stealth(context, log)
            log.info("[playwright] browser ready; session from %s", self.session_file)
            return pw, browser, context
        except Exception as exc:
            log.error("[playwright] failed to start browser: %s", exc)
            await pw.stop()
            return pw, None, None

    async def _apply_stealth(self, context, log):
        """Apply playwright-stealth, tolerating either of its API shapes."""
        try:
            try:
                # Newer API: Stealth().apply_stealth_async(context)
                from playwright_stealth import Stealth
                await Stealth().apply_stealth_async(context)
                return
            except ImportError:
                pass
            # Older API: stealth_async(page) — applied per page instead.
            from playwright_stealth import stealth_async  # noqa: F401
            self._stealth_async = stealth_async
        except Exception as exc:
            log.warning("[playwright] stealth not applied (%s); continuing", exc)

    async def _new_page(self, context):
        page = await context.new_page()
        stealth = getattr(self, "_stealth_async", None)
        if stealth is not None:
            try:
                await stealth(page)
            except Exception:
                pass
        return page

    async def _stop_browser(self, pw, browser, context, log):
        for closer in (context, browser):
            try:
                if closer is not None:
                    await closer.close()
            except Exception:
                pass
        try:
            await pw.stop()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Scraping.
    # ------------------------------------------------------------------ #
    async def _scrape_account(self, context, handle, since, log):
        """Return ``(replies, newest_post_id)`` for a single caller account."""
        replies = []
        page = await self._new_page(context)
        try:
            url = f"https://x.com/{handle}"
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                await page.wait_for_selector('[data-testid="tweet"]', timeout=30_000)
            except Exception as exc:
                log.warning("[playwright] could not load @%s (%s); skipping", handle, exc)
                return replies, None

            post_ids = await self._collect_post_ids(page, handle, since, log)
            newest_id = max_id(post_ids)
            log.info("[playwright] @%s: %d source post(s) to read", handle, len(post_ids))

            for pid in post_ids:
                try:
                    thread_replies = await self._scrape_thread(context, handle, pid, log)
                    replies.extend(thread_replies)
                except Exception as exc:
                    log.warning("[playwright] thread %s under @%s failed: %s",
                                pid, handle, exc)
                    continue
            return replies, newest_id
        finally:
            try:
                await page.close()
            except Exception:
                pass

    async def _collect_post_ids(self, page, handle, since, log):
        """Scroll the profile timeline and gather the account's own post ids."""
        seen = []
        seen_set = set()
        handle_l = handle.lower()
        tracker = ScrollTracker(MAX_STALLED_SCROLLS)

        for _ in range(MAX_PROFILE_SCROLLS):
            articles = await page.query_selector_all('article[data-testid="tweet"]')
            for art in articles:
                pid, author = await self._article_id_and_author(art)
                if not pid or pid in seen_set:
                    continue
                # Only the account's *own* posts anchor a conversation we want.
                if author and author.lower() != handle_l:
                    continue
                # Resume: skip posts we already handled on an earlier run. Note
                # this cannot short-circuit the scroll — a pinned tweet sits at
                # the top of the timeline and is often older than the cursor.
                if since and id_leq(pid, since):
                    continue
                seen_set.add(pid)
                seen.append(pid)
                if len(seen) >= self.posts_per_account:
                    break

            if len(seen) >= self.posts_per_account:
                break
            # Nothing new for two scrolls means the timeline is exhausted (or
            # everything below the fold predates the cursor) — stop paying the
            # randomised pause for each remaining scroll.
            if tracker.record(len(seen_set)):
                break
            await page.mouse.wheel(0, 3200)
            await _human_pause()  # throttle between scrolls

        return seen

    async def _scrape_thread(self, context, caller, post_id, log):
        """Open a post's conversation and extract reply tweets."""
        replies = []
        page = await self._new_page(context)
        try:
            url = f"https://x.com/{caller}/status/{post_id}"
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                await page.wait_for_selector('[data-testid="tweet"]', timeout=30_000)
            except Exception as exc:
                log.warning("[playwright] could not open thread %s (%s); skipping",
                            post_id, exc)
                return replies

            await _human_pause()  # throttle before reading the thread

            seen_ids = set()
            tracker = ScrollTracker(MAX_STALLED_SCROLLS)
            for _ in range(MAX_THREAD_SCROLLS):
                articles = await page.query_selector_all('article[data-testid="tweet"]')
                for art in articles:
                    pid, author = await self._article_id_and_author(art)
                    if not pid or pid in seen_ids:
                        continue
                    # The source post itself shares this id; skip it.
                    if pid == post_id:
                        seen_ids.add(pid)
                        continue
                    seen_ids.add(pid)
                    reply = await self._article_to_reply(art, pid, author, caller, post_id)
                    if reply is not None:
                        replies.append(reply)

                # Stop once scrolling stops surfacing new replies. The previous
                # condition compared a counter against itself and was therefore
                # never true, so every thread burned the full scroll budget —
                # each one costing a 2-5.5s randomised pause.
                if tracker.record(len(seen_ids)):
                    break
                await page.mouse.wheel(0, 3200)
                await _human_pause()  # throttle between scrolls
            return replies
        finally:
            try:
                await page.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # Element -> data helpers (defensive, data-testid based).
    # ------------------------------------------------------------------ #
    async def _article_id_and_author(self, art):
        """Extract (tweet_id, author_handle) from a tweet <article>.

        An article can hold several /status/ links — a quoted tweet's permalink
        typically comes first in DOM order — so taking the first one attributes
        the reply to the quoted author. Only the tweet's own permalink wraps its
        <time> element, so that is the one we prefer.
        """
        pid = None
        author = None
        try:
            candidates = []
            for link in await art.query_selector_all('a[href*="/status/"]'):
                href = await link.get_attribute("href") or ""
                wraps_time = await link.query_selector("time") is not None
                candidates.append((href, wraps_time))
            pid, author = pick_permalink(candidates)
        except Exception:
            pass
        if author is None:
            author = await self._author_from_testid(art)
        return pid, author

    async def _author_from_testid(self, art):
        try:
            block = await art.query_selector('[data-testid="User-Name"]')
            if not block:
                return None
            text = await block.inner_text()
            # User-Name renders "Display Name\n@handle\n·\ntime"; grab the @handle.
            for token in text.split():
                if token.startswith("@"):
                    return token[1:]
        except Exception:
            return None
        return None

    async def _article_to_reply(self, art, pid, author, caller, source_post_id):
        try:
            text = ""
            text_el = await art.query_selector('[data-testid="tweetText"]')
            if text_el:
                text = (await text_el.inner_text()).strip()

            created_at = None
            time_el = await art.query_selector("time")
            if time_el:
                created_at = await time_el.get_attribute("datetime")

            like_count = await self._metric(art, "like")
            reply_count = await self._metric(art, "reply")

            handle = author or ""
            url = f"https://x.com/{handle}/status/{pid}" if handle else \
                  f"https://x.com/i/status/{pid}"

            return Reply(
                reply_id=pid,
                author_handle=handle,
                text=text,
                caller=caller,
                url=url,
                author_followers=None,   # not exposed on the thread view
                created_at=created_at,
                source_post_id=source_post_id,
                like_count=like_count,
                reply_count=reply_count,
            )
        except Exception:
            return None

    async def _metric(self, art, testid):
        try:
            btn = await art.query_selector(f'[data-testid="{testid}"]')
            if not btn:
                return 0
            label = await btn.get_attribute("aria-label")
            return parse_metric(label)
        except Exception:
            return 0


class PlaywrightSearchAdapter(PlaywrightAdapter):
    """Scrape X search results (Latest tab) for intent queries.

    Where PlaywrightAdapter mines the reply sections of specific accounts, this
    adapter finds people posting the pain *anywhere* on X — it runs each query in
    ``cfg["searches"]`` against https://x.com/search (Latest), and yields every
    result tweet as a Reply. The tweet author is the potential lead; ``caller`` is
    set to the query label so the lead sheet shows which query surfaced them.

    Resume: a per-query cursor ("search:<label>") means each run only picks up
    tweets newer than the last one seen for that query.
    """

    name = "search"

    def __init__(self, results_per_search=40, headless=True,
                 session_file=SESSION_FILE, **kw):
        super().__init__(headless=headless, session_file=session_file, **kw)
        self.results_per_search = results_per_search

    @staticmethod
    def _parse_searches(items):
        """Accept list of strings or {label, query} dicts -> [(label, query)]."""
        out = []
        for it in items or []:
            if isinstance(it, dict):
                q = it.get("query")
                if q:
                    out.append((it.get("label") or q[:24], q))
            elif isinstance(it, str) and it.strip():
                out.append((it.strip()[:24], it.strip()))
        return out

    def fetch(self, cfg, db, log):
        if not os.path.exists(self.session_file):
            log.error("[search] session file %r not found; create x_session.json first.",
                      self.session_file)
            return
        searches = self._parse_searches(cfg.get("searches", []))
        if not searches:
            log.error("[search] no 'searches' configured in config.yaml; nothing to do.")
            return

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            pw, browser, context = loop.run_until_complete(self._start_browser(log))
            if context is None:
                return
            try:
                log.info("[search] running %d query(ies)", len(searches))
                for label, query in searches:
                    key = "search:" + label
                    since = db.get_cursor(key)
                    log.info("[search] querying '%s' ...", label)
                    try:
                        replies, newest = loop.run_until_complete(
                            self._scrape_search(context, label, query, since, log))
                    except Exception as exc:
                        log.warning("[search] '%s' failed, skipping: %s", label, exc)
                        continue
                    log.info("[search] '%s': %d result(s)", label, len(replies))
                    for r in replies:
                        yield r
                    if newest:
                        db.set_cursor(key, newest)
            finally:
                loop.run_until_complete(self._stop_browser(pw, browser, context, log))
        finally:
            loop.close()

    async def _scrape_search(self, context, label, query, since, log):
        """Run one query against the Latest tab; return (replies, newest_id)."""
        replies = []
        page = await self._new_page(context)
        try:
            url = f"https://x.com/search?q={quote(query)}&src=typed_query&f=live"
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                await page.wait_for_selector('[data-testid="tweet"]', timeout=30_000)
            except Exception as exc:
                log.warning("[search] '%s' could not load (%s); skipping", label, exc)
                return replies, None

            await _human_pause()
            seen = set()
            newest = None
            tracker = ScrollTracker(MAX_STALLED_SCROLLS)
            for _ in range(MAX_SEARCH_SCROLLS):
                if len(replies) >= self.results_per_search:
                    break
                arts = await page.query_selector_all('article[data-testid="tweet"]')
                for art in arts:
                    pid, author = await self._article_id_and_author(art)
                    if not pid or pid in seen:
                        continue
                    seen.add(pid)
                    newest = max_id([newest, pid])
                    if since and id_leq(pid, since):
                        continue  # already seen on a previous run
                    reply = await self._article_to_reply(art, pid, author, label, "")
                    if reply is not None:
                        replies.append(reply)
                    if len(replies) >= self.results_per_search:
                        break
                # A query whose results are exhausted should not keep scrolling
                # an empty feed for the rest of its budget.
                if tracker.record(len(seen)):
                    break
                await page.mouse.wheel(0, 3200)
                await _human_pause()  # throttle between scrolls
            return replies, newest
        finally:
            try:
                await page.close()
            except Exception:
                pass


# ---------------------------------------------------------------------- #
# One-time interactive session capture.
# ---------------------------------------------------------------------- #
async def setup_session(session_file=SESSION_FILE):
    """Open a visible browser, let you log in by hand, then save the session.

    Run this once. A headed Chromium window opens on https://x.com; log in
    normally in that window, then return to the terminal and press Enter. The
    authenticated storage state (cookies + local storage) is written to
    ``session_file`` for the adapter to inject later.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://x.com", wait_until="domcontentloaded")

        print("\n" + "=" * 60)
        print("A browser window is open at https://x.com.")
        print("Log in manually in that window, then come back here.")
        print("=" * 60)
        # input() is blocking; run it off the event loop so the browser stays live.
        await asyncio.get_event_loop().run_in_executor(
            None, input, "Press Enter here once you are fully logged in... ")

        await context.storage_state(path=session_file)
        print(f"Saved authenticated session -> {session_file}")
        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(setup_session())
