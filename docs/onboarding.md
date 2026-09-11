# Onboarding: run the project on a fresh machine

This guide is for a teammate who has never configured this project. Follow it top to
bottom. Nothing outside it is needed, and no verbal hand-holding should be required. If
you do need help, that is a bug in this document, so please report it.

Budget about 15 minutes of downloading, then a few minutes per run.

## 1. Get the code

Use git, not a zip download: a zip adds a mark of the web that can make Windows refuse to
run PowerShell scripts.

```bash
git clone https://github.com/C202044zxy/Doctor-Work-Platform.git
cd Doctor-Work-Platform
```

You need access to the repository. Ask the team lead if the clone is rejected.

If `scripts/dev.ps1` is missing after cloning, the one-command startup is not on your
branch yet: ask which branch to check out.

## 2. Install the two prerequisites

Versions are listed in the [README](../README.md#prerequisites). Short version:

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
```

**Close and reopen the terminal** so the new `PATH` takes effect, then confirm:

```powershell
uv --version
node --version
```

`node --version` must report v22.12 or newer. Do not install Python, MySQL, or Redis.

## 3. First run: local mode

```powershell
.\scripts\dev.ps1
```

On macOS, Linux, or WSL: `./scripts/dev.sh`

The first run downloads a Python interpreter and every dependency, so give it several
minutes. When it finishes it prints:

```text
Frontend: http://127.0.0.1:5173 | API docs: http://127.0.0.1:8000/docs
```

Two extra windows open, one per server, so you can read the logs. Stop with Ctrl+C.

Check that it works:

- http://127.0.0.1:8000/docs shows the API documentation.
- http://127.0.0.1:5173 shows the patient workspace and its Department dropdown lists
  General Medicine and Cardiology. This one check proves the frontend, the API proxy,
  FastAPI, the database migration, and the seed data all work.
- http://127.0.0.1:8000/api/health/ready reports
  `{"status":"ok","checks":{"database":"ok","redis":"disabled"}}`. Redis is disabled in
  local mode, which is expected.

> **Two different health checks, don't confuse them.** The one above is the legacy
> readiness probe; it reports its own `{"status", "checks"}` shape and returns a non-200
> when a dependency is down, because CI's `smoke.py` depends on it.
>
> The check the API contract defines is **`GET /health`** (with `GET /api/health` as the
> same body under the `/api` prefix): it returns the standard envelope
> `{code: 0, data: {db, redis}}`, **always with status 200** — a dependency being down
> only flips `db`/`redis` to `"down"`, it never produces a 5xx. See
> [`API-索引.md`](api/API-索引.md) §2.1. `live`/`ready` are not part of the contract and
> are not what the sign-off scenario calls.

## 4. Full stack: docker mode

Needed for MySQL and Redis, which is how the project is verified and demonstrated.
Install Docker Desktop with Compose v2 first.

```powershell
.\scripts\dev.ps1 docker
```

Now `http://127.0.0.1:8000/api/health/ready` should also report `"redis": "ok"`.
Stop with Ctrl+C or `docker compose down`.

To start it in the background instead of holding the terminal:

```powershell
.\scripts\dev.ps1 docker --detach --wait
```

Stop a backgrounded stack with `docker compose down`. Use long-form flags on Windows:
`-d` binds to PowerShell's own `-Debug` switch, not to Docker.

In docker mode the frontend is a static production build behind Nginx, so there is no hot
reload. Use local mode for day-to-day frontend work.

## 5. What to report back

Please send these three things, even if everything worked:

1. Which mode you ran: local, docker, or both.
2. How long the first run took, from typing the command to `/docs` opening.
3. Anything that was unclear, missing, or wrong in this document.

If something failed, send the full output, and say which step and which window produced it.

The same two commands run in CI on a clean machine on every push, so a green `checks` and
`windows-one-command` run in the Actions tab is what the team checks before merging.
