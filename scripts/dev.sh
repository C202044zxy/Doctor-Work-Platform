#!/usr/bin/env bash
#
# Thin wrapper kept for CLI compatibility. The local implementation lives in
# backend/start.sh so the platform is self-contained; this script only adds the
# "docker" mode, which is a Compose concern rather than a backend one.
#
# Usage:
#   ./scripts/dev.sh                  same as ./backend/start.sh
#   ./scripts/dev.sh local [flags]     flags are forwarded to backend/start.sh
#   ./scripts/dev.sh docker [flags]    flags are forwarded to "docker compose up"
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

mode="${1:-local}"
if [[ "$mode" == "docker" ]]; then
  shift
  command -v docker >/dev/null || { echo "docker was not found. Install Docker with Compose v2 first (see README)." >&2; exit 1; }
  docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 was not found. Install it first (see README)." >&2; exit 1; }
  # Extra arguments are forwarded to "docker compose up", for example --detach --wait.
  exec docker compose up --build "$@"
fi

if [[ "$mode" != "local" ]]; then
  echo "Usage: ./scripts/dev.sh [local|docker] [extra flags for the selected mode]" >&2
  exit 1
fi

if (( $# )); then shift; fi
exec ./backend/start.sh --reload --docker-redis "$@"
