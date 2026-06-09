@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo    Certification Checker  -  Badikat Takan
echo ============================================================

REM --- 1. API key: read from api_key.txt in this same folder -------------------
REM     Create that file once, paste the sk-ant-... key into it (one line), save.
if exist "api_key.txt" (
  set /p ANTHROPIC_API_KEY=<api_key.txt
) else (
  echo NOTE: api_key.txt not found - starting in DEMO mode.
)

REM --- 2. Choose a Python command (the "py" launcher is preferred) -------------
set "PY=python"
where py >nul 2>nul && set "PY=py -3"

REM --- 3. Install components on first run only (needs internet) ----------------
%PY% -c "import flask, anthropic" 2>nul
if errorlevel 1 (
  echo Installing components ^(first run only, needs internet^)...
  %PY% -m pip install -r requirements.txt
)

REM --- 4. Open the browser shortly after, then start the server ---------------
start "" /b cmd /c "ping -n 4 127.0.0.1 >nul & start http://localhost:5000"
echo.
echo Opening http://localhost:5000 in your browser...
echo If the page is blank, wait a moment and refresh.
echo To stop: close this window.
echo ------------------------------------------------------------
%PY% server.py

echo.
echo (Server stopped.)
pause
