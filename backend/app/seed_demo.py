"""The presentation baseline: four accounts and three patients.

docs/02-测试场景.md drives every demo from this data, so the accounts, patient
numbers and allergies below are fixed -- change them only together with that
document and the scripts that assert on them.

Idempotent by design: the startup scripts run this on every launch, so it only
inserts what is missing and never overwrites a record that was edited during a
demo. That promise used to have a silent cost: a database seeded by an older
baseline keeps its old values -- an account still in the retired `General
Medicine` department, a patient whose name no longer matches §4, a demo password
that is not DEMO_PASSWORD -- and the documented demos then stop working without a
word. A run therefore *verifies* the pinned fields and prints what drifted, so at
least the drift is visible:

    python -m app.seed_demo            # insert what is missing; warn about drift
    python -m app.seed_demo --check    # report only, exit 1 on drift (CI)
    python -m app.seed_demo --fix      # rewrite the pinned fields; deletes nothing

`--fix` touches only the fields docs/02-测试场景.md §4 pins, so emails, extra
patients and every other table survive. docs/01-任务安排.md §8.4 still fixes the
*full* reset as "delete the database and seed again". Every account shares one
password, from DEMO_PASSWORD (default below); that is acceptable only because
this is demo data on a local database.
"""

import argparse
import os
from datetime import date

from sqlalchemy import select

from app import crypto
from app.auth import hash_password, verify_password
from app.config import Settings
from app.database import make_engine, session_factory
from app.models import Allergy, Department, Patient, Role, User
from app.schemas import join_tags

DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "Demo@2026")

# username, display name, email, title, department
USERS: tuple[tuple[str, str, str, str, str], ...] = (
    ("admin_zhang", "Zhang Wei", "admin_zhang@example.test", "admin", "Information Technology"),
    ("dr_li", "Dr Li", "dr_li@example.test", "senior", "Cardiology"),
    ("dr_wang", "Dr Wang", "dr_wang@example.test", "junior", "Cardiology"),
    ("dr_chen", "Dr Chen", "dr_chen@example.test", "senior", "Neurology"),
)

# patient_no, name, gender, birth_date, admitted_at, department, phone, id_card, tags, allergies
# Allergen codes come from app.allergies.DICTIONARY; names never go in that column.
# The admission dates are spread across a month so the date-range search filter
# has something to select.
PATIENTS: tuple[tuple, ...] = (
    (
        "P20260001",
        "Zhao Dayong",
        "male",
        "1968-03-12",
        "2026-08-03",
        "Cardiology",
        "13800001234",
        "110101196803071234",
        ("hypertension", "chest pain"),
        (
            ("PENICILLIN", "drug", "severe", "Anaphylaxis"),
            ("SULFONAMIDE", "drug", "moderate", "Rash"),
        ),
    ),
    (
        "P20260002",
        "Qian Xiuying",
        "female",
        "1955-11-02",
        "2026-08-11",
        "Cardiology",
        "13900002345",
        "110101195511021234",
        ("arrhythmia",),
        (),
    ),
    (
        "P20260003",
        "Sun Jianguo",
        "male",
        "1972-07-30",
        "2026-08-19",
        "Neurology",
        "13700003456",
        "110101197207301234",
        ("headache", "dizziness"),
        (("ASPIRIN", "drug", "moderate", "Gastric bleeding"),),
    ),
)

DRIFT_HEADER = "Baseline drift -- these pinned records no longer match docs/02-测试场景.md §4:"
DRIFT_REPAIR = (
    "Repair the pinned fields with `python -m app.seed_demo --fix` -- it rewrites only those "
    "fields, and deletes no row. docs/01-任务安排.md §8.4 keeps the full reset as: delete "
    "backend/doctor.db and let the startup script seed it again."
)


def master_data(db):
    """The departments and roles the baseline indexes into, or a hard stop."""
    departments = {d.name: d for d in db.scalars(select(Department))}
    roles = {r.name: r for r in db.scalars(select(Role))}
    missing = {name for _, _, _, _, name in USERS} - departments.keys()
    if missing or set(roles) < {"admin", "senior", "junior"}:
        raise SystemExit(
            f"Master data is missing ({sorted(missing) or 'roles'}). "
            "Run `python -m app.seed` first."
        )
    return departments, roles


def _restore_account(user, name, title, department, departments, roles, password_hash) -> list[str]:
    """Put the pinned fields of an account back on the baseline."""
    reset = []
    if user.name != name:
        user.name = name
        reset.append("name")
    if user.department_id != departments[department].id:
        user.department_id = departments[department].id
        reset.append("department")
    if user.role_id != roles[title].id:
        user.role_id = roles[title].id
        reset.append("title")
    if user.status != "active":
        user.status = "active"
        reset.append("status")
    if not verify_password(DEMO_PASSWORD, user.password_hash):
        user.password_hash = password_hash
        reset.append("password")
    return reset


def _restore_patient(patient, name, gender, birth_date, department_id) -> list[str]:
    """Put the pinned fields of a patient back on the baseline."""
    reset = []
    if patient.deleted_at is not None:
        patient.deleted_at = None
        reset.append("deleted_at")
    if patient.name != name:
        patient.name = name
        reset.append("name")
    if patient.gender != gender:
        patient.gender = gender
        reset.append("gender")
    expected = date.fromisoformat(birth_date)
    if patient.birth_date != expected:
        patient.birth_date = expected
        reset.append("birth_date")
    if patient.department_id != department_id:
        patient.department_id = department_id
        reset.append("department")
    return reset


def baseline_drift(db) -> list[str]:
    """Every way the pinned records differ from docs/02-测试场景.md §4.

    Read-only, and deliberately blind to what the document does not pin: emails
    are operational (teams point them at a real inbox), and an extra patient,
    allergy, tag or admission date is not drift.
    """
    drift: list[str] = []
    for username, name, _email, title, department in USERS:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            drift.append(f"account {username} is missing: expected {name} / {title} / {department}")
            continue
        if user.name != name:
            drift.append(f"account {username}: name is {user.name!r}, baseline is {name!r}")
        if user.department.name != department:
            drift.append(
                f"account {username}: department is {user.department.name!r}, "
                f"baseline is {department!r}"
            )
        if user.role.name != title:
            drift.append(f"account {username}: title is {user.role.name!r}, baseline is {title!r}")
        if user.status != "active":
            drift.append(f"account {username}: status is {user.status!r}, baseline is 'active'")
        elif not verify_password(DEMO_PASSWORD, user.password_hash):
            drift.append(f"account {username}: the password is no longer DEMO_PASSWORD")

    for (
        patient_no,
        name,
        gender,
        birth_date,
        _admitted_at,
        department,
        _phone,
        _id_card,
        _tags,
        allergies,
    ) in PATIENTS:
        patient = db.scalar(select(Patient).where(Patient.patient_no == patient_no))
        if patient is None:
            drift.append(f"patient {patient_no} is missing: expected {name} in {department}")
            continue
        if patient.deleted_at is not None:
            drift.append(f"patient {patient_no} is soft-deleted")
        if patient.name != name:
            drift.append(f"patient {patient_no}: name is {patient.name!r}, baseline is {name!r}")
        if patient.gender != gender:
            drift.append(
                f"patient {patient_no}: gender is {patient.gender!r}, baseline is {gender!r}"
            )
        expected_birth = date.fromisoformat(birth_date)
        if patient.birth_date != expected_birth:
            drift.append(
                f"patient {patient_no}: birth date is {patient.birth_date}, "
                f"baseline is {expected_birth}"
            )
        if patient.department.name != department:
            drift.append(
                f"patient {patient_no}: department is {patient.department.name!r}, "
                f"baseline is {department!r}"
            )
        for allergen, _type, severity, _reaction in allergies:
            recorded = db.scalar(
                select(Allergy).where(
                    Allergy.patient_id == patient.id, Allergy.allergen == allergen
                )
            )
            if recorded is None:
                drift.append(f"patient {patient_no}: the {allergen} allergy is missing")
            elif recorded.severity != severity:
                drift.append(
                    f"patient {patient_no}: {allergen} severity is {recorded.severity!r}, "
                    f"baseline is {severity!r}"
                )
    return drift


def report_drift(drift: list[str]) -> None:
    print(DRIFT_HEADER)
    for line in drift:
        print(f"  - {line}")
    print(DRIFT_REPAIR)


def seed_demo(*, repair: bool = False) -> list[str]:
    """Insert what is missing, verify, and (with `repair`) rewrite what drifted.

    `repair=True` is the `--fix` path. Rows are matched by username and patient
    number, and only the fields docs/02-测试场景.md §4 pins are touched, so a
    database seeded by an older baseline comes back without losing anything.
    """
    settings = Settings()
    # Match the running application, which configures this from the same setting.
    crypto.configure(settings.patient_data_key)
    engine = make_engine(settings.database_url)
    created = {"users": 0, "patients": 0}
    repaired: list[str] = []
    try:
        with session_factory(engine)() as db:
            departments, roles = master_data(db)
            password_hash = hash_password(DEMO_PASSWORD)
            for username, name, email, title, department in USERS:
                existing = db.scalar(select(User).where(User.username == username))
                if existing is not None:
                    if repair:
                        reset = _restore_account(
                            existing, name, title, department, departments, roles, password_hash
                        )
                        if reset:
                            repaired.append(f"account {username}: " + "/".join(reset))
                    continue
                db.add(
                    User(
                        username=username,
                        name=name,
                        email=email,
                        password_hash=password_hash,
                        role_id=roles[title].id,
                        department_id=departments[department].id,
                    )
                )
                created["users"] += 1
            db.flush()

            for (
                patient_no,
                name,
                gender,
                birth_date,
                admitted_at,
                department,
                phone,
                id_card,
                tags,
                allergies,
            ) in PATIENTS:
                patient = db.scalar(select(Patient).where(Patient.patient_no == patient_no))
                department_id = departments[department].id
                if patient is None:
                    # The table stores real dates: a Date column rejects the
                    # strings these constants are written as.
                    patient = Patient(
                        patient_no=patient_no,
                        name=name,
                        gender=gender,
                        birth_date=date.fromisoformat(birth_date),
                        department_id=department_id,
                        notes="Presentation baseline record",
                        phone_enc=crypto.encrypt(phone) if phone else None,
                        id_card_enc=crypto.encrypt(id_card) if id_card else None,
                        symptom_tags=join_tags(list(tags)),
                        admitted_at=date.fromisoformat(admitted_at),
                    )
                    db.add(patient)
                    db.flush()
                    created["patients"] += 1
                elif repair:
                    reset = _restore_patient(patient, name, gender, birth_date, department_id)
                    if reset:
                        repaired.append(f"patient {patient_no}: " + "/".join(reset))
                # A missing allergy is filled in either way: §4.2 makes the
                # 青霉素(严重) record the star of the allergy demo, and adding a
                # row is what "only inserts what is missing" means.
                for allergen, allergy_type, severity, reaction in allergies:
                    recorded = db.scalar(
                        select(Allergy).where(
                            Allergy.patient_id == patient.id, Allergy.allergen == allergen
                        )
                    )
                    if recorded is None:
                        db.add(
                            Allergy(
                                patient_id=patient.id,
                                allergen=allergen,
                                allergy_type=allergy_type,
                                severity=severity,
                                reaction=reaction,
                                recorded_at=patient.admitted_at,
                            )
                        )
                        repaired.append(f"patient {patient_no}: added the {allergen} allergy")
                    elif repair and (
                        recorded.severity != severity or recorded.allergy_type != allergy_type
                    ):
                        recorded.severity = severity
                        recorded.allergy_type = allergy_type
                        repaired.append(f"patient {patient_no}: {allergen} restored to {severity}")
            db.commit()
            drift = baseline_drift(db)
    finally:
        engine.dispose()

    print(
        f"Demo data ready: {created['users']} account(s) and {created['patients']} patient(s) added, "
        f"{len(USERS) - created['users']} and {len(PATIENTS) - created['patients']} already present."
    )
    for line in repaired:
        print(f"Baseline restored: {line}")
    print(f"Sign in as any of {', '.join(u[0] for u in USERS)} with password {DEMO_PASSWORD}.")
    if drift:
        # A warning, not a failure: the startup scripts call this, and a demo
        # machine must not refuse to boot over one patient's department.
        print()
        report_drift(drift)
    return drift


def check_baseline() -> list[str]:
    """Read-only drift report: writes nothing, not even a missing record."""
    settings = Settings()
    crypto.configure(settings.patient_data_key)
    engine = make_engine(settings.database_url)
    try:
        with session_factory(engine)() as db:
            master_data(db)
            return baseline_drift(db)
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed and verify the presentation baseline.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="report baseline drift and exit 1; write nothing at all",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="rewrite the pinned fields of the pinned rows; deletes nothing",
    )
    args = parser.parse_args(argv)

    if args.check:
        drift = check_baseline()
        if drift:
            report_drift(drift)
            return 1
        print("Baseline matches docs/02-测试场景.md §4.")
        return 0

    drift = seed_demo(repair=args.fix)
    return 1 if args.fix and drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
