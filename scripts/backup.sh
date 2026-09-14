#!/usr/bin/env bash
#
# Back up the SQLite database. Both modes take a consistent snapshot with
# SQLite's online backup API, so the stack can keep running.
#
# Usage:
#   ./scripts/backup.sh local     copy backend/doctor.db (the no-Docker mode)
#   ./scripts/backup.sh docker    pull the database out of the compose volume
#
# Environment: BACKUP_DIR (default "backups"), BACKUP_KEEP (default 7),
# SQLITE_PATH (local mode only; default "backend/doctor.db").
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

mode="${1:-local}"
backup_dir="${BACKUP_DIR:-backups}"
keep="${BACKUP_KEEP:-7}"
stamp="$(date +%Y%m%d-%H%M%S)"
root_dir="$(pwd)"

mkdir -p "$backup_dir"
# Resolve to an absolute path: the local branch below changes directory, and a
# relative BACKUP_DIR would otherwise resolve against backend/ instead of here.
backup_dir="$(cd -- "$backup_dir" && pwd)"
target="$backup_dir/sqlite-$stamp.db"

case "$mode" in
  docker)
    command -v docker >/dev/null || { echo "docker was not found. Install Docker with Compose v2 first (see README)." >&2; exit 1; }
    # The container has no sqlite3 CLI, so use the Python that is already there.
    docker compose exec -T backend .venv/bin/python -c \
      "import sqlite3; src = sqlite3.connect('/data/doctor.db'); dst = sqlite3.connect('/tmp/backup.db'); src.backup(dst); dst.close(); src.close()"
    docker compose cp backend:/tmp/backup.db "$target"
    docker compose exec -T backend rm -f /tmp/backup.db
    ;;
  local|sqlite)
    db_path="${SQLITE_PATH:-$root_dir/backend/doctor.db}"
    [[ -f "$db_path" ]] || { echo "No SQLite database at $db_path; run the startup script first (backend/start.sh or backend/start.ps1)." >&2; exit 1; }
    uv run --project "$root_dir/backend" python - "$db_path" "$target" <<'PY'
import sqlite3
import sys

source = sqlite3.connect(sys.argv[1])
destination = sqlite3.connect(sys.argv[2])
source.backup(destination)
destination.close()
source.close()
PY
    ;;
  *)
    echo "Usage: ./scripts/backup.sh [local|docker]  (\"sqlite\" is an alias of \"local\")" >&2
    exit 1
    ;;
esac

echo "Wrote $target"

if [[ "$keep" =~ ^[0-9]+$ ]] && (( keep > 0 )); then
  old_archives=$(ls -1t "$backup_dir"/sqlite-*.db 2>/dev/null | tail -n "+$((keep + 1))" || true)
  while IFS= read -r old_archive; do
    [[ -n "$old_archive" ]] || continue
    rm -f "$old_archive"
    echo "Removed old backup $old_archive"
  done <<< "$old_archives"
fi
