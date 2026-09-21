#!/usr/bin/env bash
#
# One-command local startup for the Doctor Work Platform on Linux and macOS.
#
# This script is self-contained: it prepares Redis, the SQLite database, the
# Python environment and the frontend, then serves the API and the web UI. The
# Windows equivalent is backend/start.ps1 -- keep the two in step.
#
# Usage:
#   ./backend/start.sh                 set up, then serve API + frontend
#   ./backend/start.sh --no-serve      set up only, then exit (used by CI)
#
# Redis: an already-running server is used as-is. Otherwise the script starts
# one from PATH, and failing that downloads and builds a private copy under
# backend/runtime/redis. That directory is gitignored -- never commit binaries.
set -euo pipefail

backend_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root_dir="$(dirname -- "$backend_dir")"
frontend_dir="$root_dir/frontend"

redis_runtime="$backend_dir/runtime/redis"
redis_data="$backend_dir/runtime/redis-data"
redis_version="7.4.2"
redis_url="${REDIS_URL:-redis://127.0.0.1:6379/0}"

no_serve=0
reload=0
docker_redis=0
skip_install=0
for arg in "$@"; do
  case "$arg" in
    --no-serve) no_serve=1 ;;
    --reload) reload=1 ;;
    --docker-redis) docker_redis=1 ;;
    --skip-install) skip_install=1 ;;
    -h|--help) sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown argument: $arg (see --help)" >&2; exit 1 ;;
  esac
done

log() { printf '\033[36m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*" >&2; }

assert_command() {
  command -v "$1" >/dev/null || { echo "Missing required command: $1. $2" >&2; exit 1; }
}

# Runs a Python one-liner with the project environment, which is the only place
# the "redis" package is guaranteed to be importable.
redis_bootstrap() {
  (cd "$backend_dir" && uv run --quiet python -m app.redis_bootstrap "$@")
}

start_redis_from() {
  local server_bin="$1" port="$2"
  mkdir -p "$redis_data"
  # --daemonize lets the server outlive this script, so the next run finds it
  # already reachable instead of trying to start a second one on the same port.
  "$server_bin" \
    --port "$port" \
    --dir "$redis_data" \
    --appendonly yes \
    --daemonize yes \
    --logfile "$redis_data/redis.log" \
    --pidfile "$redis_data/redis.pid"
}

build_redis_from_source() {
  local port="$1" source_dir jobs
  assert_command curl "Install curl, or install Redis with your package manager."
  assert_command tar "Install tar, or install Redis with your package manager."
  assert_command make "Install build tools (for Debian/Ubuntu: apt-get install build-essential), or install Redis with your package manager."
  command -v cc >/dev/null || gcc --version >/dev/null 2>&1 || {
    echo "No C compiler found. Install build-essential, or run: sudo apt-get install redis-server" >&2
    exit 1
  }

  source_dir="$redis_runtime/redis-$redis_version"
  mkdir -p "$redis_runtime"
  log "Downloading Redis $redis_version source into backend/runtime/redis ..."
  curl -fL --retry 3 --retry-delay 2 \
    -o "$redis_runtime/redis-$redis_version.tar.gz" \
    "https://download.redis.io/releases/redis-$redis_version.tar.gz"
  rm -rf "$source_dir"
  tar -xzf "$redis_runtime/redis-$redis_version.tar.gz" -C "$redis_runtime"

  # MALLOC=libc skips the bundled jemalloc build: it is much faster to compile
  # and the allocator makes no difference for a local demo dataset.
  jobs="$( (nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2) )"
  log "Compiling Redis (a couple of minutes, one time only) ..."
  make -C "$source_dir" -j"$jobs" MALLOC=libc redis-server >"$redis_runtime/build.log" 2>&1 || {
    echo "Redis failed to build. See $redis_runtime/build.log." >&2
    echo "Simplest alternative: install it with your package manager (brew install redis / sudo apt-get install redis-server)." >&2
    exit 1
  }
  start_redis_from "$source_dir/src/redis-server" "$port"
}

ensure_redis() {
  if (( docker_redis )); then
    assert_command docker "Start Docker before running development mode."
    docker info --format '{{.ServerVersion}}' >/dev/null || {
      echo "Docker is unavailable. Start Docker (Linux containers), then retry." >&2
      exit 1
    }
    docker compose -f "$root_dir/compose.dev.yaml" up --detach --wait --wait-timeout 60
    redis_bootstrap wait --url "$redis_url" --timeout 30
    return
  fi
  if redis_bootstrap probe --url "$redis_url"; then
    log "Redis is already reachable at $redis_url."
    return 0
  fi

  local host port
  read -r host port < <(redis_bootstrap endpoint --url "$redis_url")

  # Starting a local server would not help when REDIS_URL points elsewhere, so
  # say what is actually wrong instead of starting an unused process.
  if [[ "$host" != "127.0.0.1" && "$host" != "localhost" && "$host" != "::1" ]]; then
    echo "Redis is unreachable at $redis_url, which points at a remote host." >&2
    echo "Start that server, or unset REDIS_URL to use a local one." >&2
    exit 1
  fi

  log "No Redis on 127.0.0.1:$port; preparing a local one ..."
  if command -v redis-server >/dev/null; then
    log "Using the redis-server found on PATH."
    start_redis_from "$(command -v redis-server)" "$port"
  else
    build_redis_from_source "$port"
  fi

  if ! redis_bootstrap wait --url "$redis_url" --timeout 30; then
    echo "Redis was started but never answered on port $port. See $redis_data/redis.log." >&2
    exit 1
  fi
  log "Redis is up on 127.0.0.1:$port."
}

assert_command uv "Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
assert_command node "Install Node.js 22.12 or newer."
assert_command npm "Install Node.js and npm."

log "Syncing backend dependencies ..."
if (( ! skip_install )); then (cd "$backend_dir" && uv sync --frozen); fi
(cd "$backend_dir" && uv run --no-sync python -m app.dev_config)
if (( docker_redis )); then
  redis_url="redis://127.0.0.1:16379/0"
  export APP_ENV=dev
else
  redis_url="$(cd "$backend_dir" && uv run --no-sync python -c "from app.config import Settings; print(Settings().redis_url or 'redis://127.0.0.1:6379/0')")"
fi
export REDIS_URL="$redis_url"

# Stops only a leftover that is provably this project's own dev server; anything
# else is reported and left alone.
if (( ! no_serve )); then (cd "$backend_dir" && uv run --no-sync python -m app.dev_runtime reclaim); fi
ensure_redis

log "Applying database migrations and seeding ..."
(
  cd "$backend_dir"
  uv run alembic upgrade head
  uv run python -m app.seed
  # Presentation baseline (admin_zhang, dr_wang, P20260001 ...). Safe to repeat.
  uv run python -m app.seed_demo
)

log "Installing frontend dependencies ..."
# Keep installation independent of a stale user-level mirror/proxy configuration.
npm_args=(--registry="${npm_config_registry:-https://registry.npmjs.org}" --fetch-retries=1 --fetch-timeout=20000)
install_proxy="${https_proxy:-${HTTPS_PROXY:-${http_proxy:-${HTTP_PROXY:-}}}}"
if [[ -n "$install_proxy" ]]; then
  npm_args+=(--proxy="$install_proxy" --https-proxy="$install_proxy")
fi
if (( ! skip_install )) && ! (cd "$frontend_dir" && npm ci "${npm_args[@]}"); then
  echo "Frontend dependency installation failed. Check your registry and HTTP(S)_PROXY settings." >&2
  exit 1
fi

if (( no_serve )); then
  log "Setup finished. Start the servers with: ./backend/start.sh"
  exit 0
fi

log "Starting FastAPI and Vite. Ctrl+C stops both."
pids=()
# $! is the subshell that execs into `uv run`, which may fork uvicorn rather than
# replace itself. Killing only that parent would leave the server orphaned -- the
# same class of bug the Windows sibling script is being fixed for. Walk the tree.
kill_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do kill_tree "$child"; done
  kill "$pid" 2>/dev/null || true
}
cleanup() { for pid in "${pids[@]}"; do kill_tree "$pid"; done; }
trap cleanup EXIT
trap 'exit 130' INT TERM
api_args=(--host 127.0.0.1 --port 8000 --no-access-log --log-level warning)
if (( reload )); then api_args+=(--reload --reload-dir app); fi
(cd "$backend_dir" && exec uv run uvicorn app.main:app "${api_args[@]}") &
pids+=("$!")
(cd "$frontend_dir" && exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort) &
pids+=("$!")
(cd "$backend_dir" && uv run --no-sync python -m app.dev_runtime ready)
echo "Redis: ready | Frontend: http://127.0.0.1:5173 | API docs: http://127.0.0.1:8000/docs"
wait -n "${pids[@]}"
