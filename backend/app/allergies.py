"""Task T14: the allergen dictionary and the one shared reader for a patient's allergies."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Allergy, Patient

# The five families T14 criterion 3 requires, plus anything a clinic adds later.
# Codes are the vocabulary the order-validation engine compares against
# Drug.contraindications, so they are English and uppercase; the display names
# follow the English-UI rule in docs/api/API-索引.md 1.2.
DICTIONARY: tuple[dict[str, str], ...] = (
    {"code": "PENICILLIN", "name": "Penicillins"},
    {"code": "SULFONAMIDE", "name": "Sulfonamides"},
    {"code": "CEPHALOSPORIN", "name": "Cephalosporins"},
    {"code": "ASPIRIN", "name": "Aspirin"},
    {"code": "CONTRAST_MEDIA", "name": "Contrast media"},
)

_NAMES = {entry["code"]: entry["name"] for entry in DICTIONARY}


def dictionary(db: Session) -> list[dict[str, str]]:
    """The built-in families followed by every custom code a clinic has recorded.

    T14 criterion 3 lists five families and asks for custom additions, but the
    contract exposes one read-only route for the dictionary, so a custom value
    cannot be registered on its own. The dictionary grows from use instead: every
    code recorded on a patient is listed, and a code with no display name falls
    back to the code itself.
    """
    built_in = {entry["code"] for entry in DICTIONARY}
    recorded = db.scalars(select(Allergy.allergen).distinct())
    custom = [
        {"code": code, "name": _NAMES.get(code, code)}
        for code in sorted(code for code in recorded if code not in built_in)
    ]
    return [dict(entry) for entry in DICTIONARY] + custom


def allergen_name(code: str) -> str:
    """Display name for a dictionary code; a custom addition falls back to its code."""
    return _NAMES.get(code, code)


def get_patient_allergens(db: Session, patient_no: str) -> list[Allergy]:
    """Every allergy recorded for a live patient, oldest first.

    This is the single source of truth T14 criterion 2 asks for: the detail-page
    warning banner and the T21 order-validation engine both call this function
    instead of querying ``allergies`` themselves, so the two cannot drift apart.

    A missing or soft-deleted patient answers with an empty list rather than an
    error, because the validation engine treats "no allergies" and "no patient"
    the same way: nothing to block.
    """
    patient_id = db.scalar(
        select(Patient.id).where(
            Patient.patient_no == patient_no,
            Patient.deleted_at.is_(None),
        )
    )
    if patient_id is None:
        return []
    return list(
        db.scalars(select(Allergy).where(Allergy.patient_id == patient_id).order_by(Allergy.id))
    )
