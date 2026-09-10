<#
.SYNOPSIS
Starts the Doctor Work Platform locally on Windows.
.EXAMPLE
.\scripts\dev.ps1
.\scripts\dev.ps1 docker
.\scripts\dev.ps1 -NoServe
.\scripts\dev.ps1 docker --detach --wait
.NOTES
Arguments after the mode are forwarded to "docker compose up". Use long-form flags:
Windows PowerShell binds "-d" to its own -Debug switch instead of passing it on.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("local", "docker")]
    [string]$Mode = "local",
    [switch]$NoServe,
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$ComposeArgs = @()
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$pythonExe = Join-Path $backendDir ".venv\Scripts\python.exe"

function Assert-LastExit {
    param([string]$What)
    if ($LASTEXITCODE -ne 0) {
        throw "$What failed with exit code $LASTEXITCODE."
    }
}

function Assert-Command {
    param([string]$Name, [string]$Hint)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $Name`n$Hint"
    }
}

function Resolve-Uv {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        return
    }
    $candidates = @(
        (Join-Path $env:USERPROFILE ".local\bin"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links")
    )
    $packages = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path -LiteralPath $packages) {
        $candidates += Get-ChildItem -LiteralPath $packages -Directory -Filter "astral-sh.uv*" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }
    }
    foreach ($dir in $candidates) {
        if ($dir -and (Test-Path -LiteralPath (Join-Path $dir "uv.exe"))) {
            $env:PATH = "$dir;$env:PATH"
            Write-Host "uv was missing from PATH; using $dir for this session." -ForegroundColor Yellow
            return
        }
    }
    throw "Missing required command: uv`nInstall uv, then open a new terminal:`n  winget install --id astral-sh.uv -e`n  powershell -ExecutionPolicy ByPass -c `"irm https://astral.sh/uv/install.ps1 | iex`""
}

try {
    if ($Mode -eq "docker") {
        Assert-Command "docker" "Install Docker Desktop with Compose v2, then run this again."
        Push-Location $root
        try {
            & docker compose up --build @ComposeArgs
            $code = $LASTEXITCODE
        } finally {
            Pop-Location
        }
        exit $code
    }

    Resolve-Uv
    Assert-Command "node" "Install Node.js 22.12 or newer (see README)."
    Assert-Command "npm.cmd" "Install Node.js 22.12 or newer (see README)."

    try {
        $nodeVersion = [version]((& node --version).TrimStart("v"))
        if ($nodeVersion -lt [version]"20.19.0") {
            Write-Host "Node $nodeVersion detected; Vite 7 needs 20.19+, and this project targets 22.12+." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "Could not read the Node.js version; continuing anyway." -ForegroundColor Yellow
    }

    Write-Host "Installing backend dependencies and preparing the database..." -ForegroundColor Cyan
    Push-Location $backendDir
    try {
        & uv sync --frozen
        Assert-LastExit "uv sync"
        & uv run alembic upgrade head
        Assert-LastExit "Database migration"
        & uv run python -m app.seed
        Assert-LastExit "Seeding"
    } finally {
        Pop-Location
    }

    Write-Host "Installing frontend dependencies..." -ForegroundColor Cyan
    $registry = if ($env:npm_config_registry) { $env:npm_config_registry } else { "https://registry.npmjs.org" }
    $npmArgs = @("--registry=$registry", "--fetch-retries=1", "--fetch-timeout=20000")
    $proxy = $env:HTTPS_PROXY
    if (-not $proxy) { $proxy = $env:https_proxy }
    if (-not $proxy) { $proxy = $env:HTTP_PROXY }
    if (-not $proxy) { $proxy = $env:http_proxy }
    if ($proxy) {
        $npmArgs += @("--proxy=$proxy", "--https-proxy=$proxy")
    }
    Push-Location $frontendDir
    try {
        & npm.cmd ci @npmArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend dependency installation failed. Check your registry and HTTP(S)_PROXY settings."
        }
    } finally {
        Pop-Location
    }

    if ($NoServe) {
        Write-Host "Setup finished. Start the servers with: .\scripts\dev.ps1" -ForegroundColor Green
        exit 0
    }

    if (-not (Test-Path -LiteralPath $pythonExe)) {
        throw "Expected a virtual environment at $pythonExe, but it is missing. Re-run this script."
    }

    Write-Host "Starting FastAPI and Vite. One window per server; closing a window stops it." -ForegroundColor Cyan
    $api = Start-Process -FilePath $pythonExe -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") -WorkingDirectory $backendDir -PassThru
    $web = Start-Process -FilePath "node" -ArgumentList @("node_modules/vite/bin/vite.js", "--host", "127.0.0.1") -WorkingDirectory $frontendDir -PassThru

    try {
        $ready = $false
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            if ($api.HasExited) { break }
            try {
                Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/health/live" -UseBasicParsing -TimeoutSec 2 | Out-Null
                $ready = $true
                break
            } catch {
                Start-Sleep -Milliseconds 500
            }
        }
        if ($ready) {
            Write-Host "Frontend: http://127.0.0.1:5173 | API docs: http://127.0.0.1:8000/docs" -ForegroundColor Green
        } else {
            Write-Host "The API did not answer on port 8000 yet. Check the FastAPI window for errors." -ForegroundColor Yellow
        }
        while (-not $api.HasExited -and -not $web.HasExited) {
            Start-Sleep -Milliseconds 500
        }
    } finally {
        foreach ($server in @($api, $web)) {
            if ($server -and -not $server.HasExited) {
                Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
            }
        }
    }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
