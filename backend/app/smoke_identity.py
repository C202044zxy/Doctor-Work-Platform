"""Explicit CI-only account provisioning; run inside the disposable Compose stack.

This command needs database access and prints a bearer credential to stdout.
Callers must capture it without logging it. It is never exposed as an API route.
"""

import secrets

from sqlalchemy import select

from app.auth import hash_password, issue_token
from app.config import Settings
from app.database import make_engine, session_factory
from app.models import Department, Role, User


def main():
    settings = Settings()
    engine = make_engine(settings.database_url)
    try:
        with session_factory(engine)() as db:
            role = db.scalar(select(Role).where(Role.name == "admin"))
            department = db.scalar(select(Department).order_by(Department.id))
            user = db.scalar(select(User).where(User.username == "ci_smoke"))
            if user is None:
                user = User(
                    username="ci_smoke",
                    name="CI Smoke",
                    email="ci_smoke@example.test",
                    password_hash=hash_password(secrets.token_urlsafe(32)),
                    role_id=role.id,
                    department_id=department.id,
                )
                db.add(user)
                db.commit()
            print(issue_token(user, settings.jwt_secret))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
