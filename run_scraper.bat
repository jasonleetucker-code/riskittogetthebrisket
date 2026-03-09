@echo off
cd /d "%~dp0"
python "Dynasty Scraper.py" %*
if errorlevel 1 exit /b %errorlevel%
echo.
echo Running post-publish debug audit...
python "debug_loop.py" --iterations 1 --required-passes 1
exit /b %errorlevel%
