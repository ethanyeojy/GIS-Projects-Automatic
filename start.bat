@echo off
cd /d "%~dp0"
echo Starting GeoProject Studio... leave this window open while you use the site.
start "" http://127.0.0.1:8765
py server.py
pause
