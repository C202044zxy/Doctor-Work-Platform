"""Activate an email-verified signup after checking staff identity and department."""

import argparse

from sqlalchemy import select

from app.config import Settings
from app.database import make_engine, session_factory
from app.models import Department, User


def activate(db, username, department):
    user = db.scalar(select(User).where(User.username == username))
    dept = db.scalar(select(Department).where(Department.name == department))
    if user is None or user.status != "pending":
        raise ValueError("Pending user not found")
    if dept is None:
        raise ValueError("Department not found")
    user.department = dept
    user.status = "active"
    db.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument("--department", required=True)
    args = parser.parse_args()
    engine = make_engine(Settings().database_url)
    try:
        with session_factory(engine)() as db:
            try:
                activate(db, args.username, args.department)
            except ValueError as exc:
                parser.error(str(exc))
        print("Account activated with junior access")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
