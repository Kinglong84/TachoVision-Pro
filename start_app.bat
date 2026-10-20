@echo off
rem Avvia TachoVision Pro in questa finestra: premere INVIO per aprire il browser.
title TachoVision Pro
cd /d "%~dp0"
python app.py
if errorlevel 1 pause
