@echo off
rem Starts the Job Tracker in the background (no window) and opens it in your browser: http://localhost:8787
rem Your rows are kept in tracker-data.json in this folder. To reach it from a phone on the same network, run
rem   python tracker.py start --lan   (anyone on that network can then edit the tracker).
set "PY=py -3"
where py >nul 2>nul || set "PY=python"
%PY% "%~dp0tracker.py" start --open
if errorlevel 1 pause
