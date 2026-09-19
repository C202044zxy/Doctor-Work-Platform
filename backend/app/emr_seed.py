"""M4 master data; dose thresholds are configurable database rules."""

from sqlalchemy import select

from app.emr_models import Drug, EmrTemplate


def seed_emr(db):
    for name in ("Admission note", "Daily progress note"):
        if db.scalar(select(EmrTemplate).where(EmrTemplate.name == name)) is None:
            fields = [
                {
                    "key": "chief_complaint",
                    "label": "Chief complaint",
                    "type": "text",
                    "required": True,
                },
                {"key": "history", "label": "History", "type": "textarea"},
                {"key": "diagnosis", "label": "Diagnosis", "type": "text", "required": True},
                {"key": "temperature", "label": "Temperature (C)", "type": "number"},
                {"key": "note_date", "label": "Note date", "type": "date", "required": True},
                {
                    "key": "severity",
                    "label": "Severity",
                    "type": "select",
                    "options": ["mild", "moderate", "severe"],
                },
                {"key": "plan", "label": "Treatment plan", "type": "textarea"},
            ]
            db.add(EmrTemplate(name=name, fields_json={"fields": fields}))
    for code, name, spec, frequency, tags, low, high, unit, daily in [
        ("AMOX500", "Amoxicillin capsules", "0.5g", "tid", ["PENICILLIN"], 0.5, 0.5, "g", False),
        ("SMZ", "Co-trimoxazole", "2 tablets", "bid", ["SULFONAMIDE"], 2, 2, "tablets", False),
        (
            "ASP100",
            "Aspirin enteric-coated tablets",
            "100mg",
            "qd",
            ["ASPIRIN"],
            100,
            100,
            "mg",
            False,
        ),
        ("FURO20", "Furosemide tablets", "20mg", "qd", [], 20, 40, "mg", True),
    ]:
        if db.get(Drug, code) is None:
            db.add(
                Drug(
                    code=code,
                    name=name,
                    spec=spec,
                    default_frequency=frequency,
                    contraindications=tags,
                    dose_min=f"{low:g}{unit}",
                    dose_max=f"{high:g}{unit}",
                    dose_rule={"min": low, "max": high, "unit": unit, "daily": daily},
                )
            )
