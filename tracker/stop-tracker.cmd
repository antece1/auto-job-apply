@echo off
rem Stops the Job Tracker server. Your rows stay in tracker-data.json.
set "PY=py -3"
where py >nul 2>nul || set "PY=python"
%PY% "%~dp0tracker.py" stop
timeout /t 3 >nul
