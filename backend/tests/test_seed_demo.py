"""`app.seed_demo` seeds the presentation baseline and verifies it afterwards.

The verification exists because the seeder is additive on purpose: a database
seeded by an older baseline keeps its old values, and the documented demos then
stop working without a word (a patient still in the retired `General Medicine`
department, an account the scope rules can no longer see). `--check` is the
read-only report CI runs; `--fix` is the explicit repair.
"""

import contextlib
from datetime import date

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, func, select

from app.database import make_engine, session_factory
from app.models import Allergy, Department, Patient, User
from app.seed import seed
from app.seed_demo import PATIENTS, USERS, baseline_drift, main


@pytest.fixture
def database(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'demo.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    seed()
    return url


@contextlib.contextmanager
def opened(url):
    engine = make_engine(url)
    try:
        with session_factory(engine)() as db:
            yield db
    finally:
        engine.dispose()


def department_id(db, name):
    return db.scalar(select(Department.id).where(Department.name == name))


def patient_row(db, patient_no):
    return db.scalar(select(Patient).where(Patient.patient_no == patient_no))


def test_the_baseline_is_seeded_once_and_verifies_clean(database):
    assert main([]) == 0
    assert main([]) == 0  # Repeating it must not duplicate anything.
    with opened(database) as db:
        assert db.scalar(select(func.count()).select_from(User)) == len(USERS)
        assert db.scalar(select(func.count()).select_from(Patient)) == len(PATIENTS)
        assert baseline_drift(db) == []
    assert main(["--check"]) == 0


def test_a_stale_patient_is_reported_and_never_overwritten(database):
    assert main([]) == 0
    with opened(database) as db:
        row = patient_row(db, "P20260001")
        row.name = "赵雷"
        row.department_id = department_id(db, "Neurology")
        db.commit()

    # Additive by contract: the record a demo edited stays edited, which is why
    # the module warns instead of repairing...
    assert main([]) == 0
    with opened(database) as db:
        row = patient_row(db, "P20260001")
        assert row.name == "赵雷"
        assert row.department.name == "Neurology"
        assert [line for line in baseline_drift(db) if "P20260001" in line]
    # ...and --check is the loud version of that warning.
    assert main(["--check"]) == 1


def test_a_missing_baseline_allergy_is_filled_and_reported(database):
    assert main([]) == 0
    with opened(database) as db:
        db.execute(delete(Allergy).where(Allergy.patient_id == patient_row(db, "P20260001").id))
        db.commit()
        assert any("PENICILLIN" in line for line in baseline_drift(db))
    assert main(["--check"]) == 1

    # Filling a missing record is what the additive path is for.
    assert main([]) == 0
    with opened(database) as db:
        assert baseline_drift(db) == []


def test_check_reports_missing_records_without_creating_them(database):
    with opened(database) as db:
        assert any("dr_chen" in line for line in baseline_drift(db))

    assert main(["--check"]) == 1
    with opened(database) as db:
        assert db.scalar(select(User.id).where(User.username == "dr_chen")) is None

    # The startup path is the one that fills in what is missing.
    assert main([]) == 0
    with opened(database) as db:
        assert baseline_drift(db) == []


def test_fix_restores_the_pinned_fields_and_keeps_the_rest(database):
    assert main([]) == 0
    with opened(database) as db:
        row = patient_row(db, "P20260001")
        row.name = "赵雷"
        row.department_id = department_id(db, "Neurology")
        db.add(
            Patient(
                patient_no="P20269999",
                name="Kept",
                gender="unknown",
                department_id=department_id(db, "Cardiology"),
                notes="not part of the baseline",
                admitted_at=date(2026, 1, 1),
            )
        )
        db.commit()

    # The startup path warns and leaves the edit alone...
    assert main([]) == 0
    assert main(["--check"]) == 1

    # ...and --fix is the repair, which deletes nothing.
    assert main(["--fix"]) == 0
    with opened(database) as db:
        row = patient_row(db, "P20260001")
        assert row.name == "Zhao Dayong"
        assert row.department.name == "Cardiology"
        kept = db.scalar(select(Patient.patient_no).where(Patient.patient_no == "P20269999"))
        assert kept == "P20269999"
        assert baseline_drift(db) == []
    assert main(["--check"]) == 0
