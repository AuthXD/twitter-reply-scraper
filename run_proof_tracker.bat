@echo off
REM ============================================================
REM  Proof-log auto-tracker launcher (Windows Task Scheduler)
REM  Edit PROJDIR only if you move the project folder.
REM ============================================================
set "PROJDIR=%~dp0"
cd /d "%PROJDIR%"
py -3 "%PROJDIR%proof_tracker.py" >> "%PROJDIR%proof_tracker.log" 2>&1
