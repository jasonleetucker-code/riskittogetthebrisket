@echo off
cd /d "%~dp0"
python "Dynasty Scraper.py" %*
exit /b %errorlevel%
