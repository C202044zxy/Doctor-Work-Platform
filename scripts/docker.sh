#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
action="${1:-up}"
case "$action" in init|up|down|logs|status|check|account) ;; *) echo 'Usage: bash scripts/docker.sh [init|up|down|logs|status|check|account]' >&2; exit 2 ;; esac
command -v docker >/dev/null || { echo 'Install and start Docker with the Compose plugin.' >&2; exit 1; }
docker compose version
docker info --format '{{.OSType}}'
if [[ "$action" == init || "$action" == up ]]; then
    if [[ ! -f "$root/.env.server" ]]; then
        docker run --rm --user "$(id -u):$(id -g)" --mount "type=bind,source=$root,target=/workspace" -w /workspace python:3.12-slim-bookworm python scripts/init_docker.py
    fi
fi
[[ "$action" == init ]] && exit 0
[[ -f "$root/.env.server" ]] || { echo 'Run bash scripts/docker.sh init first.' >&2; exit 1; }
compose=(docker compose --project-directory "$root" --env-file "$root/.env.server" -f "$root/compose.sqlite.yaml")
"${compose[@]}" config --quiet
case "$action" in
    up)
        "${compose[@]}" up --build --detach --wait --wait-timeout 300
        "${compose[@]}" exec -T backend .venv/bin/python -m app.docker_check
        echo 'Ready: http://127.0.0.1:8080 (unless HTTP_BIND/HTTP_PORT were changed).'
        echo 'Configure SMTP and a staff account; see docs/Docker-reproduction.md.'
        ;;
    account)
        read -r -p 'Username (for example admin): ' username
        read -r -p 'Display name: ' display_name
        read -r -p 'Email address that receives verification codes: ' email
        read -r -p 'Role (admin, senior, junior): ' title
        read -r -p 'Department (General Medicine or Cardiology): ' department
        "${compose[@]}" exec backend .venv/bin/python -m app.create_user --username "$username" --name "$display_name" --email "$email" --title "$title" --department "$department"
        ;;
    check) "${compose[@]}" exec -T backend .venv/bin/python -m app.docker_check ;;
    down) "${compose[@]}" down ;;
    logs) "${compose[@]}" logs --tail=100 ;;
    status) "${compose[@]}" ps ;;
esac
