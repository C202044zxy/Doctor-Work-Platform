# Repository Guidelines

## Sources of Truth

Read these before changing anything. Everything else in the repository is either
derived from them or obsolete.

| Question | Authority |
|---|---|
| Scope, modules, task IDs, ownership, status, schedule, capacity, tech and deploy choices | `docs/01-任务安排.md` |
| Test scenarios, demo baseline data, simulation red lines, defence talking points | `docs/02-测试场景.md` |
| Request/response shape (field names, enums, status codes) | `docs/api/openapi.yaml`, indexed by `docs/api/API-索引.md` |
| What is actually built right now | the code, plus `docs/03-实现现状.md` |

Every pre-overhaul document was **deleted on 2026-09-14**, `docs/archive/` included.
Several of those files claimed to be authoritative while describing features that were
never built, so nothing was kept "for provenance". There is no archive: do not go looking
for one, and treat any citation to a missing document as a stale reference to fix. Old
task IDs are traceable through the mapping table in `docs/01` §7.1; history lives in
`git log`.

One exception remains on disk: **`新任务安排.md`** at the repo root, a pre-overhaul
document whose deletion was blocked by a permissions failure. Do not treat its contents as
fact; run `git rm 新任务安排.md` when you have the permissions.

`README.md` covers install, run, and verify. Setting up for the first time? Follow
`docs/onboarding.md`.

## Project Structure & Module Organization

- `backend/app/` -- FastAPI application. `main.py` builds the app, exception handlers, health endpoints, and the department, patient, and audit routes; `models.py` (SQLAlchemy), `schemas.py` (Pydantic), `crypto.py` (AES-256-GCM and masking helpers for patient identifiers), `config.py`, `database.py`, `seed.py` (master data: roles and departments), `seed_demo.py` (presentation baseline).
- `backend/migrations/` -- Alembic revisions. Schema changes reach a database only through a revision.
- `backend/tests/` -- pytest suite; each test migrates a throwaway SQLite database.
- `frontend/src/` -- Vue 3 single-page workspace and styles.
- `backend/start.sh` / `backend/start.ps1` -- the real one-command deploy scripts (POSIX and Windows). `scripts/dev.sh` / `dev.ps1` / `dev.cmd` are thin forwarders to them that also accept a `docker` mode.
- `scripts/smoke.py` -- checks a running stack.
- `compose.yaml` -- Redis 7, API, and frontend services. There is no database container: the database is a SQLite file on a volume. `.github/workflows/ci.yml` starts that stack through `scripts/dev.sh docker`, then runs the stack smoke test, pytest, Ruff, the frontend build, and the backup script.

## Stack

FastAPI, SQLAlchemy 2.0, Alembic, and Pydantic v2 on Python 3.12 managed by uv;
Vue 3, Vite, and Element Plus on the frontend.

- **SQLite** is the database, not MySQL. The default file is `backend/doctor.db`.
- **Redis is a hard dependency of authentication** (login tickets, verification codes, the JWT blacklist, and login rate limiting), not an optional cache. When Redis is down the login flow is unusable, but other endpoints still return 200 with `redis: "down"`.
- The frontend uses native `fetch` and `sessionStorage`. No Pinia, no axios.
- **All user-facing frontend text is English.** Do not add Chinese UI strings.

## Build, Test, and Development Commands

From `backend/`:

- `uv sync --frozen` -- install locked dependencies.
- `uv run pytest -q` -- run the test suite.
- `uv run ruff check app tests migrations` and `uv run ruff format --check app tests migrations` -- lint and format gate.
- `uv run alembic upgrade head` -- apply migrations.
- `uv run alembic revision --autogenerate -m "describe change"` -- create a revision; review it before applying.
- `uv run alembic check` -- confirm models and migrations agree.
- `uv run python -m app.seed` -- seed departments and roles.
- `uv run python -m app.seed_demo` -- seed the presentation baseline (idempotent).

From `frontend/`: `npm ci`, `npm run dev`, `npm run build`.

From the repository root: `./scripts/dev.sh` or `.\scripts\dev.ps1` prepares and starts the local stack; the `docker` argument starts the Compose stack; `-NoServe` prepares without starting servers. Arguments after `docker` are forwarded to `docker compose up`, so `--detach --wait` starts it in the background; use long-form flags on Windows, because `-d` binds to PowerShell's own `-Debug`. These commands work unchanged in PowerShell, Git Bash, and WSL.

## Coding Style & Naming Conventions

- Python: four-space indentation, double quotes, Ruff formatting with `line-length = 100`.
- API: `docs/api/openapi.yaml` is the **source of truth for request and response shape**, and `docs/api/API-索引.md` is its index. Generate from it rather than inventing fields. It is tracked in git, so pull before generating: a stale copy silently produces the wrong fields.
- `backend/app/auth_schemas.py` is **generated** by `scripts/generate_auth_schemas.py` from `openapi.yaml`'s `components.schemas`. Never hand-edit it; change the YAML and regenerate.
- API envelope: every JSON response is `{code, message, data}`, with `code: 0` for success. Lists are paginated as `data: {items, total, page, size}`; errors carry a non-zero `code` and a human-readable `message`, not a nested `error` object. The single exception is `GET /metrics`, which speaks Prometheus text format.
- API paths live under `/api`, **except** the health check: `GET /health` is a required alias of `GET /api/health` with a byte-identical body. The health payload's database key is `db` (values `ok` / `down` / `disabled`), and a dependency outage never changes the status code.
- Roles are `admin` / `senior` / `junior`. The JWT claim carrying the role is named `title`. Departments are, in this fixed order, `Information Technology`, `Cardiology`, `Neurology` -- tests index into that order, so never reorder them.
- Authorization failures use two distinct codes: **403** when the role lacks the permission, **404** when the object is outside the caller's department scope.
- Vue and JavaScript: two-space indentation, single quotes, no semicolons.
- Task and module identifiers come from `docs/01-任务安排.md`. The current system is `M0`–`M9`, `S1`–`S6`, and `D01`–`D07`. Legacy identifiers `T01`–`T37` and `M01`–`M07` may appear **only** in that document's §7 mapping table -- nowhere else, including branches, PR descriptions, and code comments.
- Keep `scripts/dev.sh` and `scripts/dev.ps1` in sync, and keep `dev.ps1` ASCII-only: Windows PowerShell 5.1 decodes a script without a byte-order mark as ANSI.

## Testing Guidelines

- Tests live in `backend/tests/` and are named `test_*.py`; run them with `uv run pytest -q` from `backend/`.
- The suite migrates isolated SQLite databases and uses a Redis test double, so it does not exercise a real Redis. The CI jobs cover that separately.
- Add or extend a test with every behavior change, including validation failures, not-found paths, and list filters.
- Acceptance checks should cover the three demonstration flows in `docs/02-测试场景.md`, including role and department access, allergy blocking, archive locking, and consultations.

## Honesty Rules

These are red lines, not style preferences.

- **Never describe a simulation as working capability.** `backend/app/face_login.py`'s `match_face()` returns `True` unconditionally, and `/api/auth/face/login` is on the anonymous allowlist: any valid JPEG plus the username of an existing active account yields a real two-hour token. It must always be labelled a simulation in the UI, in the response body (`"mock": true`), and in any document that mentions it.
- Simulation modules must sit behind a replaceable provider interface, not hard-coded fake logic in business code.
- **Status columns only record what the code does.** No code means not started; code without the scenarios exercised means at most partially complete. Do not mark a module complete because a document claims it is.
- `audit_logs` is append-only, enforced by database triggers installed by migration `c0311060809b`. Do not add update or delete paths.

## Commit & Pull Request Guidelines

Follow the existing `type: imperative summary` pattern, for example `feat: add allergy endpoints`. Keep changes focused.

PRs should explain the change, reference task IDs from `docs/01-任务安排.md` and scenario IDs from `docs/02-测试场景.md`, and list the validation performed (`uv run pytest -q`, Ruff, `npm run build`). For scope or schedule changes, state the capacity impact and record unresolved decisions explicitly. Work on a feature branch and open a pull request so CI runs before merge, matching the existing history.

Never commit `JWT_SECRET`, `PATIENT_DATA_KEY`, SMTP credentials, `.env`, the SQLite database file, or the Redis binaries the startup scripts unpack into `backend/runtime/`.
