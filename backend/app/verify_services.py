"""Run against a disposable SQLite/Redis stack; no real SMTP is required."""

import secrets

from redis import Redis
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.auth import code_key, store_verification_code, ticket_key
from app.config import Settings
from app.database import make_engine, session_factory
from app.models import AuditLog
from app.otp import reserve_send


def main():
    settings = Settings()
    # The audit append-only check below relies on the triggers the migration
    # installs for both SQLite and MySQL, so either engine works here.
    if not settings.redis_url:
        raise RuntimeError("Requires a real Redis: set REDIS_URL")
    cache = Redis.from_url(settings.redis_url, socket_timeout=3)
    engine = make_engine(settings.database_url)
    uid = secrets.randbelow(1_000_000_000) + 1_000_000_000
    ticket = secrets.token_urlsafe(32)
    try:
        cache.set(ticket_key(ticket), uid, ex=300)
        reserve_send(cache, uid)
        store_verification_code(cache, settings.jwt_secret, ticket, "123456")
        assert 295 <= cache.ttl(code_key(uid)) <= 300
        assert cache.get(code_key(uid)) != b"123456"
        with session_factory(engine)() as db:
            row = AuditLog(action="integration.verify", object_type="system", result="success")
            db.add(row)
            db.commit()
            audit_id = row.id
        for statement in [
            "UPDATE audit_logs SET action='tampered' WHERE id=:id",
            "DELETE FROM audit_logs WHERE id=:id",
        ]:
            try:
                with engine.begin() as connection:
                    connection.execute(text(statement), {"id": audit_id})
            except DBAPIError as exc:
                assert "append-only" in str(exc) or "denied" in str(exc)
            else:
                raise AssertionError("Audit mutation was accepted")
        print(
            "Real SQLite/Redis checks passed: audit mutation rejected, send reservation and OTP TTL verified"
        )
    finally:
        keys = [ticket_key(ticket), code_key(uid), f"auth:send:cooldown:{uid}"]
        keys.extend(cache.scan_iter(match=f"auth:send:daily:{uid}:*"))
        cache.delete(*keys)
        cache.close()
        engine.dispose()


if __name__ == "__main__":
    main()
