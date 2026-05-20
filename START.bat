@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Karama Registration Automation
echo Starting automation... Press Ctrl+C to stop.
python main.py
pause
