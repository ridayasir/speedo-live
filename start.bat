@echo off
rem Starts Speedo Live locally: API on :8000 (SQLite + demo data), website on :3000.
rem First-time setup is in README.md, section 2.
cd /d "%~dp0backend"
if not exist .venv\Scripts\python.exe (echo backend\.venv is missing - see README.md section 2 & pause & exit /b 1)
.venv\Scripts\python.exe -m app.seed
start "Speedo API" .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
cd /d "%~dp0web"
start "Speedo Web" cmd /c npm run dev
timeout /t 6 >nul
start http://localhost:3000
