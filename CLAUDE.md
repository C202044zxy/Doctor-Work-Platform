# CLAUDE.md

Read **`AGENTS.md`** first — it is the authoritative guide to this repository
(structure, stack, commands, conventions, and the honesty rules). Everything below
is the short version, plus what an AI in particular tends to get wrong here.

## Documentation map

Four documents, in this order of authority:

| Question | Document |
|---|---|
| Scope, modules, task IDs, ownership, status, schedule, tech and deploy choices | `docs/01-任务安排.md` |
| Test scenarios, demo baseline data, simulation red lines, defence talking points | `docs/02-测试场景.md` |
| What is actually built right now | `docs/03-实现现状.md` (plus the code) |
| Request/response shape | `docs/api/openapi.yaml`, indexed by `docs/api/API-索引.md` |

Every pre-overhaul document was **deleted on 2026-09-14**, including the `docs/archive/`
directory itself. There is no archive and no second source of truth. If you meet a
citation to a document that does not exist (`project_plan.md`, the task-chain or
requirements papers), treat it as a stale citation to fix, not a file to go looking for.
For old task IDs use the mapping table in `docs/01` §7.1; for history, use `git log`.

The obsolete root planning duplicate was removed during M3 integration. Use docs/01.

## The four things most likely to mislead you

1. **The API contract describes the target, not completion.** This branch now has M3 chat, records, signaling and main audit APIs. See `docs/03-实现现状.md` for the current snapshot and `docs/M3-架构与工作记录.md` for pending physical-media/M5 checks.

2. **Face login is a simulation, and it is on the anonymous allowlist.**
   `backend/app/face_login.py`'s `match_face()` returns `True` unconditionally, so any
   valid JPEG plus the username of an existing active account yields a real two-hour
   token. Never describe it as working face recognition, and never expose it outside a
   local demo.
3. **The database is SQLite, not MySQL.** Redis is a hard dependency of
   authentication. `backend/start.sh` and `backend/start.ps1` are the real one-command
   deploy scripts; `scripts/dev.*` are thin forwarders.
4. **Legacy identifiers are retired.** `T01`–`T37`, `M01`–`M07`, and single-letter
   member codes appear **only** in `docs/01-任务安排.md` §7. Do not use them in
   branches, PR descriptions, commits, or new documents. The current numbering is
   `M0`–`M9`, `S1`–`S6`, `D01`–`D07`.

## Hard rules

- Status columns record what the code does. No code means not started. Do not mark
  something complete because a document says it is.
- `backend/app/auth_schemas.py` is **generated** from `openapi.yaml` by
  `scripts/generate_auth_schemas.py`. Never hand-edit it.
- The health payload's database key is `db` (values `ok` / `down` / `disabled`).
  `GET /health` and `GET /api/health` are byte-identical aliases and always return 200.
  `GET /api/health/ready` returns **503** when a dependency is down — the two are not
  equivalent, so do not generalise one rule to the other.
- Roles are `admin` / `senior` / `junior`; the JWT claim is `title`. Departments are,
  in this fixed order, `Information Technology`, `Cardiology`, `Neurology` — tests
  index into that order.
- Authorization failures: **403** when the role lacks the permission, **404** when the
  object is outside the caller's department scope.
- All user-facing frontend text is English. Do not add Chinese UI strings.
- `audit_logs` is append-only, enforced by database triggers from migration
  `c0311060809b`. Do not add update or delete paths.
- **The database is rebuilt, never committed.** `backend/doctor.db` is a build artifact and
  `.gitignore` excludes `*.db`: a binary database cannot be reviewed, and two people editing
  their own copy of one always conflict on merge. Build it with
  `uv run --project backend python scripts/build_db.py` from the repository root, and never
  treat editing a database in a GUI as a schema change.
- **A table change is not finished until `scripts/build_db.py` agrees with it.** Changing a
  model means all four, in one commit: the model, a revision in `backend/migrations/`, the
  `EXPECTED_TABLES` / `EXPECTED_TRIGGERS` constants in that script, and a successful run of
  it. The script's build fails loudly until they agree -- it also runs `alembic check` -- and
  it restores the previous database rather than leaving a half-built one behind.
- Never commit `.env`, `JWT_SECRET`, `PATIENT_DATA_KEY`, SMTP credentials, the SQLite
  database file, or the Redis binaries unpacked under `backend/runtime/`.

## Commands

```bash
# backend (from backend/)
uv sync --frozen
uv run pytest -q
uv run ruff check app tests migrations && uv run ruff format --check app tests migrations
uv run alembic upgrade head
uv run python -m app.seed && uv run python -m app.seed_demo

# frontend (from frontend/)
npm ci && npm run build

# whole stack (from the repository root)
./scripts/dev.sh          # or .\scripts\dev.ps1 on Windows; add `docker` for Compose

# rebuild the local SQLite database from scratch (snapshot -> migrate -> seed -> verify)
uv run --project backend python scripts/build_db.py
```
