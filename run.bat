@echo off
REM Run Speedo Live locally on Windows (DEMO mode, SQLite).
REM Needs Python 3.10+ (and Node only to rebuild the web app).
setlocal
cd /d "%~dp0"

REM --- Find Python ---
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
    where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [ERROR] Python nahi mila. Python 3.10+ install karein: https://www.python.org/downloads/
    echo         Install karte waqt "Add Python to PATH" tick karna na bhoolen.
    pause
    exit /b 1
)

REM --- Virtual environment ---
if not exist "backend\.venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    %PY% -m venv backend\.venv
    if errorlevel 1 (
        echo [ERROR] venv nahi ban saka.
        pause
        exit /b 1
    )
)
call "backend\.venv\Scripts\activate.bat"

REM --- Install requirements ---
echo Installing requirements...
python -m pip install -q -r backend\requirements.txt
if errorlevel 1 (
    echo [ERROR] Requirements install nahi huin. Internet connection check karein.
    pause
    exit /b 1
)

REM --- Optional: rebuild web app if Node is installed ---
where npx >nul 2>&1
if not errorlevel 1 (
    if exist "web\src" (
        echo Building web app...
        pushd web
        call npx -y -p typescript tsc -p .
        if errorlevel 1 echo web build skipped; using prebuilt web\public\js
        popd
    )
)

REM --- Start server ---
if not defined PORT set "PORT=8000"
cd backend
echo.
echo ============================================================
echo  Speedo Live: http://localhost:%PORT%
echo  Admin: /admin   Driver: /driver   API docs: /docs
echo  Demo password: Demo@12345
echo  Band karne ke liye: Ctrl+C
echo ============================================================
echo.
start "" /min cmd /c "timeout /t 5 >nul & start http://localhost:%PORT%"
python -m uvicorn app.main:app --host 0.0.0.0 --port %PORT%

pause
endlocal
