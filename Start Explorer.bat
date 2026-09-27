@echo off
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 scripts\launch_explorer.py
) else (
  python scripts\launch_explorer.py
)
if errorlevel 1 (
  echo Python 3.10 or newer is required. See EXPLORER_README.md.
  pause
)
