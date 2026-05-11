@echo off
chcp 65001 >nul
title Nexa Search Connection Check
python -m pip install -r requirements.txt
python check_connection.py
powershell -NoProfile -Command "Write-Host ''; Write-Host 'Extra Windows test:'; Test-NetConnection api.telegram.org -Port 443"
pause
