@echo off
REM ============================================================
REM  Daily reply-scraper pipeline
REM   1) search scrape   2) reply-mining   3) export keyword leads
REM   4) baseline sheet  5) leads.py (LLM refine -> clean leads + sheet)
REM  Stage 5 only refines if llm.enabled=true and the key named by
REM  llm.api_key_env (default NVIDIA_API_KEY) is set in the environment;
REM  otherwise it no-ops and the baseline (stage 4) sheet stands.
REM
REM  NOTE: stages 1-2 use the browser adapters, which drive an authenticated
REM  session against x.com and breach X's Terms of Service. See README.md.
REM ============================================================
set "PROJDIR=%~dp0"
cd /d "%PROJDIR%"
echo ==== run %date% %time% ==== >> "%PROJDIR%scraper.log"
py -3 -u -m reply_pipeline.cli run --adapter search >> "%PROJDIR%scraper.log" 2>&1
py -3 -u -m reply_pipeline.cli run --adapter playwright >> "%PROJDIR%scraper.log" 2>&1
py -3 -u -m reply_pipeline.cli export --out qualified.csv >> "%PROJDIR%scraper.log" 2>&1
py -3 build_lead_sheet.py qualified.csv Leads.xlsx >> "%PROJDIR%scraper.log" 2>&1
py -3 leads.py --in qualified.csv --out leads.csv --sheet Leads.xlsx >> "%PROJDIR%scraper.log" 2>&1
