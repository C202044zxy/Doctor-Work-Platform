# Sprint 1 — owner A implementation and hand-off

Scope remains T01, T02, T05, T10 (18 estimated task-hours). No baseline schedule or
capacity changes. Implementation evidence is separate from E's customer sign-off.

| Task | Delivered |
| --- | --- |
| T01 | Existing FastAPI/Vue scaffold retained; feature-branch workflow; updated verification and setup documentation. |
| T02 | Existing user/role/department/patient/allergy/log schema retained; additive Alembic revision `d2a5f8b13c64` adds contract user identity/status fields and `temp_grant`. Migrated and seeded the requested MySQL `doctor` database. |
| T05 | bcrypt password provisioning; five-minute tickets; Redis password throttling; single-use code consumption; two-hour JWTs; current-user validation; Redis logout blacklist and disabled-user rejection. |
| T10 | Admin/senior grant creation, filtered pagination and manual revocation; patient visibility hook; expiry enforced on every access; APScheduler scans every minute with transactional audit events. |

## API and integration boundaries

`docs/api/openapi.yaml` remains authoritative. Request/response base models in
`backend/app/auth_schemas.py` are generated from the tracked contract with
`uv run scripts/generate_auth_schemas.py`; run backend Ruff formatting afterward.
Endpoint subclasses add semantic constraints (UTF-8 bcrypt limit, future timezone-aware
expiry and nonblank reason). Pull the contract before regenerating.

- **B / T06:** implement `/api/auth/send-code` and SMTP delivery, resend cooldown and
  daily limits. Resolve the password-verified ticket via `auth.ticket_key(ticket)`.
  After successful delivery, call
  `store_verification_code(cache, settings.jwt_secret, ticket, six_digit_code)`.
  This stores a ticket-bound HMAC under `auth:code:<user_id>` for 300 seconds. Neither
  responses nor logs reveal the code. No production bypass or debug-code route exists.
  The verification endpoint consumes ticket and code atomically through Redis WATCH,
  and invalidates the challenge after five wrong submissions.
- **B / T08–T09:** reuse `auth.current_user` and `grants.patient_scope(user)`.
  Identity/role/department are reloaded from the database, not trusted solely from JWT
  claims. Existing patient and allergy endpoints now require authentication and enforce
  patient scope, including list filters and allergy-by-id operations. The full T08
  permission matrix and user administration remain B's tasks.
- **C / T07:** the existing UI uses a mock session. Wire login → send-code → verify-code,
  attach `Authorization: Bearer <access_token>`, restore `/api/me`, and clear the token on
  logout/401. Login itself returns only `{ticket, expires_in}`; never an access token.
- **B / T11 and C / T12:** grant events are stored transactionally in `audit_logs` with
  actions `temp_grant.create`, `temp_grant.expire`, and `temp_grant.revoke`. Detail includes
  grant, grantee and acting user ids. Audit search/export remains separate work.

Seniors may manage grants only for patients in their own department. A received grant
cannot be delegated onwards to another user. Admins are exempt. Expired grants are
reported inactive and stop permitting access even before the scheduler updates the flag.

Each application lifespan registers one 60-second APScheduler job. Multiple workers
may scan simultaneously: a conditional SQL UPDATE claims a still-valid expired row;
only the winning transaction writes its expiry audit record. Scheduler shutdown waits
for active jobs. This works without Redis locks and does not depend on a single worker.
Dates are normalized to UTC before MySQL DATETIME storage and on serialization.

## Setup and verification

The remote connection is stored only in ignored `backend/.env` (mode 0600). No database
password is in the code, examples or this document. Set a persistent Redis service URL;
a temporary loopback Redis instance was used for integration verification in this session.
No application accounts/passwords are seeded; use the prompted `app.create_user` CLI.

From `backend/`:

```bash
uv sync --frozen
uv run alembic upgrade head
uv run python -m app.seed
uv run alembic check
uv run pytest -q
uv run ruff check app tests migrations
uv run ruff format --check app tests migrations
uv run python ../scripts/verify_sprint1.py
```

The last command uses configured MySQL and real Redis, creates synthetic users/patient,
exercises the login/code hand-off, cross-department grant access, actual minute scheduler,
expiry audit and logout, and removes its SQL fixtures afterward. It does not send email.
It requires two seeded departments and may take about 90 seconds with a remote database.

Frontend verification: `npm ci && npm run build` from `frontend/`.
Compose CI captures a token from `app.smoke_identity` inside its disposable database,
then runs the full authenticated patient smoke check. Without Redis/token, the Windows
startup smoke only verifies readiness, frontend delivery and anonymous access refusal.

Outstanding customer acceptance dependencies: SMTP (T06), real frontend login (T07),
remaining role/admin/audit work (T08/T11/T12), and E's final acceptance review.

## Recorded verification

- 37 pytest tests passed, including legacy migration preservation, concurrent code
  consumption, authorization boundaries and expired-grant behavior.
- Backend Ruff lint and format checks passed.
- Remote MySQL migrations, repeated seed and `alembic check` passed.
- Real MySQL/Redis integration passed with the actual 60-second scheduler; its
  synthetic SQL records were removed afterward. SMTP was not tested.
- Frontend production build passed (existing large-chunk warnings). The first npm
  attempt failed on mirror fetches; retrying with the repository's proxy settings passed.
- Docker Compose and Windows execution are left to CI; Docker is unavailable locally.
