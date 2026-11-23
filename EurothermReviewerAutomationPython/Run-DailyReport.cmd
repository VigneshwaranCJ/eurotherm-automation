@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0logs" mkdir "%~dp0logs"
if not exist "%~dp0.env" (
  echo Missing .env in project folder >> "%~dp0logs\scheduled-run.log"
  exit /b 2
)
set "REPORT_MODE=env"
set "START_DATETIME="
set "END_DATETIME="
set "DRY_RUN=true"
"%~dp0.venv\Scripts\python.exe" -m reviewer report >> "%~dp0logs\scheduled-run.log" 2>&1
exit /b %ERRORLEVEL%
