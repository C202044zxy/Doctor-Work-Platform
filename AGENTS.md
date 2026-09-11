# Repository Guidelines

## Project Structure & Module Organization

`project_plan.md` is the source of truth for baseline scope, task IDs, ownership, dependencies, capacity, milestones, and unresolved decisions. `README.md` documents how to install, run, and verify the stack.

- `backend/app/` -- FastAPI application. `main.py` builds the app, exception handlers, health endpoints, and the department, patient, and audit routes; `models.py` (SQLAlchemy), `schemas.py` (Pydantic), `crypto.py` (AES-256-GCM and masking helpers for patient identifiers), `config.py`, `database.py`, `seed.py`.
- `backend/migrations/` -- Alembic revisions. Schema changes reach a database only through a revision.
- `backend/tests/` -- pytest suite; each test migrates a throwaway SQLite database.
- `frontend/src/` -- Vue 3 single-page workspace and styles.
- `scripts/` -- `dev.sh` (macOS, Linux, WSL), `dev.ps1` (Windows PowerShell), `dev.cmd` (execution-policy wrapper), `smoke.py` (checks a running stack).
- `compose.yaml` -- MySQL 8.4, Redis 7, API, and frontend services. `.github/workflows/ci.yml` starts that stack through `scripts/dev.sh docker`, then runs the stack smoke test, pytest, Ruff, the frontend build, and the backup script.

## Build, Test, and Development Commands

From `backend/`:

- `uv sync --frozen` -- install locked dependencies.
- `uv run pytest -q` -- run the test suite.
- `uv run ruff check app tests migrations` and `uv run ruff format --check app tests migrations` -- lint and format gate.
- `uv run alembic upgrade head` -- apply migrations.
- `uv run alembic revision --autogenerate -m "describe change"` -- create a revision; review it before applying.
- `uv run alembic check` -- confirm models and migrations agree.
- `uv run python -m app.seed` -- seed departments and roles.

From `frontend/`: `npm ci`, `npm run dev`, `npm run build`.

From the repository root: `./scripts/dev.sh` or `.\scripts\dev.ps1` prepares and starts the local stack; the `docker` argument starts the Compose stack; `-NoServe` prepares without starting servers. Arguments after `docker` are forwarded to `docker compose up`, so `--detach --wait` starts it in the background; use long-form flags on Windows, because `-d` binds to PowerShell's own `-Debug`. These commands work unchanged in PowerShell, Git Bash, and WSL.

## Coding Style & Naming Conventions

- Python: four-space indentation, double quotes, Ruff formatting with `line-length = 100`.
- API: `docs/api/openapi.yaml` is the **source of truth for request and response shape**, and `docs/api/API-索引.md` is its index. Generate from it rather than inventing fields. It is tracked in git, so pull before generating: a stale copy silently produces the wrong fields.
- API envelope: every JSON response is `{code, message, data}`, with `code: 0` for success. Lists are paginated as `data: {items, total, page, size}`; errors carry a non-zero `code` and a human-readable `message`, not a nested `error` object.
- API paths live under `/api`, **except** the health check: `GET /health` is a required alias of `GET /api/health` with a byte-identical body (the sign-off scenario calls the bare path).
- `backend/app/main.py` follows the envelope on every route, including the ones that predate the contract; keep new endpoints on the same pattern.
- Vue and JavaScript: two-space indentation, single quotes, no semicolons.
- Preserve task identifiers such as T01 and M01 and module identifiers such as M1 and M8 from `project_plan.md`.
- Keep `scripts/dev.sh` and `scripts/dev.ps1` in sync, and keep `dev.ps1` ASCII-only: Windows PowerShell 5.1 decodes a script without a byte-order mark as ANSI.

## Testing Guidelines

- Tests live in `backend/tests/` and are named `test_*.py`; run them with `uv run pytest -q` from `backend/`.
- The suite migrates isolated SQLite databases and uses a Redis test double, so it does not exercise MySQL or a real Redis. The CI jobs cover those separately.
- Add or extend a test with every behavior change, including validation failures, not-found paths, and list filters.
- Future acceptance checks should cover the three demonstration flows in `project_plan.md`, including role and department access, allergy blocking, archive locking, and consultations.

## Commit & Pull Request Guidelines

Follow the existing `type: imperative summary` pattern, for example `feat: add allergy endpoints`. Keep changes focused.

PRs should explain the change, reference task IDs from `project_plan.md`, and list the validation performed (`uv run pytest -q`, Ruff, `npm run build`). For scope or schedule changes, state the capacity impact and record unresolved decisions explicitly. Work on a feature branch and open a pull request so CI runs before merge, matching the existing history.
