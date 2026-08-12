# Twitter Reply Scraper

A configurable tool for mining **X (Twitter) reply sections** for leads. Point it at
a set of accounts (or search queries), and it keeps only the replies whose language
signals an intent you care about — questions, buying signals, pain points, regret —
then runs an **LLM gate** to strip out sarcasm and negation, producing a clean,
ranked, qualified lead sheet.

Everything domain-specific (which accounts to mine, which phrases count, how to
score them, what reply to draft) lives in config you supply — the code stays generic.

> **Two-stage design:** a fast, broad **keyword + fuzzy** pass (recall-first)
> followed by an **LLM intent gate** that confirms real leads and vetoes
> negation/sarcasm ("glad I missed that" → not a lead).

## Repository layout

```
twitter-reply-scraper/
├── pipeline/                          # the active pipeline (start here)
│   ├── config.example.yaml            # template: accounts, themes, filters, LLM settings
│   ├── reply_pipeline/                # package: cli, pipeline, db, filters, scoring, llm_filter, ids, scroll, adapters/
│   ├── leads.py                       # stage 2: LLM refinement (qualified.csv -> leads.csv + sheet)
│   ├── build_lead_sheet.py            # build the .xlsx lead sheet from a CSV
│   ├── build_session_from_cookies.py  # turn an exported browser cookies file into x_session.json
│   ├── run_scraper.bat                # daily end-to-end run
│   ├── requirements.txt
│   ├── sample_manual_replies.csv      # synthetic example input
│   ├── .env.example                   # template for your secrets
│   └── README.md                      # pipeline-specific details
├── tests/                             # tests for the root scripts
└── (root scripts)
    ├── x_scraper.py                   # standalone twscrape-based scraper (legacy/experimental)
    ├── proof_tracker.py               # optional: enrich a log with market data from Dexscreener
    └── scraper_config.example.py      # template config for the standalone scraper
```

## Setup

```bash
cd pipeline
python -m venv .venv
# Windows:  .venv\Scripts\Activate.ps1   |   macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt          # PyYAML + requests; rapidfuzz optional
```

### Configuration (your accounts stay private)

The account lists, search queries, and reply templates are **yours** — they ship only
as `*.example` templates so nothing personal is committed. Copy them and fill in your
own values; the real files are git-ignored.

```bash
cp pipeline/config.example.yaml pipeline/config.yaml     # pipeline config
cp scraper_config.example.py scraper_config.py           # standalone-scraper config
# Windows PowerShell:  Copy-Item pipeline/config.example.yaml pipeline/config.yaml
```

### Secrets (never committed)

No keys or session cookies are tracked. You supply your own, and `.gitignore` keeps
them out of git.

1. **Copy the env template and fill in your key:**
   ```bash
   cp pipeline/.env.example pipeline/.env
   ```
2. **NVIDIA NIM API key** — required for the LLM gate. Get a free key at
   [build.nvidia.com](https://build.nvidia.com), then set it in your environment
   (the code reads it from `NVIDIA_API_KEY`, not from the `.env` file directly):
   ```powershell
   setx NVIDIA_API_KEY "nvapi-...your-key..."      # Windows (open a NEW terminal after)
   ```
   ```bash
   export NVIDIA_API_KEY="nvapi-...your-key..."     # macOS/Linux
   ```
   Leave `llm.api_key` **empty** in `config.yaml` — the key comes from the env var.
3. **X session** — the Playwright scraper authenticates with a saved browser
   session, not a password. Export your logged-in x.com cookies (e.g. via the
   Cookie-Editor extension) to `cookies.json`, then:
   ```bash
   python build_session_from_cookies.py cookies.json
   ```
   This writes `x_session.json` (git-ignored). The `auth_token` inside it is a live
   credential — keep it private.
4. **X API bearer token** (optional) — only if you use the official `api` adapter.
   Set `X_BEARER_TOKEN` in your environment.

### Standalone scraper auth (twscrape, direct credentials)

The **standalone** `x_scraper.py` uses [twscrape](https://github.com/vladkens/twscrape)
and can authenticate with account credentials instead of an exported cookie session:

- **Authentication** — add a burner account programmatically by supplying
  `username:password:email:email_pw` (instead of a cookie string), then log in:
  ```bash
  twscrape add_accounts accounts.txt username:password:email:email_pw
  twscrape login_accounts
  ```
- **Efficiency** — twscrape hits X's internal GraphQL API and returns structured
  tweets directly, so there's no HTML parsing (no BeautifulSoup). The scrape stays
  fast and lightweight.

> ⚠️ **These are real, full-account credentials — far more sensitive than a cookie.**
> `accounts.txt` (plaintext login) and `accounts.db` (twscrape's session store) are
> **git-ignored** and must never be committed. Use a **burner** account, never your
> main — multi-account automation is against X's ToS and risks a ban.

## Configure

Edit `pipeline/config.yaml` (your copy of the template) — no code changes needed:

- `accounts` — whose reply sections to mine
- `themes` — keyword phrases per intent, with weights
- `searches` — X search queries for the `search` adapter
- `retail`, `scoring`, `fuzzy_threshold` — precision/quality filters
- `llm` — enable the intent gate, pick the model/endpoint

## Run

```bash
cd pipeline

# assisted / manual collection (compliant bridge — ingest human-collected replies):
python -m reply_pipeline.cli run --adapter manual --input sample_manual_replies.csv --out qualified.csv

# official X API v2 adapter (needs X_BEARER_TOKEN):
python -m reply_pipeline.cli run --adapter api --out qualified.csv

# stage 2 — LLM refinement into a clean lead list:
python leads.py --in qualified.csv --out leads.csv

# full daily pipeline (Windows):
run_scraper.bat
```

## Test

Two suites — one per package root:

```bash
cd pipeline && python -m unittest discover -s tests -v   # the pipeline
cd ..      && python -m unittest discover -s tests -v   # the root scripts
```

## What is git-ignored (kept private)

`.gitignore` excludes everything that carries secrets or personal data, so it can
never be committed:

- **Your config:** `config.yaml`, `scraper_config.py` (accounts & call lists) — only
  the `*.example` templates are tracked
- **Secrets/sessions:** `.env`, `x_session.json` / `*_session.json`, `cookies.*`,
  `accounts.txt`, `accounts.db`
- **Scraped data & outputs:** `*.db`, `*.csv` (except the synthetic sample),
  `*.xlsx` / `*.docx` (lead sheets, logs), `*.log`, `seen_handles.json`
- **Build noise:** `__pycache__/`, virtualenvs, caches

Only source code, the `*.example` templates, the docs, and the synthetic
`sample_manual_replies.csv` are tracked.

## Notes

Use authorized data sources and respect X's Terms of Service and rate limits. The
LLM gate is fail-open — if the API is disabled or errors, the pipeline keeps the
keyword verdict rather than dropping a run.
