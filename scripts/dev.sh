#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ "${1:-local}" == "docker" ]]; then
  shift
  command -v docker >/dev/null || { echo "docker was not found. Install Docker with Compose v2 first (see README)." >&2; exit 1; }
  docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 was not found. Install it first (see README)." >&2; exit 1; }
  # Extra arguments are forwarded to "docker compose up", for example --detach --wait.
  exec docker compose up --build "$@"
fi
if [[ "${1:-local}" != "local" ]]; then
  echo "Usage: ./scripts/dev.sh [local|docker] [extra docker compose up flags]" >&2
  exit 1
fi
command -v uv >/dev/null || { echo "Install uv first (see README)." >&2; exit 1; }
command -v node >/dev/null || { echo "Install Node.js 22.12 or newer first (see README)." >&2; exit 1; }
command -v npm >/dev/null || { echo "Install Node.js and npm first (see README)." >&2; exit 1; }
(cd backend && uv sync --frozen && uv run alembic upgrade head && uv run python -m app.seed)
# Keep installation independent of a stale user-level mirror/proxy configuration.
npm_args=(--registry="${npm_config_registry:-https://registry.npmjs.org}" --fetch-retries=1 --fetch-timeout=20000)
install_proxy="${https_proxy:-${HTTPS_PROXY:-${http_proxy:-${HTTP_PROXY:-}}}}"
if [[ -n "$install_proxy" ]]; then
  npm_args+=(--proxy="$install_proxy" --https-proxy="$install_proxy")
fi
if ! (cd frontend && npm ci "${npm_args[@]}"); then
  echo "Frontend dependency installation failed. Check your registry and HTTP(S)_PROXY settings." >&2
  exit 1
fi
pids=()
cleanup() { for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done; }
trap cleanup EXIT
trap 'exit 130' INT TERM
(cd backend && exec uv run uvicorn app.main:app --host 127.0.0.1 --port 8000) &
pids+=("$!")
(cd frontend && exec node node_modules/vite/bin/vite.js --host 127.0.0.1) &
pids+=("$!")
echo "Frontend: http://127.0.0.1:5173 | API docs: http://127.0.0.1:8000/docs"
wait -n "${pids[@]}"
