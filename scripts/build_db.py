#!/usr/bin/env python3
"""Build the local SQLite database: schema from migrations, then seed data.

Run it from the repository root:

    uv run --project backend python scripts/build_db.py
    uv run --project backend python scripts/build_db.py --db backend/scratch.db
    uv run --project backend python scripts/build_db.py --no-demo

The target is whatever `DATABASE_URL` resolves to -- `backend/.env` if it sets
one, otherwise `backend/doctor.db`. The script refuses to touch anything that is
not a SQLite file. An existing database is snapshotted into `backups/` first,
then rebuilt from scratch; if any step fails, the previous file is put back.

The three seed layers, and why the third is here
------------------------------------------------
`app.seed` writes master data, `app.seed_demo` writes the demonstration accounts
and patients, and `app.seed_flow` writes the clinical state the three flows in
`docs/02-测试场景.md` §3 start from -- consultation rooms in all three states,
records in all three review states, a completed meeting, a health plan with
fired reminders. All three run here, because a database built by this script is
the one the demonstrations and the screenshots are taken against: leaving the
third out would produce a database that opens on empty workbenches.

`--no-flow` (and `--no-demo`, which implies it) skips that layer for a build
that only needs the schema and master data.

Why a build script instead of a committed database
--------------------------------------------------
`backend/doctor.db` is an artifact, not a source file, and `.gitignore` keeps it
out of git on purpose: a binary database cannot be reviewed, and two people who
each edit their own copy of one always conflict on merge. Every developer
therefore rebuilds it locally with this script, so the database each of us ends
up with is a function of `backend/migrations/` and the two seeders -- text
files, which merge normally.

Keeping this script in sync with the schema
-------------------------------------------
`EXPECTED_TABLES` below is a contract, not a summary. A freshly built database
must contain exactly those tables and nothing else, plus the append-only
triggers on `audit_logs`. Add, rename or drop a model and this script fails the
build until that list is updated, so a table change cannot land without its
build recipe. Update it in the same commit as the migration.

This is a developer tool. `backend/start.sh`, `backend/start.ps1` and the
Compose image keep running alembic and the seeders directly, because
`docs/01-任务安排.md` §8.2 requires the backend to start without help from a
repo-root script.
"""

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
# The app package is imported, never installed, so make it reachable up front:
# every helper below assumes `app.config` and friends resolve.
sys.path.insert(0, str(BACKEND))

# The schema a fresh build must produce. `alembic_version` is Alembic's own
# bookkeeping table. Changing a model means changing this set in the same
# commit as its revision.
# Named test recordings reuse call_recording (is_test / filename); no extra table.
EXPECTED_TABLES = frozenset(
    {
        "alembic_version",
        "emr_template",
        "emr_record",
        "emr_version",
        "medical_order",
        "drug",
        "allergies",
        "audit_logs",
        "departments",
        "health_assessments",
        "health_plans",
        "meeting_materials",
        "meeting_participants",
        "meeting_reports",
        "meetings",
        "passkeys",
        "patient_group_members",
        "patient_groups",
        "patient_history",
        "patient_symptom_tags",
        "patients",
        "reminder_logs",
        "reminder_rules",
        "roles",
        "temp_grant",
        "users",
        "consultation",
        "consult_message",
        "image_upload",
        "call_log",
        "call_recording",
        "notify_outbox",
        "legacy_medical_order",
        "health_plan",
        "reminder_rule",
        "reminder_log",
        "vital_signs",
        "vital_thresholds",
    }
)

# The append-only guarantee on audit_logs (migration c0311060809b) lives in the
# database, not in the application, so a build that lost the triggers is not a
# valid build. See CLAUDE.md.
EXPECTED_TRIGGERS = frozenset({"audit_logs_no_update", "audit_logs_no_delete"})

# Fixed order, ids 1/2/3: tests and the demo seeders index into it, so a build
# that reordered these would be broken even though the row count looks right.
EXPECTED_DEPARTMENTS = ("Information Technology", "Cardiology", "Neurology")
EXPECTED_ROLES = frozenset({"admin", "senior", "junior"})


class BuildError(RuntimeError):
    """A build step produced a database that does not match this script."""


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--db",
        metavar="PATH",
        help="build this file instead of the one DATABASE_URL names",
    )
    parser.add_argument(
        "--no-demo",
        action="store_true",
        help="seed master data only; skip the demo accounts, patients and flow data",
    )
    parser.add_argument(
        "--no-flow",
        action="store_true",
        help="keep the accounts and patients, but skip the clinical flow baseline",
    )
    return parser.parse_args()


def load_settings(db_override):
    """Read the app settings, with `--db` winning over `DATABASE_URL`."""
    if db_override is not None:
        # A POSIX absolute path needs four slashes and a Windows one three;
        # this f-string produces the right number for each.
        os.environ["DATABASE_URL"] = f"sqlite:///{db_override.as_posix()}"
    try:
        from app.config import Settings
    except ImportError as error:  # pragma: no cover - environment problem
        raise SystemExit(
            f"Cannot import the backend application: {error}\n"
            "Run this script through the backend environment:\n"
            "    uv run --project backend python scripts/build_db.py"
        ) from error
    # Settings reads backend/.env, so the caller must have chdir'd to BACKEND.
    return Settings()


def database_path(database_url):
    """Turn a SQLAlchemy URL into the file it names, or explain why it cannot."""
    from sqlalchemy.engine import make_url

    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise SystemExit(
            f"build_db.py builds SQLite databases, but DATABASE_URL is {url.drivername}.\n"
            "Unset DATABASE_URL, or point it at a file, to build the local database."
        )
    if url.database in (None, "", ":memory:"):
        raise SystemExit(f"DATABASE_URL names no file to build: {database_url}")
    path = Path(url.database)
    # A relative URL like sqlite:///./doctor.db is relative to backend/, which
    # is where alembic and the seeders run.
    return path if path.is_absolute() else (BACKEND / path).resolve()


def sidecars(db_path):
    """SQLite's write-ahead and shared-memory files, which go with the database."""
    return (db_path.with_name(f"{db_path.name}-wal"), db_path.with_name(f"{db_path.name}-shm"))


def snapshot(db_path):
    """Copy an existing database aside with SQLite's online backup API."""
    backup_dir = Path(os.environ.get("BACKUP_DIR", "backups"))
    if not backup_dir.is_absolute():
        backup_dir = ROOT / backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)
    # Local time with a timezone attached, matching the stamp scripts/backup.sh
    # writes; a naive now() is the one thing Ruff flags in this repository.
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"prebuild-{stamp}.db"

    source = sqlite3.connect(db_path)
    try:
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
    except (sqlite3.DatabaseError, OSError) as error:
        target.unlink(missing_ok=True)
        raise BuildError(
            f"{db_path} could not be read as a SQLite database ({error}).\n"
            "Either it is not a database file -- move it aside by hand -- or the stack is\n"
            "still running and holding it. Stop the servers, then run this script again."
        ) from error
    finally:
        source.close()

    prune(backup_dir)
    return target


def prune(backup_dir):
    """Keep the newest BACKUP_KEEP pre-build snapshots, like scripts/backup.sh."""
    keep = os.environ.get("BACKUP_KEEP", "7")
    if not keep.isdigit() or int(keep) <= 0:
        return
    archives = sorted(backup_dir.glob("prebuild-*.db"))
    for stale in archives[: -int(keep)]:
        stale.unlink(missing_ok=True)
        print(f"Removed old snapshot {stale}")


def run(*args):
    """Run a backend command with this interpreter, from backend/."""
    print(f"+ {Path(sys.executable).name} {' '.join(args)}", flush=True)
    subprocess.run([sys.executable, *args], cwd=BACKEND, check=True)


def verify(db_path, with_demo, with_flow, upload_dir):
    """Check that the build produced the database this script promises."""
    connection = sqlite3.connect(db_path)
    try:
        tables = {
            name
            for (name,) in connection.execute("select name from sqlite_master where type = 'table'")
            if not name.startswith("sqlite_")
        }
        triggers = {
            name
            for (name,) in connection.execute(
                "select name from sqlite_master where type = 'trigger'"
            )
        }
        revision = connection.execute("select version_num from alembic_version").fetchone()
        departments = [
            name for (name,) in connection.execute("select name from departments order by id")
        ]
        roles = {name for (name,) in connection.execute("select name from roles")}
        usernames = {name for (name,) in connection.execute("select username from users")}
        patients = connection.execute("select count(*) from patients").fetchone()[0]
    finally:
        connection.close()

    unexpected = tables - EXPECTED_TABLES
    missing = EXPECTED_TABLES - tables
    if unexpected or missing:
        raise BuildError(
            "The built schema does not match EXPECTED_TABLES in this script "
            f"(unexpected: {sorted(unexpected)}, missing: {sorted(missing)}).\n"
            "A table change must update scripts/build_db.py in the same commit as its migration."
        )

    absent = EXPECTED_TRIGGERS - triggers
    if absent:
        raise BuildError(
            f"audit_logs is missing its append-only trigger(s): {sorted(absent)}.\n"
            "The migration that installs them (c0311060809b) did not take effect."
        )

    if tuple(departments) != EXPECTED_DEPARTMENTS:
        raise BuildError(
            f"Departments came out as {departments}, expected {list(EXPECTED_DEPARTMENTS)} "
            "in that order. Tests index into it."
        )
    if roles != EXPECTED_ROLES:
        raise BuildError(f"Roles came out as {sorted(roles)}, expected {sorted(EXPECTED_ROLES)}.")

    if with_demo:
        from app.seed_demo import PATIENTS, USERS

        expected_users = {user[0] for user in USERS}
        if usernames != expected_users:
            raise BuildError(
                f"Demo accounts came out as {sorted(usernames)}, expected {sorted(expected_users)}."
            )
        if patients != len(PATIENTS):
            raise BuildError(
                f"The demo baseline produced {patients} patient(s), expected {len(PATIENTS)}."
            )
    elif usernames:
        raise BuildError("--no-demo was given, but the build created accounts anyway.")

    if with_flow:
        verify_flow(db_path, upload_dir)

    return revision[0] if revision else None


def verify_flow(db_path, upload_dir):
    """Check the full-flow baseline `app.seed_flow` writes.

    The expected counts live in that module rather than here, so the seeder and
    its contract cannot drift apart: adding a seeded row means changing one
    constant. The attachments are checked too -- a material row pointing at a
    file nobody wrote is a 404 the demonstration would find, not this script.
    """
    from app.seed_flow import EXPECTED_COUNTS, SEEDED_FILES

    connection = sqlite3.connect(db_path)
    try:
        wrong = []
        for model, expected in EXPECTED_COUNTS.items():
            # The table name comes from the model, not from input.
            count = connection.execute(f"select count(*) from {model.__tablename__}").fetchone()[0]
            if count != expected:
                wrong.append(f"{model.__tablename__} has {count} row(s), expected {expected}")
    finally:
        connection.close()

    if wrong:
        raise BuildError(
            "The full-flow seed (app.seed_flow) did not produce the rows it promises "
            f"({'; '.join(wrong)}).\n"
            "That seed and EXPECTED_COUNTS are the contract; fix them together."
        )

    absent = [name for name in SEEDED_FILES if not (upload_dir / name).is_file()]
    if absent:
        raise BuildError(
            f"The full-flow seed named {len(absent)} attachment(s) that are not on disk: "
            f"{absent}.\nThey belong under {upload_dir}; check that the seeder could write there."
        )


def recover(db_path, restore_from, error):
    """Put the previous database back and report why the build failed.

    Recovery can fail for the same reason the build did -- Windows refuses to
    replace a file a running server holds open -- so nothing here is allowed to
    raise. The snapshot is named in the message either way, which is what makes
    a failed recovery survivable.
    """
    print(f"\nBuild failed: {error}", file=sys.stderr)
    if restore_from is None:
        try:
            db_path.unlink(missing_ok=True)
        except OSError as cleanup_error:
            print(f"Could not remove the incomplete database: {cleanup_error}", file=sys.stderr)
            print(f"Delete {db_path} yourself before the next run.", file=sys.stderr)
        else:
            print("Removed the incomplete database.", file=sys.stderr)
        return 1

    try:
        shutil.copy2(restore_from, db_path)
    except OSError as restore_error:
        print(f"Could not restore {db_path}: {restore_error}", file=sys.stderr)
        print(f"Your previous database is untouched at {restore_from}.", file=sys.stderr)
    else:
        print(f"Restored the previous database from {restore_from}", file=sys.stderr)
    return 1


def main():
    args = parse_args()
    # Resolve a relative --db before changing directory: it belongs to the
    # directory the user typed it in, not to backend/.
    db_override = None if args.db is None else (Path.cwd() / args.db).resolve()
    os.chdir(BACKEND)

    settings = load_settings(db_override)
    db_path = database_path(settings.database_url)
    print(f"Building {db_path}")

    restore_from = None
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        if db_path.exists():
            restore_from = snapshot(db_path)
            print(f"Previous database snapshotted to {restore_from}")
            for stale in (db_path, *sidecars(db_path)):
                stale.unlink(missing_ok=True)

        run("-m", "alembic", "upgrade", "head")
        # Fails when a model and its migration have drifted apart, which is the
        # other half of "this script always produces the current schema".
        run("-m", "alembic", "check")
        run("-m", "app.seed")
        if not args.no_demo:
            run("-m", "app.seed_demo")
            # The clinical state the three flows start from. It builds on the
            # accounts and patients above, so it never runs without them.
            if not args.no_flow:
                run("-m", "app.seed_flow")
        revision = verify(
            db_path,
            with_demo=not args.no_demo,
            with_flow=not (args.no_demo or args.no_flow),
            upload_dir=Path(settings.upload_dir),
        )
    except (subprocess.CalledProcessError, BuildError, OSError) as error:
        return recover(db_path, restore_from, error)

    print(f"\nBuilt {db_path} ({db_path.stat().st_size / 1024:.0f} KiB)")
    print(f"  revision    {revision}")
    print(
        f"  tables      {len(EXPECTED_TABLES)}, plus {len(EXPECTED_TRIGGERS)} append-only triggers"
    )
    print("  master data 3 departments, 3 roles")
    if args.no_demo:
        print("  demo data   skipped (--no-demo)")
    else:
        print("  demo data   4 accounts, 3 patients")
        if args.no_flow:
            print("  flow data   skipped (--no-flow)")
        else:
            print("  flow data   3 consultations, 3 records, 1 meeting, 1 plan, 30 readings")
        print("Sign in as admin_zhang, dr_li, dr_wang or dr_chen with Demo@2026.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
