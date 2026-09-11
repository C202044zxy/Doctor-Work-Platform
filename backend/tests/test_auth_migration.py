from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from app.database import make_engine, session_factory
from app.models import User


def test_existing_user_identity_and_role_are_preserved(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "c1d4e7a90b52")
    engine = make_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO departments (id, name) VALUES (1, 'Legacy')"))
        db.execute(text("INSERT INTO roles (id, name) VALUES (1, 'administrator')"))
        db.execute(
            text(
                "INSERT INTO users (id, email, password_hash, role_id, department_id) VALUES (1, 'legacy@example.test', 'unchanged-hash', 1, 1)"
            )
        )
    command.upgrade(cfg, "head")
    with session_factory(engine)() as db:
        user = db.scalar(select(User))
        assert user.username == "user_1"
        assert user.email == "legacy@example.test"
        assert user.password_hash == "unchanged-hash"
        assert user.role.name == "admin"
        assert user.department.name == "Legacy"
        assert user.status == "active"
        assert user.created_at is not None
    command.check(cfg)
    engine.dispose()
