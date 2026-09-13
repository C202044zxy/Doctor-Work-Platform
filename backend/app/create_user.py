"""Provision an account locally; T08 owns the HTTP user-administration API."""

import argparse
import getpass

from sqlalchemy import select

from app.auth import hash_password
from app.config import Settings
from app.database import make_engine, session_factory
from app.models import Department, Role, User


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--title", choices=("admin", "senior", "junior"), required=True)
    parser.add_argument("--department", required=True)
    args = parser.parse_args()
    if not 1 <= len(args.username) <= 100 or not 1 <= len(args.name) <= 100:
        parser.error("Username and name must contain 1–100 characters")
    if "@" not in args.email or len(args.email) > 254:
        parser.error("A valid email address is required")
    password = getpass.getpass("Password (never stored in plaintext): ")
    if password != getpass.getpass("Repeat password: "):
        parser.error("Passwords do not match")
    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        parser.error(str(exc))
    engine = make_engine(Settings().database_url)
    try:
        with session_factory(engine)() as db:
            department = db.scalar(select(Department).where(Department.name == args.department))
            role = db.scalar(select(Role).where(Role.name == args.title))
            if department is None or role is None:
                parser.error("Department or role not found; seed master data first")
            if db.scalar(
                select(User.id).where((User.username == args.username) | (User.email == args.email))
            ):
                parser.error("Username or email already exists")
            db.add(
                User(
                    username=args.username,
                    name=args.name,
                    email=args.email,
                    password_hash=password_hash,
                    role_id=role.id,
                    department_id=department.id,
                )
            )
            db.commit()
        print("User created")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
