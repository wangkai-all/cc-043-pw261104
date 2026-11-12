#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install --quiet fastapi uvicorn
fi
if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm install --no-audit --no-fund)
fi

# Seed the demo database unless one already exists.
if [ ! -f contracts.sqlite3 ]; then
  .venv/bin/python -m app.seed
fi

cleanup() { kill "$API_PID" "$UI_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 &
API_PID=$!
(cd frontend && npm run dev -- --host 127.0.0.1) &
UI_PID=$!

echo "API  http://127.0.0.1:8000/docs"
echo "UI   http://127.0.0.1:5173"
wait
