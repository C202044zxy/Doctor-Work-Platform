# Doctor Work Platform

A runnable foundation for the school project's doctor workspace: FastAPI, Vue 3,
SQLAlchemy/Alembic, and a Docker Compose stack with MySQL 8.4 and Redis 7.
Scope and future clinical workflows are tracked in [project_plan.md](project_plan.md).
Setting the project up for the first time? Follow [docs/onboarding.md](docs/onboarding.md).

## Prerequisites

Install these once per machine. Do not install Python, MySQL, or Redis: uv downloads and
manages the Python 3.12 interpreter, and local mode stores data in SQLite with Redis
disabled.

The startup scripts therefore check for uv, Node.js, and Docker, but deliberately not for
Python: uv resolves the interpreter itself, so a host Python installation is neither
required nor used.

Windows (PowerShell):

```powershell
winget install --id astral-sh.uv -e
winget install --id OpenJS.NodeJS.LTS -e
```

macOS:

```bash
brew install uv node
```

Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# Then install Node.js 22.12 or newer with your package manager or nvm.
```

Close and reopen the terminal after installing, then confirm both commands exist:

```powershell
uv --version
node --version
```

`node --version` must report v22.12 or newer.

Clone the repository with git instead of downloading a zip: a zip adds a mark of the web
that can make Windows refuse to run `dev.ps1`, and it leaves you without the branch
history the team works from.

Docker Desktop is optional. It is only needed for the MySQL/Redis stack described under
Quick start.

### Tool versions

| Tool | Version | Notes |
| ---- | ------- | ----- |
| uv | 0.9 or newer (0.12.12 verified) | Also downloads and manages the Python interpreter |
| Python | 3.12 or newer | Managed by uv; required by `backend/pyproject.toml`. Do not install it separately |
| Node.js | 22.12 or newer | Required by Vite 7. Version 20.19 works, but 22.12 is the target |
| Docker Engine | 24 or newer, with Compose v2 | Optional; only for the MySQL/Redis stack |
| MySQL | 8.4 | Runs in `compose.yaml`; never installed on the host |
| Redis | 7 | Runs in `compose.yaml`; never installed on the host |
| Git | any recent version | Clone the repository with git, never from a zip |

## Quick start

These commands run from the repository root; the prompt should show the
`Doctor-Work-Platform` directory. The first run downloads a Python interpreter, backend
packages, and frontend packages, so expect several minutes and a few hundred megabytes.

Windows (PowerShell):

```powershell
.\scripts\dev.ps1
```

macOS, Linux, or WSL:

```bash
./scripts/dev.sh
```

Either script installs locked dependencies, applies migrations, seeds departments and
roles, and starts both servers. It waits for the API to answer before printing the URLs.
Open http://127.0.0.1:5173; API documentation is at http://127.0.0.1:8000/docs. Run the
command again to restart; records persist in `backend/doctor.db`. Local mode uses SQLite
and disables Redis unless `REDIS_URL` is configured in `backend/.env`.

Windows notes:

- `scripts\dev.cmd` wraps `dev.ps1` and bypasses the PowerShell execution policy, for
  machines that block scripts extracted from a downloaded zip.
- `dev.ps1` opens one window per server so you can read its log; closing a window stops
  that server. If Ctrl+C leaves a window behind, close it manually.
- `dev.ps1 -NoServe` installs dependencies, applies migrations, and seeds data without
  starting the servers. Use it to check that your environment is ready.
- In Git Bash, prefer `dev.ps1`: `dev.sh` runs there too, but Ctrl+C may leave an
  orphaned `uvicorn` process.

For the MySQL/Redis stack, install Docker with Compose v2 and run:

```powershell
.\scripts\dev.ps1 docker
```

```bash
./scripts/dev.sh docker
```

Compose applies the same migrations and seeds automatically. MySQL and Redis use
persistent named volumes and are accessible only inside the Compose network.
The frontend and API use the same local URLs. Stop with Ctrl+C or `docker compose down`;
normal shutdown preserves the database volumes.

Extra arguments are forwarded to `docker compose up`, which is how CI starts the stack
without tying up a terminal:

```powershell
.\scripts\dev.ps1 docker --detach --wait
```

```bash
./scripts/dev.sh docker --detach --wait
```

Use long-form flags on Windows: Windows PowerShell binds `-d` to its own `-Debug` switch
and never passes it to Docker.

### Modes

| Mode | Command | Running services | Data stores | Use it for |
| ---- | ------- | ---------------- | ----------- | ---------- |
| local (default) | `.\scripts\dev.ps1` / `./scripts/dev.sh` | FastAPI and the Vite dev server | SQLite, Redis disabled | Day-to-day work, especially frontend, because Vite serves with hot reload |
| docker | `.\scripts\dev.ps1 docker` / `./scripts/dev.sh docker` | MySQL 8.4, Redis 7, FastAPI, and the built frontend behind Nginx | MySQL and Redis, in named volumes | The full stack: integration, verification, and demonstrations |

Local mode is the default so that nobody needs Docker to write code. The full stack named
in the task acceptance criteria (MySQL + Redis + backend + frontend) is the `docker` mode,
which serves the frontend as a static production build through Nginx and therefore has no
hot reload.

### Stopping

- Windows: press Ctrl+C in the terminal that started the script; the two server windows
  close with it. If a window stays open, close it manually.
- macOS and Linux: press Ctrl+C; the script kills both servers.
- Docker mode: press Ctrl+C, or run `docker compose down`. Shutting down normally keeps
  the MySQL and Redis volumes.

## Startup troubleshooting

If npm reports `Exit handler never called!`, inspect the npm log for preceding
fetch errors. An unreachable registry or proxy can cause installation to fail.
The startup script defaults to the official npm registry and uses `HTTPS_PROXY`
(or `HTTP_PROXY`) when set, overriding stale npm-specific proxy settings for that
invocation. Set `npm_config_registry` explicitly if you need another registry.
It does not change your global npm configuration.

### Windows

- `Missing required command: uv` -- uv is not on `PATH`. Install it with
  `winget install --id astral-sh.uv -e`, then open a new terminal.
- `uv` is installed but still not found -- the terminal was started before the
  installer updated `PATH`. Log off and back on to refresh it, or reload it in the
  current session with
  `$env:PATH = [Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [Environment]::GetEnvironmentVariable("PATH","User")`.
  `dev.ps1` also locates the winget package directory itself, so it usually works
  without this.
- `dev.ps1 cannot be loaded because running scripts is disabled` -- run
  `scripts\dev.cmd` instead, or run
  `powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1`.
- Ports 5173 or 8000 already in use -- stop the previous run, or close the leftover
  server windows.

## Basic functionality

- Create, read, update, and delete synthetic patients, each with a server-generated
  `patient_no` such as `P20260001`.
- Search by fuzzy name, exact patient number, exact symptom tag, and admission-date
  range; the four filters combine with AND and results page by `created_at` descending.
- Store patients and transactional create/update/delete audit entries in the database.
- Store phone numbers and national ID numbers as AES-256-GCM ciphertext, and return
  masked values only, such as `138****1234`.
- Delete patients with a cascade to their allergy rows; the deletion policy is written
  out under [Patient API](#patient-api-task-t13).
- Seed two departments and three provisional roles without duplicate records.
- Check liveness at `/api/health/live` and database/Redis readiness at `/api/health/ready`.
  Readiness returns HTTP 503 if a configured dependency is unavailable.
- Inspect and exercise the documented API through FastAPI Swagger.

This is an unauthenticated local development demo. Use synthetic data only.
User and allergy tables are foundations; login, RBAC, 2FA, allergy validation,
EMR workflows, consultation features, and a full audit trail are not implemented.
The provisional role names require confirmation against task T08.

### Patient API (task T13)

`GET /api/patients` accepts `q` (fuzzy name), `patient_no` (exact), `symptom_tag` (exact
tag), `admitted_from` and `admitted_to` (inclusive dates), `offset`, and `limit`. Every
filter is optional and they combine with AND; with no filter the whole table is returned.
The payload is `{"data": [...], "total": n}`, ordered by `created_at` descending. Tags are
stored as `,tag,tag,`, so `symptom_tag=胸痛` matches that tag exactly instead of matching a
longer tag by accident.

`patient_no` is generated by the server as `P<year><0001-style sequence>` and cannot be
edited. Phone numbers and national ID numbers are encrypted with AES-256-GCM before they
reach the database, and every response masks them (`138****1234`,
`110101********1234`).

**Deletion policy.** `DELETE /api/patients/{id}` is a hard delete, not a soft delete.
Allergy rows cascade away through the foreign key, audit-log rows keep the numeric patient
id as a historical reference and are never deleted, and the record stops appearing in
list, detail, and search results. A patient number freed by a delete can be reissued.

## Layout

```text
backend/app/          Configuration, database models, API, schemas, seed command
backend/migrations/   Versioned Alembic schema migrations
backend/tests/        API, persistence, validation, and dependency health tests
frontend/src/         Vue patient workspace and styles
scripts/dev.sh        Local and Docker startup for macOS, Linux, and WSL
scripts/dev.ps1       Local and Docker startup for Windows PowerShell
scripts/dev.cmd       Windows wrapper that bypasses the PowerShell execution policy
scripts/backup.sh     mysqldump or SQLite backup, written into backups/
scripts/smoke.py      Checks a running stack through the frontend API proxy
compose.yaml          MySQL, Redis, API, and frontend services
docs/onboarding.md    Step-by-step fresh-machine walkthrough for a new teammate
```

## Configuration

Copy `backend/.env.example` to `backend/.env` for local overrides. Compose uses the
root `.env.example` as a reference: copy it to `.env` to override demo credentials.
Neither file is committed. Percent-encode special characters in credentials when
constructing a `DATABASE_URL`. Restart services after configuration changes.
Do not expose this demo to a shared network before implementing authentication.

### Environment variables

| Variable | Read by | Default | Purpose |
| -------- | ------- | ------- | ------- |
| `DATABASE_URL` | backend | `sqlite:///./doctor.db` | SQLAlchemy connection URL. Compose overrides it with a `mysql+pymysql://` URL. Percent-encode special characters in credentials. |
| `REDIS_URL` | backend | unset | Redis connection URL. While unset, Redis stays disabled and `/api/health/ready` reports `redis: disabled`. |
| `PATIENT_DATA_KEY` | backend | `dev-only-insecure-patient-data-key` | Passphrase hashed into the AES-256 key for the patient phone and ID columns (T13). Every process that reads the table must use the same value; change it outside a local demo. |
| `MYSQL_DATABASE` | Compose | `doctor_platform` | Database created by the MySQL service. |
| `MYSQL_USER` | Compose | `doctor` | Application database user. |
| `MYSQL_PASSWORD` | Compose | `doctor_local_password` | Application database password. |
| `MYSQL_ROOT_PASSWORD` | Compose | `root_local_password` | MySQL root password. |
| `npm_config_registry` | dev scripts | `https://registry.npmjs.org` | Registry used by `npm ci`. |
| `HTTPS_PROXY` and `HTTP_PROXY` | dev scripts | unset | Forwarded to `npm ci` as `--proxy` and `--https-proxy`. |
| `SMOKE_BASE_URL` | `scripts/smoke.py` | `http://127.0.0.1:5173` | Base URL the smoke test calls. |
| `SMOKE_REQUIRE_REDIS` | `scripts/smoke.py` | `1` | Set it to `0` when Redis is disabled, which is the case in local mode. |
| `BACKUP_DIR` | `scripts/backup.sh` | `backups` | Directory that receives database dumps. |
| `BACKUP_KEEP` | `scripts/backup.sh` | `7` | How many of the newest archives to keep. |

## Deployment

Minimum single-host deployment. This is still a development demo: authentication is not
implemented, so do not expose it to a shared network.

### Backend under uvicorn

Prepare the environment and the database once:

```bash
uv sync --frozen --no-dev
uv run alembic upgrade head
uv run python -m app.seed
```

Then run uvicorn on the loopback interface so that only the reverse proxy is publicly
reachable:

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
```

Set `DATABASE_URL` and `REDIS_URL` in `backend/.env` first; see the environment variable
table above.

### Nginx

Build the frontend once with `npm ci && npm run build` in `frontend/`, then serve the
built files and proxy `/api` to uvicorn:

```nginx
server {
    listen 80;
    server_name _;

    root /srv/doctor-work-platform/frontend/dist;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Forwarding `X-Real-IP` matters because the audit trail records client IP addresses;
without it every entry shows the proxy address instead.

### Backups

`scripts/backup.sh` dumps the MySQL database, or copies the SQLite file, into `backups/`,
then deletes everything beyond the newest `BACKUP_KEEP` archives (7 by default).

```bash
./scripts/backup.sh          # docker mode: mysqldump inside the MySQL container
./scripts/backup.sh sqlite   # local mode: copy backend/doctor.db
```

Run it from Git Bash or WSL on Windows. Without either, the same dump from PowerShell:

```powershell
docker compose exec -T mysql sh -c 'exec mysqldump --single-transaction --databases "$MYSQL_DATABASE" -u"$MYSQL_USER" -p"$MYSQL_PASSWORD"' > backups\mysql.sql
```

Restore a dump with:

```bash
docker compose exec -T mysql sh -c 'exec mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD"' < backups/mysql-YYYYMMDD-HHMMSS.sql
```

The Compose stack also keeps MySQL and Redis data in named volumes, so stopping the stack
is not a backup: run this script before wiping volumes or reinstalling.

## Development and verification

Backend commands run from `backend/`:

```bash
uv sync --frozen
uv run pytest -q
uv run ruff check app tests migrations
uv run ruff format --check app tests migrations
uv run alembic upgrade head
uv run alembic check
uv run python -m app.seed
```

For schema changes, update models, run `uv run alembic revision --autogenerate -m
"describe change"`, review the migration, then apply it. Tests migrate isolated
SQLite databases; Redis readiness uses a test double. They do not validate MySQL
server behavior. The CI jobs described under [What CI verifies](#what-ci-verifies)
separately exercise real MySQL and Redis.

Frontend commands run from `frontend/`:

```bash
npm ci
npm run dev
npm run build
```

Use four-space Python indentation and Ruff formatting. Use two-space indentation
in Vue/JavaScript. Keep API routes under `/api`; success payloads use `data` and
errors use `error.message`. The Vite development proxy and Nginx container proxy
route browser API requests to FastAPI without cross-origin configuration.

`dev.sh` and `dev.ps1` must keep the same set of commands; when you change one, change
the other. Keep `dev.ps1` ASCII-only: Windows PowerShell 5.1 decodes a script without a
byte-order mark as ANSI, which corrupts non-ASCII text.

Framework references: [FastAPI lifecycle](https://fastapi.tiangolo.com/advanced/events/)
and [Vite setup](https://vite.dev/guide/).

### What CI verifies

`.github/workflows/ci.yml` runs on every push and pull request, and can be started by hand
from the Actions tab. It covers the acceptance scenarios for the startup scripts, so a
red run is the first sign that the one-command startup broke.

| Job | Runner | What it proves |
| --- | ------ | -------------- |
| `checks` | ubuntu-latest | Backend tests and Ruff, frontend production build, then `scripts/dev.sh docker` starts MySQL, Redis, backend, and frontend; `scripts/smoke.py` exercises the API through the frontend proxy; `scripts/backup.sh docker` writes a MySQL dump |
| `windows-one-command` | windows-latest | One command, `scripts\dev.ps1`, on a clean checkout with only uv and Node installed: it installs dependencies, migrates, seeds, and serves both servers; the same smoke test runs through the Vite proxy |

The Windows job runs local mode, so it sets `SMOKE_REQUIRE_REDIS=0`; local mode disables
Redis by design. Read the per-step durations in the Actions log when you need evidence for
the ten-minute first-run budget.

To reproduce the missing-dependency scenario locally, run a startup script on a machine
without Docker and check that it prints the install hint and exits non-zero:

```bash
bash scripts/dev.sh docker; echo "exit=$?"
```
