# Reply Pipeline

Accounts x keyword themes -> a qualified target sheet. Pull replies under a defined
set of accounts, then keep only those whose language matches the intent themes you
configure (e.g. discovery questions, tool requests, regret/FOMO signals).

## Adapters

Four ship, and they differ sharply in how they get their data. Pick deliberately.

| Adapter | Source | Terms of Service |
|---|---|---|
| `manual` | A CSV/JSON you collected by hand from your own logged-in session | Compliant |
| `api` | Official X API v2 recent search via `conversation_id`, needs `X_BEARER_TOKEN` | Compliant |
| `playwright` | Headless Chromium reading reply threads with a saved session | **Violates X's ToS** |
| `search` | The same browser against X search (Latest tab) | **Violates X's ToS** |

> ⚠️ `playwright` and `search` drive an authenticated browser against x.com and
> apply `playwright-stealth` to reduce bot detection. Automated access without
> permission breaches X's Terms of Service, and evading detection is a further
> escalation. They are here because they were built; that is not the same as
> being safe to run. Prefer `api`, or `manual` while you wait for a token.

## Install
```
pip install -r requirements.txt   # PyYAML + requests; rapidfuzz optional
# playwright/search adapters additionally need: pip install playwright playwright-stealth
```

## Configure
Edit `config.yaml` — accounts (WHERE) and keyword themes (WHAT). Non-coders can
change phrases without touching code.

## Run
```
# manual / assisted collection:
python -m reply_pipeline.cli run --adapter manual --input replies.csv --out targets.csv

# official API (once you have a bearer token):
export X_BEARER_TOKEN=...
python -m reply_pipeline.cli run --adapter api --out targets.csv

# export again from stored data:
python -m reply_pipeline.cli export --out targets.csv

# re-apply changed themes/filters to replies already stored (no re-scrape):
python reclassify.py

# stage 2 — LLM refinement into a clean lead list:
python leads.py --in qualified.csv --out leads.csv
```

## Two-stage design
A broad, recall-first **keyword + fuzzy** pass writes `qualified.csv`; an **LLM
intent gate** (`leads.py`) then vetoes sarcasm and negation that keywords cannot
see ("glad I missed that rug" -> dropped). The gate is fail-open: if it is
disabled or the endpoint errors, the keyword verdict stands rather than zeroing
a run. Verdicts are cached in SQLite by `reply_id`, so a cumulative
`qualified.csv` costs API calls only for rows never judged before.

### Fail-open is silent — check the summary line

The gate keeps a reply when the endpoint errors, so a broken stage 2 does not
look broken: it looks like a run where nothing was vetoed. Two defaults made
that easy to hit, and both are now fixed in `config.example.yaml`:

* `timeout` is **per API call**, and 45s was shorter than a single large-model
  call. One 8-post batch measured 195s on NVIDIA's free tier, so every batch
  timed out and every row was kept unjudged.
* `model` defaulted to an 8b model. On a 101-row sample it vetoed **1** row;
  `meta/llama-3.3-70b-instruct` vetoed **40** of the same rows.

`leads.py` now reports failures explicitly rather than warning once and moving
on:

```
kept=61  llm_vetoed=40  no_opinion_kept=27  [!] 3/11 batches failed -> 27 row(s) kept UNJUDGED
```

`no_opinion_kept` on its own is not a problem — it also counts low-confidence
verdicts. The `[!]` clause is the one that means calls are failing.

Batch size is a trade-off between two opposing limits: free-tier latency is
dominated by per-call queue time, which favours **large** batches, while the
server returns `HTTP 504` when a single call runs too long, which favours
**small** ones. Verdicts cache by `reply_id` and a failed batch is never
cached, so re-running `leads.py` **without** `--refresh` retries only the rows
that never got a verdict, and converges.

## Precision filters

Keyword themes decide what *looks* like a lead; the `veto` block in `config.yaml`
decides what can never be one. Vetoes run before scoring, so a dropped reply
never reaches the sheet, and each drop is logged with its category and trigger.

| Category | Catches |
|---|---|
| `hate` | Hateful content. Checked **first and unconditionally** — dropped even if the same post also reads as a perfect lead. |
| `promo` | Shills: presales, call channels, invite links, pasted contract addresses. |
| `competitor` | Accounts marketing their own rival tool. Someone selling a solution is not someone who needs one. |
| `announcement` | Broadcasting a result: launches, "called it", gain brags (`up 40x`, `did 300%`). Someone performing a win is not someone with a problem. |
| `off_topic` | The positive gate: the post must be about crypto trading at all. |
| `not_asking` | The second positive gate: the post must read as *seeking* — a question, a request, or a first-person need. |

`off_topic` is the one a blocklist cannot replace. Intent phrasing shows up in
unrelated universes — "best bot" in a medical update, "what tool do you use"
from a backend developer — and nothing in those posts is *bad*, so only a
positive domain requirement removes them. A cashtag (`$WIF`) counts as a signal.

### Asking vs announcing

`announcement` and `not_asking` are deliberately separate categories even though
they enforce one idea, because the fix for each is the opposite: a wrong drop in
`announcement` means the broadcast list is too wide, a wrong drop in
`not_asking` means the ask vocabulary is too narrow. One merged bucket would
make `vetoed.csv` useless for tuning.

The ask gate is **not** question-mark-only. `"missed another 10x again smh"` and
`"wish i aped that"` ask nothing outright and are the highest-intent replies in
the sheet, so first-person pain counts as asking — while the same pain in the
third person (`"he keeps missing these"`) does not, because a spectator
narrating someone else's trade is not a buyer.

Pain phrasing is matched **fuzzily**, at a threshold (`ask_fuzzy_threshold: 75`)
deliberately looser than theme matching (86). The gate only ever *keeps* a
reply — the announcement filters and the LLM gate still screen whatever it lets
through — whereas a reply dropped at stage 1 is unrecoverable. 75 is what keeps
a typo'd lead alive: `"missd anethr runner ugh"` scores 83 against `missed`.

Matching is word-bounded, so `ass` does not match `class`. The hate list lives
in a git-ignored file (`veto.hate_terms_file`) rather than in the repo; if the
path is set but missing the run fails loudly rather than silently disabling the
filter.

To clean an existing lead list without re-scraping — tighten the lists, then:

```
python reclassify.py --vetoed-out vetoed.csv   # re-judge everything, audit the drops
```

`vetoed.csv` lists every removed reply with its category and the exact term that
triggered it, which is what makes the surviving list defensible.

The LLM gate (stage 2) enforces the same categories in prose, catching the
cases wordlists miss.

## Features
Async-free, dependency-light. SQLite store with **dedup** (by reply_id),
**resume** (per-account cursors), batched writes, run log, keyword + **fuzzy**
matching, intent scoring (HIGH/MED/LOW), retail filters (skip mega-influencers &
bots), structured logging, CSV export, unit tests.

## Test
```
python -m unittest discover -s tests -v          # from pipeline/
python -m unittest discover -s tests -v          # and from the repo root, for x_scraper
```
