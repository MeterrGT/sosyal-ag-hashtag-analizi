@echo off
chcp 65001 >nul
cd /d "%~dp0"
python render_final_deliverables.py
pause
