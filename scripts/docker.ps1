[CmdletBinding()]
param(
    [ValidateSet("init", "up", "down", "logs", "status", "check", "account")]
    [string]$Action = "up"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
function Invoke-Docker {
    & docker @args
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed (exit $LASTEXITCODE)." }
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Install Docker Desktop, start it in Linux containers mode, then reopen this terminal."
}
Invoke-Docker compose version
Invoke-Docker info --format '{{.OSType}}'
if ($Action -eq "init" -or $Action -eq "up") {
    if (-not (Test-Path -LiteralPath (Join-Path $root ".env.server"))) {
        Invoke-Docker run --rm --mount "type=bind,source=$root,target=/workspace" -w /workspace python:3.12-slim-bookworm python scripts/init_docker.py
    }
}
if ($Action -eq "init") { return }
if (-not (Test-Path -LiteralPath (Join-Path $root ".env.server"))) {
    throw "Run scripts/docker.ps1 init first."
}
$compose = @("compose", "--project-directory", $root, "--env-file", (Join-Path $root ".env.server"), "-f", (Join-Path $root "compose.sqlite.yaml"))
# Quiet validation: never print expanded environment values or secrets.
Invoke-Docker @compose config --quiet
switch ($Action) {
    "up" {
        Invoke-Docker @compose up --build --detach --wait --wait-timeout 300
        Invoke-Docker @compose exec -T backend .venv/bin/python -m app.docker_check
        Write-Host "Ready: http://127.0.0.1:8080 (unless HTTP_BIND/HTTP_PORT were changed)."
        Write-Host "Set SMTP in .env.server and provision a staff account; see docs/Docker-reproduction.md."
    }
    "account" {
        $username = Read-Host "Username (for example admin)"
        $displayName = Read-Host "Display name"
        $email = Read-Host "Email address that receives verification codes"
        $title = Read-Host "Role: admin, senior, or junior"
        $department = Read-Host "Department: General Medicine or Cardiology"
        Invoke-Docker @compose exec backend .venv/bin/python -m app.create_user --username $username --name $displayName --email $email --title $title --department $department
    }
    "check" { Invoke-Docker @compose exec -T backend .venv/bin/python -m app.docker_check }
    "down" { Invoke-Docker @compose down }
    "logs" { Invoke-Docker @compose logs --tail=100 }
    "status" { Invoke-Docker @compose ps }
}
