@echo off
REM ============================================================
REM  ShiftGuard - one-click start for backend + frontend (+ AI agent)
REM  Double-click this file, or run:  start-all.bat
REM  Opens windows for:
REM    Backend   (Django, Supabase Postgres)  port 8000
REM    Frontend  (Vite)                       port 5173
REM    AI agent  (FastAPI/LangGraph)          port 8001  - only if its .env exists
REM ============================================================
setlocal
set "ROOT=%~dp0"
set "BACKEND=%ROOT%PowerPioneer-Backend-Core"
set "FRONTEND=%ROOT%PowerPioneer-Frontend"
set "AGENT=%ROOT%PowerPioneer-AI\langgraph-agent"
set "AGENT_PORT=8001"

REM ---- Check tools ----
where python >nul 2>nul || (echo [ERROR] Python not found. Install it from python.org & pause & exit /b 1)
where npm    >nul 2>nul || (echo [ERROR] Node.js/npm not found. Install it from nodejs.org & pause & exit /b 1)

REM ---- Backend setup ----
echo.
echo === Backend setup ===
cd /d "%BACKEND%" || (echo [ERROR] Backend folder not found & pause & exit /b 1)

REM The backend now uses the team Supabase database and needs SUPABASE_DB_PASSWORD in .env
if not exist ".env" (
    copy /y ".env.example" ".env" >nul
    echo [ACTION NEEDED] Created PowerPioneer-Backend-Core\.env from .env.example.
    echo                 Open it, set SUPABASE_DB_PASSWORD, then run start-all.bat again.
    pause & exit /b 1
)
findstr /r /c:"^SUPABASE_DB_PASSWORD=..*" ".env" >nul || (
    echo [ACTION NEEDED] SUPABASE_DB_PASSWORD is empty in PowerPioneer-Backend-Core\.env
    echo                 Set it to the Supabase database password, then run start-all.bat again.
    pause & exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv || (echo [ERROR] Could not create venv & pause & exit /b 1)
)

echo Installing Python packages...
".venv\Scripts\python.exe" -m pip install -q --upgrade pip
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || (echo [ERROR] pip install failed & pause & exit /b 1)

echo Applying database migrations (Supabase)...
".venv\Scripts\python.exe" manage.py migrate || (echo [ERROR] migrate failed - check SUPABASE_DB_PASSWORD and your network & pause & exit /b 1)

echo Seeding demo data (skipped if the database already has employees)...
".venv\Scripts\python.exe" manage.py seed_data >nul 2>nul && echo Demo data created. || echo Demo data already present.

REM ---- Frontend setup ----
echo.
echo === Frontend setup ===
cd /d "%FRONTEND%" || (echo [ERROR] Frontend folder not found & pause & exit /b 1)

if not exist "node_modules" (
    echo Installing npm packages - first run, this can take a minute...
    call npm install || (echo [ERROR] npm install failed & pause & exit /b 1)
)

REM ---- AI agent setup (optional) ----
set "START_AGENT=0"
echo.
echo === AI agent setup ===
if not exist "%AGENT%\.env" (
    echo Skipping AI agent: PowerPioneer-AI\langgraph-agent\.env not found ^(needs GEMINI_API_KEY^).
    goto :launch
)
cd /d "%AGENT%" || goto :launch
if not exist ".venv\Scripts\python.exe" (
    echo Creating AI agent virtual environment...
    python -m venv .venv || (echo [WARN] Could not create agent venv - skipping agent & goto :launch)
)
echo Installing AI agent packages - first run, this can take a few minutes...
".venv\Scripts\python.exe" -m pip install -q --upgrade pip
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || (echo [WARN] Agent pip install failed - skipping agent & goto :launch)
set "START_AGENT=1"

REM ---- Launch ----
:launch
echo.
echo === Starting servers ===
start "ShiftGuard Backend"  cmd /k "cd /d "%BACKEND%" && .venv\Scripts\python.exe manage.py runserver"
start "ShiftGuard Frontend" cmd /k "cd /d "%FRONTEND%" && npm run dev"
REM Agent must run from its own folder (MCP servers are resolved relative to it) and on 8001 to avoid Django's 8000
if "%START_AGENT%"=="1" start "ShiftGuard AI Agent" cmd /k "cd /d "%AGENT%" && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port %AGENT_PORT%"

REM Give the servers a few seconds, then open the app
timeout /t 6 /nobreak >nul
start "" http://localhost:5173

echo.
echo  Frontend:  http://localhost:5173
echo  Backend:   http://127.0.0.1:8000/api/docs/
if "%START_AGENT%"=="1" echo  AI agent:  http://127.0.0.1:%AGENT_PORT%/docs
echo  Admin:     hello@admin.com / admin@123
echo  Demo:      jordan.reyes@powerpioneer.local / Password@123  (if seeded by seed_data)
echo.
echo  To stop: close the "ShiftGuard ..." server windows.
echo.
pause
