@echo off
rem Creates (or promotes) the Speedo Live administrator in your Firebase project.
rem The password is typed here and never shown on screen.
cd /d "%~dp0backend"
if not exist .venv\Scripts\python.exe (echo backend\.venv is missing - see README.md section 1 & pause & exit /b 1)
.venv\Scripts\python.exe -m app.seed --ask
echo.
pause
