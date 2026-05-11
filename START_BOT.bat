@echo off
chcp 65001 >nul
title Nexa Search Bot
python -m pip install -r requirements.txt
python bot_bootstrap.py
pause
