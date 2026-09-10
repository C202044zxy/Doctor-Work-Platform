#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

mode="${1:-docker}"
backup_dir="${BACKUP_DIR:-backups}"
keep="${BACKUP_KEEP:-7}"
stamp="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$backup_dir"

case "$mode" in
  docker)
    command -v docker >/dev/null || { echo "docker was not found. Install Docker with Compose v2 first (see README)." >&2; exit 1; }
    # Credentials stay inside the container, which already has them in its environment.
    target="$backup_dir/mysql-$stamp.sql"
    docker compose exec -T mysql sh -c 'exec mysqldump --single-transaction --databases "$MYSQL_DATABASE" -u"$MYSQL_USER" -p"$MYSQL_PASSWORD"' > "$target"
    gzip -f "$target"
    target="$target.gz"
    pattern="$backup_dir/mysql-*.sql.gz"
    ;;
  sqlite)
    source_db="backend/doctor.db"
    [[ -f "$source_db" ]] || { echo "No SQLite database at $source_db; run the local startup script first." >&2; exit 1; }
    target="$backup_dir/sqlite-$stamp.db"
    cp "$source_db" "$target"
    pattern="$backup_dir/sqlite-*.db"
    ;;
  *)
    echo "Usage: ./scripts/backup.sh [docker|sqlite]" >&2
    exit 1
    ;;
esac

echo "Wrote $target"

if [[ "$keep" =~ ^[0-9]+$ ]] && (( keep > 0 )); then
  old_archives=$(ls -1t $pattern 2>/dev/null | tail -n "+$((keep + 1))" || true)
  while IFS= read -r old_archive; do
    [[ -n "$old_archive" ]] || continue
    rm -f "$old_archive"
    echo "Removed old backup $old_archive"
  done <<< "$old_archives"
fi
