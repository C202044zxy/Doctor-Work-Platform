"""Container readiness check; never print secrets or change business data."""

import json
import sqlite3
import sys
from pathlib import Path

from redis import Redis
from sqlalchemy import inspect, text

from app.config import Settings
from app.database import make_engine


def main():
    settings = Settings()
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is required for the complete stack")
    if len(settings.jwt_secret) < 32 or len(settings.patient_data_key) < 32:
        raise RuntimeError(
            "Set independent JWT_SECRET and PATIENT_DATA_KEY secrets (32+ characters)"
        )
    engine = make_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        missing = {
            "users",
            "consultation",
            "consult_message",
            "health_plan",
            "reminder_rule",
        } - set(inspect(engine).get_table_names())
        if missing:
            raise RuntimeError(f"Missing migrated tables: {sorted(missing)}")
        with Redis.from_url(
            settings.redis_url, socket_connect_timeout=3, socket_timeout=3
        ) as cache:
            cache.ping()
        root = Path(settings.upload_dir)
        root.mkdir(parents=True, exist_ok=True)
        # An exclusive temporary file verifies the mounted directory is writable.
        import tempfile

        with tempfile.TemporaryFile(dir=root) as probe:
            probe.write(b"ok")
        print(
            json.dumps(
                {
                    "python": sys.version.split()[0],
                    "database": engine.dialect.name,
                    "sqlite_library": sqlite3.sqlite_version,
                    "migration": revision,
                    "redis": "ok",
                    "uploads": "writable",
                    "smtp": "configured, delivery not tested"
                    if settings.smtp_host
                    else "not configured; email login unavailable",
                }
            )
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
