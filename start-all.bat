
@echo off
REM ============================================================
REM  ShiftGuard - one-click start for backend + frontend
REM  Double-click this file, or run:  start-all.bat
REM  Opens two windows: Backend (port 8000) and Frontend (5173)
REM ============================================================
setlocal
set "ROOT=%~dp0"
set "BACKEND=%ROOT%PowerPioneer-Backend-Core"
set "FRONTEND=%ROOT%PowerPioneer-Frontend"

REM ---- Check tools ----
where python >nul 2>nul || (echo [ERROR] Python not found. Install it from python.org & pause & exit /b 1)
where npm    >nul 2>nul || (echo [ERROR] Node.js/npm not found. Install it from nodejs.org & pause & exit /b 1)

REM ---- Backend setup ----
echo.
echo === Backend setup ===
cd /d "%BACKEND%" || (echo [ERROR] Backend folder not found & pause & exit /b 1)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv || (echo [ERROR] Could not create venv & pause & exit /b 1)
)

echo Installing Python packages...
".venv\Scripts\python.exe" -m pip install -q --upgrade pip
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || (echo [ERROR] pip install failed & pause & exit /b 1)

echo Applying database migrations...
".venv\Scripts\python.exe" manage.py migrate || (echo [ERROR] migrate failed & pause & exit /b 1)

echo Seeding demo data (skipped if already seeded)...
".venv\Scripts\python.exe" manage.py seed_data >nul 2>nul && echo Demo data created. || echo Demo data already present.

REM ---- Frontend setup ----
echo.
echo === Frontend setup ===
cd /d "%FRONTEND%" || (echo [ERROR] Frontend folder not found & pause & exit /b 1)

if not exist "node_modules" (
    echo Installing npm packages - first run, this can take a minute...
    call npm install || (echo [ERROR] npm install failed & pause & exit /b 1)
)

REM ---- Launch both ----
echo.
echo === Starting servers ===
start "ShiftGuard Backend"  cmd /k "cd /d "%BACKEND%" && .venv\Scripts\python.exe manage.py runserver"
start "ShiftGuard Frontend" cmd /k "cd /d "%FRONTEND%" && npm run dev"

REM Give the servers a few seconds, then open the app
timeout /t 6 /nobreak >nul
start "" http://localhost:5173

echo.
echo  Frontend:  http://localhost:5173
echo  Backend:   http://127.0.0.1:8000/api/docs/
echo  Login:     jordan.reyes@powerpioneer.local / Password@123
echo  Admin:     admin@powerpioneer.local / Admin@12345
echo.
echo  To stop: close the "ShiftGuard Backend" and "ShiftGuard Frontend" windows.
echo.
pause
