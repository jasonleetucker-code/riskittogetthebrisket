@echo off
setlocal
cd /d "%~dp0"

echo Starting Dynasty stack...
echo   Backend  -> http://localhost:8000
echo   Frontend -> http://localhost:3000
echo.

start "Dynasty Backend" cmd /k "cd /d \"%~dp0\" && python server.py"
start "Dynasty Frontend" cmd /k "cd /d \"%~dp0frontend\" && if not exist node_modules (echo Installing frontend dependencies... && npm install) && npm run dev"

echo Both services launched in separate windows.
echo You can close this launcher window.
pause
