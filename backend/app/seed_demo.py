"""The presentation baseline: four accounts and three patients.

docs/02-测试场景.md drives every demo from this data, so the accounts, patient
numbers and allergies below are fixed -- change them only together with that
document and the scripts that assert on them.

Idempotent by design: the startup scripts run this on every launch, so it only
inserts what is missing and never overwrites a record that was edited during a
demo. Every account shares one password, from DEMO_PASSWORD (default below);
that is acceptable only because this is demo data in a local database.
"""

import os
from datetime import date

from sqlalchemy import select

from app import crypto
from app.auth import hash_password
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


def seed_demo() -> None:
    settings = Settings()
    # Match the running application, which configures this from the same setting.
    crypto.configure(settings.patient_data_key)
    engine = make_engine(settings.database_url)
    created = {"users": 0, "patients": 0}
    try:
        with session_factory(engine)() as db:
            departments = {d.name: d for d in db.scalars(select(Department))}
            roles = {r.name: r for r in db.scalars(select(Role))}
            missing = {name for _, _, _, _, name in USERS} - departments.keys()
            if missing or set(roles) < {"admin", "senior", "junior"}:
                raise SystemExit(
                    f"Master data is missing ({sorted(missing) or 'roles'}). "
                    "Run `python -m app.seed` first."
                )

            password_hash = hash_password(DEMO_PASSWORD)
            for username, name, email, title, department in USERS:
                if db.scalar(select(User.id).where(User.username == username)) is not None:
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
                if db.scalar(select(Patient.id).where(Patient.patient_no == patient_no)):
                    continue
                # The table stores real dates: a Date column rejects the strings
                # these constants are written as.
                patient = Patient(
                    patient_no=patient_no,
                    name=name,
                    gender=gender,
                    birth_date=date.fromisoformat(birth_date),
                    department_id=departments[department].id,
                    notes="Presentation baseline record",
                    phone_enc=crypto.encrypt(phone) if phone else None,
                    id_card_enc=crypto.encrypt(id_card) if id_card else None,
                    symptom_tags=join_tags(list(tags)),
                    admitted_at=date.fromisoformat(admitted_at),
                )
                db.add(patient)
                db.flush()
                for allergen, allergy_type, severity, reaction in allergies:
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
                created["patients"] += 1
            db.commit()
    finally:
        engine.dispose()

    print(
        f"Demo data ready: {created['users']} account(s) and {created['patients']} patient(s) added, "
        f"{len(USERS) - created['users']} and {len(PATIENTS) - created['patients']} already present."
    )
    print(f"Sign in as any of {', '.join(u[0] for u in USERS)} with password {DEMO_PASSWORD}.")


if __name__ == "__main__":
    seed_demo()
