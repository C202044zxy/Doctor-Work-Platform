# B W2/W3 same-server deployment

Use `compose.sqlite.yaml` independently of `compose.yaml` (the latter remains D's MySQL development stack). One API worker is required: WebSocket live queues are in process, SQLite serializes writes, and one APScheduler instance evaluates reminders. Redis is private to the Compose network and stores authentication and per-connection presence leases. SQLite and chat images share the persistent `clinical_data` volume; Redis has its own AOF volume. No SQL server or SQLite network port exists.

1. Copy `.env.server.example` to `.env.server`. Set independent random `JWT_SECRET` and `PATIENT_DATA_KEY` values and real SMTP settings. Preserve these secrets across redeployments. Use the existing `backend` account creation/activation commands for staff accounts.
2. Run `docker compose --env-file .env.server -f compose.sqlite.yaml up --build -d --wait` from the repository root.
3. Put your HTTPS reverse proxy in front of `127.0.0.1:8080`. Forward WebSocket upgrades. The frontend Nginx forwards `/api`, `/ws` and protected `/uploads` to the API. Only the frontend is published; neither Redis nor the API opens a host port. `HTTP_BIND=0.0.0.0` is an explicit option for a controlled direct HTTP demonstration.
4. View logs with `docker compose --env-file .env.server -f compose.sqlite.yaml logs --tail=100 backend`. Access logs are disabled in the production API and WS proxy; the API log level is warning to suppress Uvicorn WebSocket handshake INFO lines because the browser handshake carries a JWT query parameter. Configure the outer reverse proxy likewise for `/ws/`.

This prepares deployment; it does not copy any existing MySQL data into SQLite. A fresh volume starts with an empty business database plus existing seed data. Data migration, TLS certificates, cloud firewall and a real SMTP delivery test need the server's actual inputs.

## Persistence, backup and images

`docker compose ... down` preserves volumes. Do not use `down -v` for a routine restart. Back up `/data` and the application secrets; restore to a separate volume and verify before replacing the live database. For a consistent simple backup, stop the backend first, then archive the entire `/data` volume (database, WAL/SHM if present, and images) using your server's backup tooling. Restart after the copy. SQLite's online backup API is an alternative for database-only snapshots, but it does not include images.

Images are decoded and re-encoded as JPEG/PNG/WebP, limited to 5 MiB incoming bytes and 25 megapixels, and assigned random filenames. The original filename and metadata are discarded. StaticFiles serves them only after authentication and consultation participation checks. The UI fetches them with the access token and opens the full image as a browser blob URL. A bare attachment URL requires authentication and is intentionally not public. Upload failure never creates a chat message. Refreshing fetches the durable URL again.

Retention policy: keep images referenced by `consult_message` for as long as the consultation record is retained. Do not use a blanket age-based deletion of `uploads/`. Unattached uploads older than seven days may be removed during a maintenance window after verifying both `image_upload.consultation_id IS NULL` and no `consult_message.image_url` references the filename. Back up first; delete the metadata and file together. No automatic clinical record deletion is enabled.

## Reminder timing

Five-field APScheduler cron uses `Asia/Shanghai`; weekday 0 is Monday. The one job `health_reminders` checks the current minute at second 0. It intentionally does not backfill missed minutes after downtime. A unique `(rule_id, due_at)` key prevents duplicate generation across restarts. Rules created during a minute start at their next due minute. Disabled rules keep historical logs. Linked rules fire only within the active plan's date range. Each reminder belongs to the doctor who created the rule; another doctor cannot clear that person's unread state. Opening a paginated list marks only the returned page as read; `unread_only=true` is a non-consuming preview.

## Local development

Use the existing local startup scripts, enable Redis via `REDIS_URL`, run `uv sync --frozen` and `uv run alembic upgrade head` in `backend`, then start the frontend. Vite now forwards `/ws` and `/uploads` as well as `/api`. Routes: `/consultations`, `/health-plans`, `/reminders`. Patients are selected by the existing patient number. One staff member opens a consultation on behalf of a patient; a second visible-scope staff member accepts it. These two users are its participants.
