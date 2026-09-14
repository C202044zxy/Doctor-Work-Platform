<#
.SYNOPSIS
Thin wrapper kept for CLI compatibility.

.DESCRIPTION
The local implementation lives in backend\start.ps1 so the platform stays
self-contained; this script only adds the "docker" mode, which is a Compose
concern rather than a backend one.

.EXAMPLE
.\scripts\dev.ps1
.\scripts\dev.ps1 docker
.\scripts\dev.ps1 local -NoServe
.\scripts\dev.ps1 docker --detach --wait

.NOTES
Arguments after the mode are forwarded to the selected mode. Use long-form flags:
Windows PowerShell binds "-d" to its own -Debug switch instead of passing it on.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("local", "docker")]
    [string]$Mode = "local",
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs = @()
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot

if ($Mode -eq "docker") {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Host "docker was not found. Install Docker Desktop with Compose v2, then run this again." -ForegroundColor Red
        exit 1
    }
    Push-Location $root
    try {
        & docker compose up --build @ExtraArgs
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    exit $code
}

$start = Join-Path $root "backend\start.ps1"
& $start @ExtraArgs
exit $LASTEXITCODE
