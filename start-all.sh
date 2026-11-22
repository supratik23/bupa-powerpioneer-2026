#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/PowerPioneer-Backend-Core"
FRONTEND_DIR="$ROOT_DIR/PowerPioneer-Frontend"
AGENT_DIR="$ROOT_DIR/PowerPioneer-AI/langgraph-agent"
BACKEND_PORT=8000
AGENT_PORT=8001
FRONTEND_PORT=5173

BACKEND_PID=""
FRONTEND_PID=""
AGENT_PID=""

cleanup() {
    local pid
    for pid in "$BACKEND_PID" "$FRONTEND_PID" "$AGENT_PID"; do
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    for pid in "$BACKEND_PID" "$FRONTEND_PID" "$AGENT_PID"; do
        if [[ -n "$pid" ]]; then
            wait "$pid" 2>/dev/null || true
        fi
    done
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] Python 3 not found. Install Python 3 and try again." >&2
    exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
    echo "[ERROR] Node.js/npm not found. Install Node.js and try again." >&2
    exit 1
fi

echo
echo "=== Backend setup ==="
if [[ ! -d "$BACKEND_DIR" ]]; then
    echo "[ERROR] Backend folder not found: $BACKEND_DIR" >&2
    exit 1
fi
if [[ ! -f "$BACKEND_DIR/.env" ]]; then
    if [[ -f "$BACKEND_DIR/.env.example" ]]; then
        cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
        echo "[ACTION NEEDED] Created PowerPioneer-Backend-Core/.env from .env.example."
        echo "               Set SUPABASE_DB_PASSWORD, then run this script again."
    else
        echo "[ERROR] Backend .env.example not found." >&2
    fi
    exit 1
fi
if ! grep -Eq '^SUPABASE_DB_PASSWORD=.+$' "$BACKEND_DIR/.env"; then
    echo "[ACTION NEEDED] SUPABASE_DB_PASSWORD is empty in PowerPioneer-Backend-Core/.env."
    echo "               Set it to the Supabase database password, then run this script again."
    exit 1
fi

if [[ ! -x "$BACKEND_DIR/.venv/bin/python" ]]; then
    echo "Creating backend virtual environment..."
    python3 -m venv "$BACKEND_DIR/.venv"
fi
"$BACKEND_DIR/.venv/bin/python" -m pip install -q --upgrade pip
"$BACKEND_DIR/.venv/bin/python" -m pip install -q -r "$BACKEND_DIR/requirements.txt"
"$BACKEND_DIR/.venv/bin/python" "$BACKEND_DIR/manage.py" migrate
if "$BACKEND_DIR/.venv/bin/python" "$BACKEND_DIR/manage.py" seed_data >/dev/null 2>&1; then
    echo "Demo data created."
else
    echo "Demo data already present."
fi

echo
echo "=== Frontend setup ==="
if [[ ! -d "$FRONTEND_DIR" ]]; then
    echo "[ERROR] Frontend folder not found: $FRONTEND_DIR" >&2
    exit 1
fi
if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    echo "Installing frontend packages..."
    (cd "$FRONTEND_DIR" && npm install)
fi

START_AGENT=0
echo
echo "=== AI agent setup ==="
if [[ ! -f "$AGENT_DIR/.env" ]]; then
    echo "Skipping AI agent: PowerPioneer-AI/langgraph-agent/.env not found."
else
    if [[ ! -x "$AGENT_DIR/.venv/bin/python" ]]; then
        echo "Creating AI agent virtual environment..."
        if ! python3 -m venv "$AGENT_DIR/.venv"; then
            echo "[WARN] Could not create agent virtual environment; skipping agent."
        fi
    fi
    if [[ -x "$AGENT_DIR/.venv/bin/python" ]]; then
        echo "Installing AI agent packages..."
        if "$AGENT_DIR/.venv/bin/python" -m pip install -q --upgrade pip \
            && "$AGENT_DIR/.venv/bin/python" -m pip install -q -r "$AGENT_DIR/requirements.txt"; then
            START_AGENT=1
        else
            echo "[WARN] AI agent package installation failed; skipping agent."
        fi
    fi
fi

echo
echo "=== Starting servers ==="
(
    cd "$BACKEND_DIR"
    exec .venv/bin/python manage.py runserver "127.0.0.1:$BACKEND_PORT"
) &
BACKEND_PID=$!
(
    cd "$FRONTEND_DIR"
    exec npm run dev -- --port "$FRONTEND_PORT" --strictPort
) &
FRONTEND_PID=$!
if [[ "$START_AGENT" -eq 1 ]]; then
    (
        cd "$AGENT_DIR"
        exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$AGENT_PORT"
    ) &
    AGENT_PID=$!
fi

echo
echo "Frontend:  http://localhost:$FRONTEND_PORT"
echo "Backend:   http://127.0.0.1:$BACKEND_PORT/api/docs/"
if [[ "$START_AGENT" -eq 1 ]]; then
    echo "AI agent:  http://127.0.0.1:$AGENT_PORT/docs"
fi
echo "Press Ctrl+C to stop all servers."

if command -v open >/dev/null 2>&1; then
    open "http://localhost:$FRONTEND_PORT" >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://localhost:$FRONTEND_PORT" >/dev/null 2>&1 || true
fi

wait "$BACKEND_PID"
