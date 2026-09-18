<#
.SYNOPSIS
One-command local startup for the Doctor Work Platform on Windows.

.DESCRIPTION
Self-contained: prepares Redis, the SQLite database, the Python environment and
the frontend, then serves the API and the web UI. The Linux/macOS equivalent is
backend/start.sh -- keep the two in step.

Redis: an already-running server is used as-is. Otherwise the script starts one
from PATH, and failing that downloads a private copy into backend\runtime\redis.
That directory is gitignored -- never commit binaries.

.EXAMPLE
.\backend\start.ps1
.\backend\start.ps1 -NoServe
#>
[CmdletBinding()]
param(
    [switch]$NoServe,
    [switch]$Reload,
    [switch]$DockerRedis,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$backendDir = $PSScriptRoot
$rootDir = Split-Path -Parent $backendDir
$frontendDir = Join-Path $rootDir "frontend"
$pythonExe = Join-Path $backendDir ".venv\Scripts\python.exe"

$redisRuntime = Join-Path $backendDir "runtime\redis"
$redisData = Join-Path $backendDir "runtime\redis-data"
$redisVersion = "5.0.14.1"
$redisUrl = if ($env:REDIS_URL) { $env:REDIS_URL } else { "redis://127.0.0.1:6379/0" }

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

# The shared probe in app.redis_bootstrap decides reachability; only *starting*
# a server is platform-specific and therefore lives here.
function Test-RedisReachable {
    Push-Location $backendDir
    try {
        $null = & uv run --quiet python -m app.redis_bootstrap probe --url $redisUrl 2>$null
        return ($LASTEXITCODE -eq 0)
    } finally {
        Pop-Location
    }
}

function Wait-Redis {
    Push-Location $backendDir
    try {
        & uv run --quiet python -m app.redis_bootstrap wait --url $redisUrl --timeout 30
        return ($LASTEXITCODE -eq 0)
    } finally {
        Pop-Location
    }
}

function Get-RedisEndpoint {
    Push-Location $backendDir
    try {
        $line = (& uv run --quiet python -m app.redis_bootstrap endpoint --url $redisUrl 2>$null | Select-Object -Last 1)
    } finally {
        Pop-Location
    }
    $parts = ($line -split '\s+') | Where-Object { $_ }
    return @{ Host = $parts[0]; Port = $parts[1] }
}

function Start-RedisProcess {
    param([string]$ServerExe, [string]$Port)
    New-Item -ItemType Directory -Force -Path $redisData | Out-Null
    # Windows has no --daemonize, so the server is launched hidden instead and
    # deliberately left running: the next run then finds it already reachable.
    Start-Process -FilePath $ServerExe -ArgumentList @(
        "--port", $Port,
        "--dir", $redisData,
        "--appendonly", "yes",
        "--logfile", (Join-Path $redisData "redis.log")
    ) -WindowStyle Hidden | Out-Null
}

function Install-RedisFromArchive {
    param([string]$Port)
    $url = "https://github.com/tporadowski/redis/releases/download/v$redisVersion/Redis-x64-$redisVersion.zip"
    $zipPath = Join-Path $redisRuntime "Redis-x64-$redisVersion.zip"
    New-Item -ItemType Directory -Force -Path $redisRuntime | Out-Null

    Write-Host "Downloading Redis $redisVersion into backend\runtime\redis ..." -ForegroundColor Cyan
    if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
        & curl.exe -fL --retry 3 --retry-delay 2 -o $zipPath $url
        Assert-LastExit "Downloading Redis"
    } else {
        Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing
    }

    Expand-Archive -LiteralPath $zipPath -DestinationPath $redisRuntime -Force
    $serverExe = Join-Path $redisRuntime "redis-server.exe"
    if (-not (Test-Path -LiteralPath $serverExe)) {
        throw "The Redis archive did not contain redis-server.exe. Check $redisRuntime."
    }
    Start-RedisProcess -ServerExe $serverExe -Port $Port
}

function Ensure-Redis {
    if ($DockerRedis) {
        Assert-Command "docker" "Start Docker Desktop before running development mode."
        & docker compose -f (Join-Path $rootDir "compose.dev.yaml") up --detach --wait
        Assert-LastExit "Development Redis"
        if (-not (Wait-Redis)) { throw "Development Redis did not become ready." }
        return
    }
    if (Test-RedisReachable) {
        Write-Host "Redis is already reachable at $redisUrl." -ForegroundColor Cyan
        return
    }

    $endpoint = Get-RedisEndpoint
    $host_ = $endpoint.Host
    # Starting a local server would not help when REDIS_URL points elsewhere, so
    # say what is actually wrong instead of starting an unused process.
    if ($host_ -ne "127.0.0.1" -and $host_ -ne "localhost" -and $host_ -ne "::1") {
        throw "Redis is unreachable at $redisUrl, which points at a remote host. Start that server, or unset REDIS_URL to use a local one."
    }

    $port = $endpoint.Port
    Write-Host "No Redis on 127.0.0.1:$port; preparing a local one ..." -ForegroundColor Cyan

    $onPath = Get-Command redis-server -ErrorAction SilentlyContinue
    if (-not $onPath) { $onPath = Get-Command redis-server.exe -ErrorAction SilentlyContinue }
    if ($onPath) {
        Write-Host "Using the redis-server found on PATH." -ForegroundColor Cyan
        Start-RedisProcess -ServerExe $onPath.Source -Port $port
    } else {
        $bundled = Join-Path $redisRuntime "redis-server.exe"
        if (Test-Path -LiteralPath $bundled) {
            Write-Host "Using the Redis previously unpacked into backend\runtime\redis." -ForegroundColor Cyan
            Start-RedisProcess -ServerExe $bundled -Port $port
        } else {
            Install-RedisFromArchive -Port $port
        }
    }

    if (-not (Wait-Redis)) {
        throw "Redis was started but never answered on port $port. See $(Join-Path $redisData 'redis.log')."
    }
    Write-Host "Redis is up on 127.0.0.1:$port." -ForegroundColor Cyan
}

try {
    Resolve-Uv
    Assert-Command "node" "Install Node.js 22.12 or newer."
    Assert-Command "npm.cmd" "Install Node.js 22.12 or newer."

    try {
        $nodeVersion = [version]((& node --version).TrimStart("v"))
        if ($nodeVersion -lt [version]"20.19.0") {
            Write-Host "Node $nodeVersion detected; Vite 7 needs 20.19+, and this project targets 22.12+." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "Could not read the Node.js version; continuing anyway." -ForegroundColor Yellow
    }

    Write-Host "Syncing backend dependencies..." -ForegroundColor Cyan
    Push-Location $backendDir
    try {
        if (-not $SkipInstall) {
            & uv sync --frozen
            Assert-LastExit "uv sync"
        }
        if (-not (Test-Path -LiteralPath $pythonExe)) { throw "Run without -SkipInstall once to install dependencies." }
        & $pythonExe -m app.dev_config
        Assert-LastExit "Local configuration"
        if ($DockerRedis) {
            $redisUrl = "redis://127.0.0.1:16379/0"
        } else {
            $redisUrl = (& $pythonExe -c "from app.config import Settings; print(Settings().redis_url or 'redis://127.0.0.1:6379/0')").Trim()
        }
        $env:REDIS_URL = $redisUrl
    } finally {
        Pop-Location
    }

    Ensure-Redis

    Write-Host "Applying database migrations and seeding..." -ForegroundColor Cyan
    Push-Location $backendDir
    try {
        & uv run alembic upgrade head
        Assert-LastExit "Database migration"
        & uv run python -m app.seed
        Assert-LastExit "Seeding"
        # Presentation baseline (admin_zhang, dr_wang, P20260001 ...).
        # Safe to repeat.
        & uv run python -m app.seed_demo
        Assert-LastExit "Demo seeding"
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
    if (-not $SkipInstall) {
    Push-Location $frontendDir
    try {
        & npm.cmd ci @npmArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend dependency installation failed. Check your registry and HTTP(S)_PROXY settings."
        }
    } finally {
        Pop-Location
    }
    }

    if ($NoServe) {
        Write-Host "Setup finished. For hot reload run: .\scripts\dev.ps1 -SkipInstall" -ForegroundColor Green
        exit 0
    }

    if (-not (Test-Path -LiteralPath $pythonExe)) {
        throw "Expected a virtual environment at $pythonExe, but it is missing. Re-run this script."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $frontendDir 'node_modules/vite/bin/vite.js'))) {
        throw "Frontend dependencies are missing. Run again without -SkipInstall."
    }

    $logDir = Join-Path $backendDir "runtime"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    Write-Host "Starting FastAPI and Vite. Logs: backend/runtime/*.log. Ctrl+C stops both." -ForegroundColor Cyan
    $apiArgs = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--no-access-log", "--log-level", "warning")
    if ($Reload) { $apiArgs += @("--reload", "--reload-dir", "app") }
    $api = Start-Process -FilePath $pythonExe -ArgumentList $apiArgs -WorkingDirectory $backendDir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir "api.log") -RedirectStandardError (Join-Path $logDir "api-error.log") -PassThru
    $web = Start-Process -FilePath "node" -ArgumentList @("node_modules/vite/bin/vite.js", "--host", "127.0.0.1") -WorkingDirectory $frontendDir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir "web.log") -RedirectStandardError (Join-Path $logDir "web-error.log") -PassThru

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
            throw "The API did not become ready. Check backend/runtime/api-error.log."
        }
        if ($web.HasExited) { throw "Vite exited. Check backend/runtime/web-error.log and port 5173." }
        while (-not $api.HasExited -and -not $web.HasExited) {
            Start-Sleep -Milliseconds 500
        }
    } finally {
        foreach ($server in @($api, $web)) {
            if ($server -and -not $server.HasExited) {
                # Uvicorn --reload owns a worker child; stop the entire tree.
                & taskkill.exe /PID $server.Id /T /F 2>$null | Out-Null
            }
        }
    }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
