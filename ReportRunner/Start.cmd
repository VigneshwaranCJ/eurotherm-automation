@echo off
title Report Runner
cd /d "%~dp0"
start "" "http://127.0.0.1:8780"
"D:\Ceiyone\EurothermReviewerAutomationPython\.venv\Scripts\python.exe" "%~dp0server.py"
pause
