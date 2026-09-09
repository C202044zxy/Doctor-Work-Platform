# Doctor Work Platform

A runnable foundation for the school project's doctor workspace: FastAPI, Vue 3,
SQLAlchemy/Alembic, and a Docker Compose stack with MySQL 8.4 and Redis 7.
Scope and future clinical workflows are tracked in [project_plan.md](project_plan.md).

## Quick start

With Python 3.12+, [uv](https://docs.astral.sh/uv/getting-started/installation/),
and Node.js 22.12+ installed, run from the repository root:

```bash
./scripts/dev.sh
```

The script installs locked dependencies, applies migrations, seeds departments and
roles, and starts both servers. Open http://127.0.0.1:5173; API documentation is at
http://127.0.0.1:8000/docs. Ctrl+C stops both servers. Run the command again to restart;
records persist in `backend/doctor.db`. Local mode uses SQLite and disables Redis
unless `REDIS_URL` is configured in `backend/.env`.

For the planned MySQL/Redis stack, install Docker with Compose v2 and run:

```bash
./scripts/dev.sh docker
```

Compose applies the same migrations and seeds automatically. MySQL and Redis use
persistent named volumes and are accessible only inside the Compose network.
The frontend and API use the same local URLs. Stop with Ctrl+C or `docker compose down`;
normal shutdown preserves the database volumes.

## Basic functionality

- Create synthetic patients, search names, paginate, view notes, and delete records.
- Store patients and transactional create/delete audit entries in the database.
- Seed two departments and three provisional roles without duplicate records.
- Check liveness at `/api/health/live` and database/Redis readiness at `/api/health/ready`.
  Readiness returns HTTP 503 if a configured dependency is unavailable.
- Inspect and exercise the documented API through FastAPI Swagger.

This is an unauthenticated local development demo. Use synthetic data only.
User and allergy tables are foundations; login, RBAC, 2FA, allergy validation,
EMR workflows, consultation features, and a full audit trail are not implemented.
The provisional role names require confirmation against task T08.

## Layout

```text
backend/app/          Configuration, database models, API, schemas, seed command
backend/migrations/   Versioned Alembic schema migrations
backend/tests/        API, persistence, validation, and dependency health tests
frontend/src/         Vue patient workspace and styles
scripts/dev.sh        Local and Docker startup
compose.yaml          MySQL, Redis, API, and frontend services
```

## Configuration

Copy `backend/.env.example` to `backend/.env` for local overrides. Compose uses the
root `.env.example` as a reference: copy it to `.env` to override demo credentials.
Neither file is committed. Percent-encode special characters in credentials when
constructing a `DATABASE_URL`. Restart services after configuration changes.
Do not expose this demo to a shared network before implementing authentication.

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
server behavior. The CI Compose job separately exercises real MySQL and Redis.

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

Framework references: [FastAPI lifecycle](https://fastapi.tiangolo.com/advanced/events/)
and [Vite setup](https://vite.dev/guide/).
