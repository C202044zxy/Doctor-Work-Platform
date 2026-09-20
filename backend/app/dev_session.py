"""Issue a local demo session from the CLI; never exposes an HTTP login bypass."""

import argparse

from sqlalchemy import select

from app.auth import issue_token
from app.config import Settings
from app.database import make_engine, session_factory
from app.models import User
from app.seed_demo import USERS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True, choices=[row[0] for row in USERS])
    args = parser.parse_args()
    settings = Settings()
    if not settings.database_url.startswith("sqlite:///"):
        parser.error("This helper is restricted to local SQLite demo databases.")
    if len(settings.jwt_secret) < 32:
        parser.error("Configure a private local JWT_SECRET first.")
    engine = make_engine(settings.database_url)
    try:
        with session_factory(engine)() as db:
            user = db.scalar(
                select(User).where(User.username == args.username, User.status == "active")
            )
            if user is None:
                parser.error("Demo account not found. Run app.seed and app.seed_demo first.")
            print(issue_token(user, settings.jwt_secret))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
