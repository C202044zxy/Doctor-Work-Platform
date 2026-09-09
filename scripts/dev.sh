#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ "${1:-local}" == "docker" ]]; then
  exec docker compose up --build
fi
if [[ "${1:-local}" != "local" ]]; then
  echo "Usage: ./scripts/dev.sh [local|docker]" >&2
  exit 1
fi
command -v uv >/dev/null || { echo "Install uv first (see README)." >&2; exit 1; }
command -v npm >/dev/null || { echo "Install Node.js and npm first (see README)." >&2; exit 1; }
(cd backend && uv sync --frozen && .venv/bin/alembic upgrade head && .venv/bin/python -m app.seed)
(cd frontend && npm ci)
pids=()
cleanup() { for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done; }
trap cleanup EXIT
trap 'exit 130' INT TERM
(cd backend && exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000) &
pids+=("$!")
(cd frontend && exec node node_modules/vite/bin/vite.js --host 127.0.0.1) &
pids+=("$!")
echo "Frontend: http://127.0.0.1:5173 | API docs: http://127.0.0.1:8000/docs"
wait -n "${pids[@]}"
