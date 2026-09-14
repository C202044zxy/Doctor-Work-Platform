# Doctor Work Platform

A runnable foundation for the school project's doctor workspace: FastAPI, Vue 3,
SQLAlchemy/Alembic, SQLite, and Redis 7.
Scope, task numbering, ownership and status are tracked in
[docs/01-任务安排.md](docs/01-任务安排.md); what is actually built is in
[docs/03-实现现状.md](docs/03-实现现状.md); the rest of the doc set is indexed in
[docs/README.md](docs/README.md).
Setting the project up for the first time? Follow [docs/onboarding.md](docs/onboarding.md).

## Prerequisites

Install these once per machine. Do not install Python or Redis: uv downloads and manages
the Python 3.12 interpreter, and the startup scripts find a Redis server if one is on
`PATH`, otherwise unpack a portable one into the gitignored `backend/runtime/`. There is
no database to install at all: the database is a SQLite file, `backend/doctor.db`.

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

Docker Desktop is optional. It is only needed for the Compose stack described under
Quick start. Both modes use SQLite; neither installs a database on the host.

### Tool versions

| Tool | Version | Notes |
| ---- | ------- | ----- |
| uv | 0.9 or newer (0.12.12 verified) | Also downloads and manages the Python interpreter |
| Python | 3.12 or newer | Managed by uv; required by `backend/pyproject.toml`. Do not install it separately |
| Node.js | 22.12 or newer | Required by Vite 7. Version 20.19 works, but 22.12 is the target |
| Docker Engine | 24 or newer, with Compose v2 | Optional; only for the Compose stack |
| Redis | 7 | Required by authentication. The startup scripts use a server from `PATH`, or unpack a portable one into `backend/runtime/`; Compose runs `redis:7-alpine` |
| SQLite | — | No install: it is a file, `backend/doctor.db`. Compose keeps it on the `sqlite_data` volume |
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

Either script installs locked dependencies, prepares Redis, applies migrations, seeds
master data and the demo baseline, and starts both servers. It waits for the API to answer
before printing the URLs. Open http://127.0.0.1:5173; API documentation is at
http://127.0.0.1:8000/docs. Run the command again to restart; records persist in
`backend/doctor.db`.

Redis is a hard dependency of the login flow (tickets, verification codes, the JWT
blacklist, and login rate limiting), so the script makes sure one is running before it
starts the API. If it finds no `redis-server` on `PATH` it unpacks a portable build into
`backend/runtime/` (gitignored). When Redis is genuinely unreachable the app still serves
other endpoints, reporting `redis: "down"` in the health body.

Windows notes:

- `scripts\dev.cmd` wraps `dev.ps1` and bypasses the PowerShell execution policy, for
  machines that block scripts extracted from a downloaded zip.
- `dev.ps1` opens one window per server so you can read its log; closing a window stops
  that server. If Ctrl+C leaves a window behind, close it manually.
- `dev.ps1 -NoServe` installs dependencies, applies migrations, and seeds data without
  starting the servers. Use it to check that your environment is ready.
- In Git Bash, prefer `dev.ps1`: `dev.sh` runs there too, but Ctrl+C may leave an
  orphaned `uvicorn` process.

For the Compose stack, install Docker with Compose v2 and run:

```powershell
.\scripts\dev.ps1 docker
```

```bash
./scripts/dev.sh docker
```

Compose applies the same migrations and seeds automatically. The SQLite file and Redis use
persistent named volumes (`sqlite_data`, `redis_data`) and are reachable only inside the
Compose network. There is no database container.
The frontend and API use the same local URLs. Stop with Ctrl+C or `docker compose down`;
normal shutdown preserves the volumes.

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
| local (default) | `.\scripts\dev.ps1` / `./scripts/dev.sh` | Redis, FastAPI, and the Vite dev server | SQLite file, Redis | Day-to-day work, especially frontend, because Vite serves with hot reload |
| docker | `.\scripts\dev.ps1 docker` / `./scripts/dev.sh docker` | Redis 7, FastAPI, and the built frontend behind Nginx | SQLite and Redis, in named volumes | The full stack: integration, verification, and demonstrations |

Local mode is the default so that nobody needs Docker to write code. The full stack named
in the task acceptance criteria (Redis + backend + frontend, on SQLite) is the `docker`
mode, which serves the frontend as a static production build through Nginx and therefore
has no hot reload.

### Stopping

- Windows: press Ctrl+C in the terminal that started the script; the two server windows
  close with it. If a window stays open, close it manually.
- macOS and Linux: press Ctrl+C; the script kills both servers.
- Docker mode: press Ctrl+C, or run `docker compose down`. Shutting down normally keeps
  the SQLite and Redis volumes.

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
- Soft-delete patients while retaining their allergy rows; the deletion policy is written
  out under [Patient API](#patient-api-task-t13).
- Seed the three departments (`Information Technology`, `Cardiology`, `Neurology` -- in
  that order) and the roles `admin`, `senior`, and `junior` idempotently.
- Check liveness at `/api/health/live` and database/Redis readiness at `/api/health/ready`.
  Readiness returns HTTP 503 if a configured dependency is unavailable. `/health` and
  `/api/health` are different: they are byte-identical aliases that always return 200 and
  report dependency state in the body.
- Inspect and exercise the documented API through FastAPI Swagger.

The authentication backend is complete: bcrypt, the two-step login ticket/JWT exchange,
logout revocation, department patient scope, temporary grants with a minute expiry scan,
email signup with activation, and login rate limiting. Patient and allergy APIs require a
bearer token. The frontend session is real -- it attaches the token and restores `/api/me`
-- and `PatientListView` is the one business screen talking to the live service. Everything
else on the frontend is still fabricated; see [docs/03-实现现状.md](docs/03-实现现状.md) §6.

### Provision an account

Run from `backend/`, after migrations and seed. The password is prompted without echo;
there are no seeded passwords or automatically created privileged accounts.

```bash
uv run python -m app.create_user --username admin_zhang --name "Zhang Wei" --email admin@example.test --title admin --department "Information Technology"
```

The database is the SQLite file named by `DATABASE_URL` (default `backend/doctor.db`); the
schema is installed through Alembic. Configure `REDIS_URL` for the runtime and retain the
same `JWT_SECRET` and `PATIENT_DATA_KEY` across backend processes. Credentials must not be
committed.

### Patient API

`GET /api/patients` accepts `name`, `patient_no`, repeated `symptom_tags`,
`admitted_from`, `admitted_to`, `page`, and `size`. Filters combine with AND, with any
matching supplied tag accepted. The envelope is `{code, message, data}`, where
`data` contains `{items, total, page, size}`. Results include only the caller's department
and currently granted patients; administrators see all live patients.

`patient_no` is generated by the server as `P<year><0001-style sequence>` and cannot be
edited. Phone numbers and national ID numbers are encrypted with AES-256-GCM before they
reach the database, and every response masks them (`138****1234`,
`110101********1234`).

**Deletion policy.** `DELETE /api/patients/{patient_no}` soft-deletes the patient.
Allergies and audit records remain; the patient disappears from API reads.

## Layout

```text
backend/app/          Configuration, database models, API, schemas, seed commands
backend/migrations/   Versioned Alembic schema migrations
backend/tests/        API, persistence, validation, and dependency health tests
backend/start.sh      One-command startup for macOS, Linux, and WSL
backend/start.ps1     One-command startup for Windows PowerShell
frontend/src/         Vue patient workspace and styles
scripts/dev.sh        Thin forwarder to backend/start.sh, plus a docker mode
scripts/dev.ps1       Thin forwarder to backend/start.ps1, plus a docker mode
scripts/dev.cmd       Windows wrapper that bypasses the PowerShell execution policy
scripts/backup.sh     SQLite online-backup snapshot, written into backups/
scripts/smoke.py      Checks a running stack through the frontend API proxy
compose.yaml          Redis, API, and frontend services (SQLite on a volume)
docs/                 The document set; start at docs/README.md
```

## Configuration

Copy `backend/.env.example` to `backend/.env` for local overrides. Compose uses the
root `.env.example` as a reference: copy it to `.env` to override demo credentials.
Neither file is committed. Restart services after configuration changes.

SMTP is required for the password/email login flow, so an end-to-end login demo needs the
`SMTP_*` values below. Redis is required too, and the startup scripts arrange it.

### Environment variables

| Variable | Read by | Default | Purpose |
| -------- | ------- | ------- | ------- |
| `DATABASE_URL` | backend | `sqlite:///./doctor.db` | SQLAlchemy connection URL. Compose overrides it with `sqlite:////data/doctor.db`, backed by the `sqlite_data` volume. |
| `REDIS_URL` | backend | unset | Redis connection URL. While unset, Redis stays disabled and `/health` reports `redis: "disabled"`. |
| `JWT_SECRET` | backend/Compose | unset | HS256 signing secret; must be set, and is one of the values that yields 503 when missing. Replace outside isolated development. |
| `PATIENT_DATA_KEY` | backend | `dev-only-insecure-patient-data-key` | Passphrase hashed into the AES-256 key for the patient phone and ID columns. Every process that reads the table must use the same value; change it outside a local demo. |
| `SCHEDULER_ENABLED` | backend | `true` | Start the minute-expiry job that revokes lapsed temporary grants; atomic updates prevent duplicate worker audits. |
| `DEMO_PASSWORD` | `app.seed_demo` | `Demo@2026` | Shared password for the four demo accounts. Local demo data only. |
| `npm_config_registry` | dev scripts | `https://registry.npmjs.org` | Registry used by `npm ci`. |
| `HTTPS_PROXY` and `HTTP_PROXY` | dev scripts | unset | Forwarded to `npm ci` as `--proxy` and `--https-proxy`. |
| `SMOKE_BASE_URL` | `scripts/smoke.py` | `http://127.0.0.1:5173` | Base URL the smoke test calls. |
| `SMOKE_ACCESS_TOKEN` | smoke script | unset | Required for authenticated patient smoke checks; CI provisions a disposable identity inside Compose. |
| `SMOKE_REQUIRE_REDIS` | `scripts/smoke.py` | `1` | Set it to `0` when running against a deployment with Redis disabled. |
| `BACKUP_DIR` | `scripts/backup.sh` | `backups` | Directory that receives database snapshots. |
| `BACKUP_KEEP` | `scripts/backup.sh` | `7` | How many of the newest archives to keep. |

## Deployment

Minimum single-host deployment. Configure Redis, `JWT_SECRET`, and `PATIENT_DATA_KEY`;
SMTP for the email login channel. **Do not expose the face login route.** See
`CLAUDE.md` for the reason.

### Backend under uvicorn

Prepare the environment and the database once:

```bash
uv sync --frozen --no-dev
uv run alembic upgrade head
uv run python -m app.seed
```

Add `uv run python -m app.seed_demo` only if you want the demo accounts and patients.

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

`scripts/backup.sh` snapshots the SQLite database into `backups/`, then deletes everything
beyond the newest `BACKUP_KEEP` archives (7 by default). Both modes use SQLite's online
backup API rather than copying the file, so a snapshot taken while the API is writing is
still consistent.

```bash
./scripts/backup.sh          # docker mode: snapshot inside the backend container
./scripts/backup.sh sqlite   # local mode: snapshot backend/doctor.db (also `local`)
```

Run it from Git Bash or WSL on Windows. The snapshot lands in `backups/` as
`doctor-YYYYMMDD-HHMMSS.db`. Restore by stopping the stack, replacing `backend/doctor.db`
with the snapshot, and restarting.

The Compose stack also keeps the SQLite file and Redis data in named volumes, so stopping
the stack is not a backup: run this script before wiping volumes or reinstalling.

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
SQLite databases and use a Redis test double, so they never touch a real Redis or a
real server process. The CI jobs described under [What CI verifies](#what-ci-verifies)
separately exercise real Redis behavior.

Frontend commands run from `frontend/`:

```bash
npm ci
npm run dev
npm run build
```

Use four-space Python indentation and Ruff formatting. Use two-space indentation
in Vue/JavaScript. Keep API routes under `/api` — with one required exception,
`GET /health`, which must exist as an alias of `GET /api/health`. Every JSON
response uses the `{code, message, data}` envelope with `code: 0` for success;
lists are paginated as `data: {items, total, page, size}`. **`docs/api/openapi.yaml`
is the source of truth for the shape of every request and response** — see
[`docs/api/API-索引.md`](docs/api/API-索引.md) for the index and the reasoning behind
each convention. The Vite development proxy and Nginx container proxy
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
| `checks` | ubuntu-latest | Backend tests and Ruff, frontend production build, then `scripts/dev.sh docker` starts Redis, backend, and frontend; `scripts/smoke.py` exercises the API through the frontend proxy; the real SQLite/Redis security behavior is verified; `scripts/backup.sh docker` snapshots the SQLite database |
| `windows-one-command` | windows-latest | One command, `scripts\dev.ps1`, on a clean checkout with only uv and Node installed: it installs dependencies, prepares Redis, migrates, seeds, and serves both servers; startup/readiness and refusal of anonymous patient access are checked through the Vite proxy |

The Windows job runs local mode. Read the per-step durations in the Actions log when you
need evidence for the ten-minute first-run budget.

To reproduce the missing-dependency scenario locally, run a startup script on a machine
without Docker and check that it prints the install hint and exits non-zero:

```bash
bash scripts/dev.sh docker; echo "exit=$?"
```

### Face login (M1)

Enter an existing account username, select **Sign in with face**, allow camera
access, then select **Capture photo and sign in**. The browser captures a JPEG
and sends it to `POST /api/auth/face/login` as `{username, photo}` (a base64 JPEG
data URL). The server validates the photo and account, calls `match_face` in
`backend/app/face_login.py`, and issues the existing two-hour session.

**Demo behavior:** `match_face` intentionally returns `True` for every attempt.
There is no face detection, comparison, enrollment, or liveness check yet;
any valid JPEG can sign in as any existing active username. Photos are processed
in memory and are not stored. Implement the TODO before using this as identity
verification. Password/email sign-in remains available.

Camera access requires HTTPS or localhost. No passkey or device biometric setup
is needed. Existing passkey database records are retained for migration
compatibility but are no longer used, and passkey endpoints have been removed.

Validation: `cd backend && uv run pytest -q`; `cd frontend && npm test && npm run build`.
Manual check: enter username → open camera → capture → confirm account in the
workspace → sign out. Also check permission denial, cancel, and retry.

For password/email login, configure SMTP in `backend/.env` (local) or `.env`
(Compose):

```dotenv
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_FROM=noreply@example.com
SMTP_USERNAME=your-smtp-user
SMTP_PASSWORD=your-smtp-password
SMTP_STARTTLS=true
```

Provision an account with `cd backend && uv run python -m app.create_user` if
needed. Redis is required for session revocation and email verification. SMTP
uses a 10-second timeout; delivery is limited to one attempt per minute and 20
per UTC day per account. SMTP failures consume an attempt.

### Email signup (M1 extension)

Choose **Create an account with email** on the login page. Enter a username, full
name, email, password (at least eight characters, at most 72 UTF-8 bytes), and an
existing department name. Redis and the existing `SMTP_*` settings are required.
The emailed six-digit code expires in five minutes; requesting a new signup code
requires waiting 60 seconds. Signup requests are limited per email and source IP.

Email verification creates a **pending junior** account. An administrator must
check staff identity and confirm the department before activating it locally:

```sh
cd backend
uv run python -m app.activate_user --username new_doctor --department "Cardiology"
```

After activation, use the existing username/password and email-code sign-in flow.
No database migration is needed: enrollment uses the existing user status field.

SMTP port `465` uses implicit TLS (`SMTP_SSL`); other ports use STARTTLS when
`SMTP_STARTTLS=true`. For a 163 Mail sender, use `smtp.163.com`, port `465`,
`SMTP_STARTTLS=false`, and the mailbox SMTP authorization code as `SMTP_PASSWORD`.
