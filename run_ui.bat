@echo off
cd /d "%~dp0"
python scripts/ui_server.py --port 8765
pause
