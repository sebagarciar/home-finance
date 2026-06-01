#!/bin/bash
# Start backend (port 8000) and frontend (port 5173) together.
# Ctrl+C kills both.

ROOT="$(cd "$(dirname "$0")" && pwd)"

# Kill anything already on these ports
lsof -ti :8000 | xargs kill -9 2>/dev/null
lsof -ti :5173 | xargs kill -9 2>/dev/null

trap 'kill 0' INT TERM EXIT

cd "$ROOT/backend" && .venv/bin/uvicorn app.main:app --reload --port 8000 &
cd "$ROOT/frontend" && npm run dev &

wait
