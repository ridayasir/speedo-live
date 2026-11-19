@echo off
rem Starts Speedo Live locally: API on :8000 (data in your Firebase project), website on :3000.
rem First-time setup (Firebase project, backend\.env, first admin) is in README.md, section 1.
cd /d "%~dp0backend"
if not exist .venv\Scripts\python.exe (echo backend\.venv is missing - see README.md section 1 & pause & exit /b 1)
findstr /r /c:"^FIREBASE_PROJECT_ID=..*" .env >nul 2>&1 || (echo FIREBASE_PROJECT_ID is not set in backend\.env - see README.md section 1 & pause & exit /b 1)
start "Speedo API" .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
cd /d "%~dp0web"
start "Speedo Web" cmd /c npm run dev
timeout /t 6 >nul
start http://localhost:3000
