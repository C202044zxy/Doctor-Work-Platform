"""The full-flow baseline: the state the three demonstration flows start from.

`app.seed` writes master data, `app.seed_demo` writes the four accounts and the
three patients `docs/02-测试场景.md` §4 pins -- and neither writes a single
piece of clinical activity. A freshly built database therefore opens on empty
workbenches: the waiting queue, the review queue, the consultation history, the
patient's health chart and its consultation tab all have nothing in them until
someone performs the entire flow by hand. This module fills that gap. It seeds
the *state* §3's three flows assume, so a demonstration can start at any step,
and so an empty list always means "nothing happened" rather than "nothing was
set up".

    python -m app.seed_flow            # insert what is missing
    python -m app.seed_flow --check    # report only, exit 1 on anything missing

What it writes, and what each row is for
----------------------------------------
* **M2** one Cardiology group holding `P20260001` and `P20260002`, so the group
  filter (M2-T9) has something to return.
* **M3** three consultations, one in each state, because the workbench groups by
  state and an empty column proves nothing: a `waiting` one the department may
  accept, an `active` one with its opening exchange, and an `ended` one from the
  previous month carrying 50 messages, one image and a call. These are patient
  channels -- both transcripts read as one consultation held with the patient,
  not as two clinicians conferring. Doctor-to-doctor clinical discussion is the
  M5 meeting below, which lives behind Remote consultation.
* **M4** three records for `dr_wang`: an archived admission note with three
  versions and a review by `dr_li`, a draft progress note with three orders
  (passed, dose-warned, stopped), and one awaiting review on `P20260002` so the
  senior's queue is not empty.
* **M5** one completed consultation on `P20260001` between `dr_wang` and
  `dr_chen`, with its material, its three-expert report and a grant that has
  already expired.
* **M6** `P20260001`'s hypertension plan with its reminder rules, three fired
  reminders -- one unread, so the workspace red dot is real -- fourteen days of
  blood pressure with the 160/100 reading in it, glucose and heart-rate series
  so the chart can be switched, and one assessment.

Three rules this module follows
-------------------------------
**It reuses the baseline and invents no one.** The accounts and patients are
`app.seed_demo`'s; this module never adds a user or a patient, so the contract
`scripts/build_db.py` verifies -- four accounts, three patients -- still holds
after it runs.

**It does not seed the audit trail.** `audit_logs` records what actually
happened, and a fabricated entry is worse than a missing one: the trail is the
thing a defence is asked to trust. It fills up on its own as soon as anyone
walks the flows.

**Values the runtime computes are computed here too**, by calling the same
functions (`app.emr_validation.validate_orders`, `app.health._is_abnormal`)
rather than by copying their answers. A seeded row whose `is_abnormal` or
`validation_detail` disagreed with the server's would put two screens into
contradiction about the same reading.
"""

import argparse
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from app.config import Settings
from app.database import make_engine, session_factory
from app.emr_models import Drug, EmrRecord, EmrTemplate, EmrVersion, MedicalOrder
from app.emr_schemas import OrderItem
from app.emr_validation import validate_orders
from app.health import _is_abnormal
from app.models import (
    Department,
    HealthAssessment,
    HealthPlan,
    Meeting,
    MeetingMaterial,
    MeetingParticipant,
    MeetingReport,
    Patient,
    PatientGroup,
    PatientGroupMember,
    ReminderLog,
    ReminderRule,
    TempGrant,
    User,
    VitalSign,
    VitalThreshold,
)
from app.work_models import CallLog, Consultation, ConsultMessage, ImageUpload

# The four accounts and three patients app.seed_demo writes. This module is a
# third layer on top of both, never a source of either.
ACCOUNTS = ("admin_zhang", "dr_li", "dr_wang", "dr_chen")
PATIENT_NOS = ("P20260001", "P20260002", "P20260003")

# The uploaded files this module writes. Their names are fixed rather than
# random, which is what makes a second run recognise its own work instead of
# piling up another copy of the same attachment every time.
IMAGE_FILENAME = "seedflow-consult-image.png"
MATERIAL_FILENAME = "心电图-2026-09-01.pdf"
MATERIAL_STORED_NAME = "seedflow-ecg-2026-09-01.pdf"
SEEDED_FILES = (IMAGE_FILENAME, f"meeting/{MATERIAL_STORED_NAME}")

GROUP = {
    "name": "Chronic follow-up",
    "description": "Cardiology patients on a monthly review cycle.",
    "department": "Cardiology",
    "created_by": "dr_wang",
    "members": ("P20260001", "P20260002"),
}

MEETING_TITLE = "Furosemide dose review before discharge"
MEETING_PURPOSE = "Confirm the diuretic dose before discharge."
PLAN_TITLE = "Hypertension management plan"

PLAN = {
    "goals": "Keep the home blood pressure below 140/90 mmHg and keep the 09:00 dose.",
    "instructions": "Low-salt diet, 30 minutes of walking daily, and a diary of morning readings.",
    "entries": (
        {"kind": "medication", "text": "Amlodipine 5 mg once daily", "done": False},
        {"kind": "followup", "text": "Clinic review in one month", "done": False},
        {
            "kind": "diet_exercise",
            "text": "Low-salt diet, 30 minutes of walking daily",
            "done": True,
        },
    ),
}

# rtype / title / cron / active. The cron is evaluated in UTC by
# `app.health.due_this_minute`, so a rule is a schedule to display; the logs
# below are what make it a schedule that has fired.
REMINDER_RULES = (
    ("medication", "Take amlodipine 5 mg", "0 9 * * *", True),
    ("followup", "Weekly blood pressure log", "0 20 * * 0", True),
    ("checkin", "Evening weight check", "0 21 * * *", False),
)

# (rule index, days ago, done, read). The first is the unread one.
REMINDER_LOGS = ((0, 1, False, False), (0, 2, True, True), (1, 3, False, True))

# (days ago, systolic, diastolic). 160/100 is the one blood-pressure reading
# above the 140/90 range, and it is the point M6-T4 hovers over.
BP_SERIES = (
    (13, 132, 84),
    (12, 128, 80),
    (11, 136, 86),
    (10, 160, 100),
    (9, 130, 82),
    (8, 126, 78),
    (7, 134, 88),
    (6, 129, 81),
    (5, 138, 88),
    (4, 131, 83),
    (3, 127, 79),
    (2, 133, 85),
    (1, 130, 82),
    (0, 135, 87),
)
GL_SERIES = ((12, 5.4), (10, 7.8), (8, 6.0), (6, 5.7), (4, 5.2), (3, 6.4), (2, 5.9), (1, 5.6))
HR_SERIES = ((12, 76), (10, 92), (8, 110), (6, 84), (4, 72), (3, 88), (2, 79), (1, 81))

# (speaker, text) for the ended consultation. This is the *patient* channel, so
# the transcript is a consultation and not two clinicians conferring: `dr_li`
# accepted the room and his lines are addressed to the patient, while `dr_wang`
# voices the patient and the carer sitting with him. That is the split the chat
# itself enforces -- whoever did not accept the room sends as `patient_assist`
# -- and with no patient account in the baseline, the initiating doctor's window
# is what stands at the patient end.
#
# Doctor-to-doctor discussion is a different channel and is seeded as one: the
# M5 meeting below, reached through Consultations -> Remote consultation.
CHAT_SCRIPT = (
    ("dr_wang", "Good morning. This is Zhao Dayong, calling about the tightness in my chest."),
    ("dr_li", "Good morning Mr Zhao. Tell me when it started."),
    ("dr_wang", "Three days ago. It comes on when I walk up the stairs to my flat."),
    ("dr_li", "What does it feel like -- sharp, heavy, or burning?"),
    ("dr_wang", "Heavy. Like a weight sitting on my chest."),
    ("dr_li", "Does it spread anywhere else?"),
    ("dr_wang", "Up to my left shoulder, sometimes as far as my jaw."),
    ("dr_li", "And how long does one spell last?"),
    ("dr_wang", "Five minutes, or a little less if I sit down and rest."),
    ("dr_li", "Does it come when you are sitting still, or only when you move about?"),
    ("dr_wang", "Only when I move about. Nothing at rest, and I sleep through the night."),
    ("dr_li", "Any breathlessness, sweating, or feeling sick with it?"),
    ("dr_wang", "Short of breath, yes. No sweating."),
    ("dr_li", "Thank you, that is useful. Have you had this chest pain before this week?"),
    ("dr_wang", "Once last week, on the same stairs. It went off and I thought nothing of it."),
    ("dr_li", "It was right to mention it. Is it worse after meals?"),
    ("dr_wang", "After a large lunch it burns a little, and sitting up helps."),
    ("dr_li", "That may be the stomach rather than the heart. We will keep both in mind."),
    ("dr_li", "Your record lists high blood pressure and diabetes. Is that still right?"),
    ("dr_wang", "Yes. The blood pressure for eight years, and the sugar is diet controlled."),
    ("dr_li", "What are you taking for them?"),
    ("dr_wang", "Amlodipine 5 mg every morning, and furosemide 20 mg once a day."),
    ("dr_li", "Do you ever miss a dose?"),
    ("dr_wang", "Very rarely. My wife puts them out for me at breakfast."),
    ("dr_li", "Good. Any allergies I should know about?"),
    ("dr_wang", "Penicillin. I came out in a rash all over my body."),
    ("dr_li", "How soon after the tablet did that happen?"),
    ("dr_wang", "Within the hour. The doctor stopped it straight away."),
    ("dr_li", "Anything else?"),
    ("dr_wang", "Sulfa tablets make me sick to my stomach."),
    ("dr_li", "Both go on your record as warnings. Does anyone in the family have heart trouble?"),
    ("dr_wang", "My father had a heart attack when he was 64."),
    ("dr_li", "Do you smoke?"),
    ("dr_wang", "I stopped ten years ago. I only drink at weekends."),
    ("dr_li", "Have you taken your blood pressure today?"),
    ("dr_wang", "142 over 88, and the pulse was 92. The nurse wrote it down this morning."),
    ("dr_li", "And your temperature?"),
    ("dr_wang", "36.8."),
    ("dr_li", "Have you had an ECG?"),
    ("dr_wang", "Yes, at the clinic this morning. I have the tracing here."),
    ("dr_li", "What did they say about it?"),
    ("dr_wang", "That the rhythm was regular and nothing urgent showed up."),
    ("dr_li", "Good. Were any blood tests taken?"),
    ("dr_wang", "This morning, but the results were not back when I left."),
    ("dr_li", "Then let me tell you where we stand."),
    ("dr_li", "Tightness on effort has to be taken seriously until those results come back."),
    ("dr_wang", "Should I be worried?"),
    (
        "dr_li",
        "Careful rather than frightened. Do not rush up the stairs, and sit down when it starts.",
    ),
    (
        "dr_li",
        (
            "Keep the furosemide at 20 mg, not above 40 mg a day without a review, and stay on "
            "the amlodipine. We will set a 09:00 dose reminder on your plan. If the tightness "
            "comes at rest, or lasts more than ten minutes, call the clinic at once."
        ),
    ),
    ("dr_wang", "Understood. I am sending you this morning's tracing now."),
)

# The opening exchange of the active consultation on `P20260002`, read the same
# way as the transcript above: `dr_li` is the accepting doctor speaking to the
# patient, `dr_wang` is the patient end.
ACTIVE_CHAT = (
    ("dr_wang", "Good morning doctor. This is Mrs Qian. My heart raced twice last night in bed."),
    ("dr_li", "Good morning Mrs Qian. Did you feel dizzy or short of breath with it?"),
    ("dr_wang", "The first one made my heart pound and I felt a little light-headed."),
    (
        "dr_li",
        (
            "Thank you. Keep taking the tablets exactly as before; I will review the blood "
            "thinner with you tomorrow."
        ),
    ),
)

# (drug_code, dose, frequency, route). The second is over the daily maximum, so
# it is stored as the warning M4-T8 demonstrates; the third is stopped.
ORDERS = (
    ("FURO20", "20mg", "qd", "oral"),
    ("FURO20", "80mg", "qd", "oral"),
    ("FURO20", "40mg", "qd", "oral"),
)
STOPPED_ORDER_INDEX = 2

# The contract `scripts/build_db.py` checks a freshly built database against.
# Keyed by model, so the check reads its own table name, and exact because this
# module only ever runs before anyone has used the database.
EXPECTED_COUNTS = {
    PatientGroup: 1,
    PatientGroupMember: len(GROUP["members"]),
    Consultation: 3,
    ConsultMessage: len(CHAT_SCRIPT) + 1 + len(ACTIVE_CHAT),
    CallLog: 1,
    ImageUpload: 1,
    EmrRecord: 3,
    EmrVersion: 6,
    MedicalOrder: len(ORDERS),
    Meeting: 1,
    MeetingParticipant: 1,
    MeetingMaterial: 1,
    MeetingReport: 1,
    TempGrant: 1,
    HealthPlan: 1,
    ReminderRule: len(REMINDER_RULES),
    ReminderLog: len(REMINDER_LOGS),
    HealthAssessment: 1,
    VitalSign: len(BP_SERIES) + len(GL_SERIES) + len(HR_SERIES),
}

MESSAGES = len(CHAT_SCRIPT) + 1 + len(ACTIVE_CHAT)
READINGS = len(BP_SERIES) + len(GL_SERIES) + len(HR_SERIES)

SUMMARY = (
    "  M2  1 Cardiology group with 2 members",
    f"  M3  3 consultations (waiting / active / ended), {MESSAGES} messages, 1 image, 1 call",
    "  M4  3 records (archived / draft / pending) and 3 orders",
    "  M5  1 completed consultation with a material, a report and an expired grant",
    f"  M6  1 plan, 3 rules, 3 reminders (1 unread), {READINGS} readings, 1 assessment",
)

COUNTERS = (
    "groups",
    "members",
    "consultations",
    "messages",
    "calls",
    "images",
    "records",
    "versions",
    "orders",
    "meetings",
    "participants",
    "grants",
    "materials",
    "reports",
    "plans",
    "rules",
    "logs",
    "vitals",
    "assessments",
)


class FlowError(RuntimeError):
    """The database does not have the baseline this module builds on."""


def _resolve(db):
    """The accounts, patients and departments the baseline pins, or a hard stop.

    Everything below indexes into these by name, so a missing one is reported
    once, up front, instead of surfacing as an `AttributeError` deep inside a
    spec.
    """
    users = {row.username: row for row in db.scalars(select(User))}
    patients = {row.patient_no: row for row in db.scalars(select(Patient))}
    departments = {row.name: row for row in db.scalars(select(Department))}
    missing = [name for name in ACCOUNTS if name not in users]
    missing += [no for no in PATIENT_NOS if no not in patients]
    if missing:
        raise FlowError(
            f"The demonstration baseline is missing ({', '.join(missing)}). "
            "Run `python -m app.seed` and `python -m app.seed_demo` first."
        )
    return users, patients, departments


def _previous_month(now: datetime) -> datetime:
    """A fixed instant in the previous calendar month.

    The ended consultation, the archived record and the completed meeting are
    dated this way on purpose: M3-T9 filters records by "this month" and expects
    the consultation the demonstration creates live, so last month's history has
    to stay outside that window however late in the month the database happens
    to be built.
    """
    first_of_this_month = now.replace(day=1, hour=10, minute=0, second=0, microsecond=0)
    return first_of_this_month - timedelta(days=15)


def _seed_bytes() -> dict[str, bytes]:
    """The two attachments, built rather than committed.

    A binary fixture in git cannot be reviewed, and the database that points at
    it is itself rebuilt from text, so the files are generated from the same
    recipe every time: a real one-page PDF (M5-T4 downloads it and expects it to
    open) and a plausible ECG tracing for the chat image bubble.
    """
    return {
        IMAGE_FILENAME: _png_bytes(),
        f"meeting/{MATERIAL_STORED_NAME}": _pdf_bytes("ECG sample - 2026-09-01"),
    }


def _png_bytes() -> bytes:
    from PIL import Image, ImageDraw

    width, height, baseline = 480, 200, 150
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((10, 10), "ECG sample - 2026-09-01 (demo attachment)", fill=(60, 60, 60))
    points = []
    for x in range(width):
        phase = x % 80
        y = baseline
        if 28 <= phase < 32:
            y = baseline - 60
        elif 32 <= phase < 36:
            y = baseline - 105
        elif 36 <= phase < 40:
            y = baseline + 30
        elif 12 <= phase < 20:
            y = baseline - 12
        elif 48 <= phase < 58:
            y = baseline - 22
        points.append((x, y))
    draw.line(points, fill=(198, 40, 40), width=2)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _pdf_bytes(text: str) -> bytes:
    """One page, one line of text, and an xref table with computed offsets.

    The offsets are the part hand-written PDFs get wrong, and a viewer that
    cannot read the cross-reference table shows a blank page rather than an
    error -- the one outcome this file exists to avoid.
    """
    stream = f"BT /F1 14 Tf 72 760 Td ({text}) Tj ET".encode("ascii")
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    )
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % index + body + b"\nendobj\n"
    start = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        start,
    )
    return bytes(out)


def write_files(upload_dir: Path) -> int:
    """Write the attachments under `upload_dir`, overwriting their own names.

    Rewriting rather than skipping is what makes a run after a directory cleanup
    self-healing: the row in `image_upload` and the file it names are a pair,
    and half a pair is a broken image in the chat history.
    """
    written = 0
    for name, payload in _seed_bytes().items():
        target = upload_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        written += 1
    return written


def _consultations(db, users, patients, now, counts) -> None:
    """One consultation per state, plus its messages, its image and its call."""
    last_month = _previous_month(now)
    sessions = {}
    ours = {}

    specs = (
        # patient, creator, doctor, status, script, started_at
        ("P20260001", "dr_li", None, "waiting", (), now - timedelta(hours=1)),
        ("P20260002", "dr_wang", "dr_li", "active", ACTIVE_CHAT, now - timedelta(hours=6)),
        ("P20260001", "dr_wang", "dr_li", "ended", CHAT_SCRIPT, last_month),
    )
    for patient_no, creator, doctor, status, script, started in specs:
        patient = patients[patient_no]
        # A consultation has no natural key, so (patient, creator, state) is the
        # identity a re-run matches on. The three sessions above are distinct
        # under it, and a session the demonstration creates later is a fourth
        # combination rather than a duplicate.
        row = db.scalar(
            select(Consultation).where(
                Consultation.patient_id == patient.id,
                Consultation.created_by == users[creator].id,
                Consultation.status == status,
            )
        )
        fresh = row is None
        if fresh:
            row = Consultation(
                patient_id=patient.id,
                created_by=users[creator].id,
                doctor_id=users[doctor].id if doctor else None,
                status=status,
                started_at=started if status != "waiting" else None,
                # Closed 12 minutes after the last line: the image and the call
                # below sit inside that window, so the timeline reads in order.
                ended_at=(
                    started + timedelta(minutes=2 * len(script) + 12) if status == "ended" else None
                ),
                created_at=started,
            )
            db.add(row)
            db.flush()
            counts["consultations"] += 1
        sessions[status] = row
        ours[status] = fresh

        # The transcript is written only alongside the session this run created.
        # A session found in place belongs to whoever made it -- matching the
        # triple above is not licence to inject fifty lines into a room a
        # demonstration is using.
        if not fresh:
            continue
        doctor_id = users[doctor].id if doctor else None
        sent = started
        for index, (speaker, text) in enumerate(script):
            sent = started + timedelta(minutes=2 * index)
            db.add(
                ConsultMessage(
                    consultation_id=row.id,
                    sender_id=users[speaker].id,
                    sender_type="doctor" if users[speaker].id == doctor_id else "patient_assist",
                    sender_name=users[speaker].name,
                    content=text,
                    sent_at=sent,
                )
            )
            counts["messages"] += 1
        if script:
            row.last_message = script[-1][1][:200]
            row.last_message_at = sent

    # The image message and the call hang off the room for the same reason the
    # transcript does, so they follow it: a room this run did not create gets
    # nothing added to it.
    if not ours["ended"]:
        return
    ended = sessions["ended"]
    if db.scalar(select(ImageUpload.id).where(ImageUpload.filename == IMAGE_FILENAME)) is None:
        sent = last_month + timedelta(minutes=2 * len(CHAT_SCRIPT))
        db.add(
            ImageUpload(
                filename=IMAGE_FILENAME,
                owner_id=users["dr_wang"].id,
                consultation_id=ended.id,
                created_at=sent,
            )
        )
        db.add(
            ConsultMessage(
                consultation_id=ended.id,
                sender_id=users["dr_wang"].id,
                sender_type="patient_assist",
                sender_name=users["dr_wang"].name,
                content="[Image] ECG tracing from this morning",
                image_url=f"/uploads/{IMAGE_FILENAME}",
                sent_at=sent,
            )
        )
        counts["messages"] += 1
        counts["images"] += 1
        ended.last_message = "ECG tracing from this morning"
        ended.last_message_at = sent

    if db.scalar(select(CallLog.id).where(CallLog.consultation_id == ended.id)) is None:
        # Sixty connected seconds after a five-second ring, and a normal
        # hang-up: §4.4 pins the baseline call as 60 seconds, S3 rebuilds its
        # playback timeline from these three instants, and the runtime derives
        # `duration_seconds` from `ended_at - connected_at`, so the same sum is
        # taken here rather than asserted.
        finished = last_month + timedelta(minutes=2 * len(CHAT_SCRIPT) + 5)
        connected = finished - timedelta(seconds=60)
        db.add(
            CallLog(
                consultation_id=ended.id,
                call_id=f"seedflow-call-{ended.id}",
                started_at=connected - timedelta(seconds=5),
                connected_at=connected,
                ended_at=finished,
                duration_seconds=int((finished - connected).total_seconds()),
                end_reason="hangup",
            )
        )
        counts["calls"] += 1


def _group(db, users, patients, departments, counts) -> None:
    """M2: the department's manual grouping and its two members."""
    department = departments[GROUP["department"]]
    row = db.scalar(
        select(PatientGroup).where(
            PatientGroup.department_id == department.id, PatientGroup.name == GROUP["name"]
        )
    )
    if row is None:
        row = PatientGroup(
            name=GROUP["name"],
            description=GROUP["description"],
            department_id=department.id,
            created_by=users[GROUP["created_by"]].id,
        )
        db.add(row)
        db.flush()
        counts["groups"] += 1
    for patient_no in GROUP["members"]:
        patient_id = patients[patient_no].id
        member = db.scalar(
            select(PatientGroupMember).where(
                PatientGroupMember.group_id == row.id,
                PatientGroupMember.patient_id == patient_id,
            )
        )
        if member is None:
            db.add(PatientGroupMember(group_id=row.id, patient_id=patient_id))
            counts["members"] += 1


def _templates(db) -> dict[str, EmrTemplate]:
    templates = {row.name: row for row in db.scalars(select(EmrTemplate))}
    missing = {"Admission note", "Daily progress note"} - templates.keys()
    if missing:
        raise FlowError(
            f"The EMR templates are missing ({sorted(missing)}). Run `python -m app.seed` first."
        )
    return templates


def _record(db, users, patient, template, author, status, contents) -> EmrRecord:
    """One record plus its immutable version snapshots.

    The versions are written the way submission writes them: v1 is the draft
    frozen on first submission, and each later version is a state that was
    submitted. A record whose versions disagreed with its own content would make
    the history panel contradict the record it belongs to.
    """
    first_at, last_at = contents[0][0], contents[-1][0]
    archived = status == "archived"
    row = EmrRecord(
        patient_id=patient.id,
        template_id=template.id,
        template_snapshot={
            "id": template.id,
            "name": template.name,
            "description": template.description,
            "fields_json": template.fields_json,
            "is_active": template.is_active,
        },
        author_id=users[author].id,
        content_json=contents[-1][1],
        status=status,
        version=len(contents),
        created_at=first_at,
        updated_at=last_at,
        submitted_at=None if status == "draft" else last_at,
        reviewer_id=users["dr_li"].id if archived else None,
        review_comment="Reviewed and archived." if archived else None,
        reviewed_at=last_at if archived else None,
    )
    db.add(row)
    db.flush()
    for index, (created_at, content) in enumerate(contents, start=1):
        db.add(
            EmrVersion(
                record_id=row.id,
                version=index,
                content_json=content,
                author_id=users[author].id,
                created_at=created_at,
            )
        )
    return row


def _records(db, users, patients, now, counts) -> None:
    """M4: an archived record, a draft carrying orders, and one awaiting review."""
    templates = _templates(db)
    admission, progress = templates["Admission note"], templates["Daily progress note"]
    last_month = _previous_month(now)
    # A record's identity here is (patient, template): the three specs below are
    # distinct under it, and anything the demonstration creates later belongs to
    # a different patient or template.
    present = {(row.patient_id, row.template_id) for row in db.scalars(select(EmrRecord))}

    first = {
        "chief_complaint": "Exertional chest tightness for three days.",
        "history": "Hypertension since 2015, type 2 diabetes since 2019, both diet-controlled.",
        "diagnosis": "Stable angina pectoris",
        "temperature": 36.7,
        "note_date": (last_month - timedelta(days=2)).date().isoformat(),
        "severity": "moderate",
        "plan": "Continue amlodipine 5 mg daily and review the diuretic dose.",
    }
    submitted = {**first, "temperature": 36.8, "diagnosis": "Stable angina pectoris, NYHA II"}
    amended = {**submitted, "plan": "Continue amlodipine; cardiology review moved to next month."}
    if (patients["P20260001"].id, admission.id) not in present:
        _record(
            db,
            users,
            patients["P20260001"],
            admission,
            "dr_wang",
            "archived",
            (
                (last_month - timedelta(days=2), first),
                (last_month - timedelta(days=1), submitted),
                (last_month, amended),
            ),
        )
        counts["records"] += 1
        counts["versions"] += 3

    if (patients["P20260001"].id, progress.id) not in present:
        draft = _record(
            db,
            users,
            patients["P20260001"],
            progress,
            "dr_wang",
            "draft",
            (
                (
                    now - timedelta(days=3),
                    {
                        "chief_complaint": "Chest tightness on exertion, milder than yesterday.",
                        "history": "Admitted two days ago; troponin negative on admission.",
                        "diagnosis": "Stable angina pectoris, improving",
                        "temperature": 36.6,
                        "note_date": (now - timedelta(days=3)).date().isoformat(),
                        "severity": "mild",
                        "plan": "Continue the diuretic; mobilise as tolerated.",
                    },
                ),
            ),
        )
        counts["records"] += 1
        counts["versions"] += 1
        for index, (code, dose, frequency, route) in enumerate(ORDERS):
            item = OrderItem(
                order_type="drug", drug_code=code, dose=dose, frequency=frequency, route=route
            )
            # The engine the API calls, so a seeded order carries exactly the
            # status and the reasons a live one would have been given.
            validation = validate_orders(db, patients["P20260001"].patient_no, [item])["results"][0]
            db.add(
                MedicalOrder(
                    record_id=draft.id,
                    patient_id=draft.patient_id,
                    doctor_id=users["dr_wang"].id,
                    order_type="drug",
                    content_json={
                        **item.model_dump(exclude={"order_type"}),
                        "drug_name": db.get(Drug, code).name,
                    },
                    status="stopped" if index == STOPPED_ORDER_INDEX else "active",
                    validation_status=validation["status"],
                    validation_detail=validation["reasons"],
                )
            )
            counts["orders"] += 1

    if (patients["P20260002"].id, admission.id) not in present:
        pending = {
            "chief_complaint": "Palpitations for two weeks, worse at night.",
            "history": "Paroxysmal atrial fibrillation, permanent since 2021.",
            "diagnosis": "Atrial fibrillation, rate controlled",
            "temperature": 36.5,
            "note_date": (now - timedelta(days=1)).date().isoformat(),
            "severity": "moderate",
            "plan": "Continue rate control; review anticoagulation at the next visit.",
        }
        _record(
            db,
            users,
            patients["P20260002"],
            admission,
            "dr_wang",
            "pending",
            (
                (now - timedelta(days=1, hours=2), {**pending, "diagnosis": "Atrial fibrillation"}),
                (now - timedelta(days=1), pending),
            ),
        )
        counts["records"] += 1
        counts["versions"] += 2


def _meeting(db, users, patients, now, counts) -> None:
    """M5: a finished cross-department consultation, and its expired grant.

    The grant is deliberately expired rather than live. Flow 2's second step
    shows `dr_chen` getting a 404 for a patient outside his department *before*
    the invitation, and a valid grant left behind by this seeder would make that
    step pass for the wrong reason.
    """
    if db.scalar(select(Meeting.id).where(Meeting.title == MEETING_TITLE)) is not None:
        return
    scheduled = _previous_month(now)
    meeting = Meeting(
        patient_id=patients["P20260001"].id,
        initiator_id=users["dr_wang"].id,
        title=MEETING_TITLE,
        purpose=MEETING_PURPOSE,
        status="completed",
        scheduled_at=scheduled,
        started_at=scheduled + timedelta(minutes=5),
        completed_at=scheduled + timedelta(minutes=35),
        created_at=scheduled - timedelta(days=1),
    )
    db.add(meeting)
    db.flush()
    db.add(
        MeetingParticipant(
            meeting_id=meeting.id,
            user_id=users["dr_chen"].id,
            status="accepted",
            created_at=meeting.created_at,
        )
    )
    counts["participants"] += 1
    db.add(
        TempGrant(
            grantee_id=users["dr_chen"].id,
            patient_id=meeting.patient_id,
            # The wording the create route writes, so the grant list reads the
            # same whether a row came from the API or from here.
            reason=f"Remote consultation #{meeting.id}: {MEETING_PURPOSE[:400]}",
            granted_by=users["dr_wang"].id,
            expire_at=scheduled + timedelta(hours=24),
            is_valid=False,
            created_at=meeting.created_at,
        )
    )
    counts["grants"] += 1
    db.add(
        MeetingMaterial(
            meeting_id=meeting.id,
            filename=MATERIAL_FILENAME,
            stored_name=MATERIAL_STORED_NAME,
            content_type="application/pdf",
            size_bytes=len(_pdf_bytes("ECG sample - 2026-09-01")),
            uploaded_by=users["dr_wang"].id,
            uploaded_at=scheduled + timedelta(minutes=10),
        )
    )
    counts["materials"] += 1
    db.add(
        MeetingReport(
            meeting_id=meeting.id,
            expert_opinions=[
                {
                    "expert_id": users["dr_chen"].id,
                    "expert_name": users["dr_chen"].name,
                    "opinion": "Troponin negative and the ECG unchanged; continue the 20 mg dose.",
                },
                {
                    "expert_id": users["dr_li"].id,
                    "expert_name": users["dr_li"].name,
                    "opinion": "Agreed. Recheck the ECG before discharge and review in a month.",
                },
                {
                    "expert_id": users["dr_wang"].id,
                    "expert_name": users["dr_wang"].name,
                    "opinion": "The 80 mg order stays blocked until an allergy review is filed.",
                },
            ],
            conclusion="Continue furosemide 20 mg daily and repeat the ECG before discharge.",
            status="final",
            version=1,
            created_by=users["dr_wang"].id,
            created_at=scheduled + timedelta(minutes=40),
        )
    )
    counts["reports"] += 1
    counts["meetings"] += 1


def _health(db, users, patients, now, counts) -> None:
    """M6: the plan, its reminders, the readings and the assessment."""
    patient = patients["P20260001"]
    plan = db.scalar(
        select(HealthPlan).where(
            HealthPlan.patient_id == patient.id, HealthPlan.title == PLAN_TITLE
        )
    )
    if plan is None:
        plan = HealthPlan(
            patient_id=patient.id,
            title=PLAN_TITLE,
            goals=PLAN["goals"],
            instructions=PLAN["instructions"],
            # The stored shape `write_plan` produces, `done` included: the read
            # model requires all three keys.
            entries=[dict(entry) for entry in PLAN["entries"]],
            start_date=(now - timedelta(days=30)).date(),
            end_date=(now + timedelta(days=60)).date(),
            status="active",
            created_by=users["dr_wang"].id,
        )
        db.add(plan)
        db.flush()
        counts["plans"] += 1

    rules = []
    for rtype, title, cron_expr, active in REMINDER_RULES:
        rule = db.scalar(
            select(ReminderRule).where(
                ReminderRule.patient_id == patient.id, ReminderRule.title == title
            )
        )
        if rule is None:
            rule = ReminderRule(
                patient_id=patient.id,
                rtype=rtype,
                title=title,
                cron_expr=cron_expr,
                active=active,
                health_plan_id=plan.id,
                created_by=users["dr_wang"].id,
            )
            db.add(rule)
            db.flush()
            counts["rules"] += 1
        rules.append(rule)

    for index, days_ago, done, read in REMINDER_LOGS:
        rule = rules[index]
        # 09:00 UTC on the day in question: the instant the scheduler would have
        # written for a `0 9 * * *` rule.
        due = (now - timedelta(days=days_ago)).replace(hour=9, minute=0, second=0, microsecond=0)
        recorded = db.scalar(
            select(ReminderLog.id).where(ReminderLog.rule_id == rule.id, ReminderLog.due_at == due)
        )
        if recorded is not None:
            continue
        db.add(
            ReminderLog(
                rule_id=rule.id,
                patient_id=patient.id,
                # Copied from the rule at firing time, exactly as the job does.
                title=rule.title,
                due_at=due,
                fired_at=due + timedelta(seconds=3),
                done=done,
                done_at=due + timedelta(hours=2) if done else None,
                read=read,
            )
        )
        counts["logs"] += 1

    thresholds = {row.sign_type: row for row in db.scalars(select(VitalThreshold))}
    missing = {"bp", "gl", "hr"} - thresholds.keys()
    if missing:
        raise FlowError(
            f"No vital threshold is configured for {sorted(missing)}; migration a3d9e5f21c70 "
            "did not take effect."
        )
    for sign_type, series in (("bp", BP_SERIES), ("gl", GL_SERIES), ("hr", HR_SERIES)):
        threshold = thresholds[sign_type]
        for reading in series:
            days_ago, value = reading[0], reading[1]
            secondary = reading[2] if len(reading) > 2 else None
            recorded_at = (now - timedelta(days=days_ago)).replace(
                hour=0, minute=30, second=0, microsecond=0
            )
            recorded = db.scalar(
                select(VitalSign.id).where(
                    VitalSign.patient_id == patient.id,
                    VitalSign.sign_type == sign_type,
                    VitalSign.recorded_at == recorded_at,
                )
            )
            if recorded is not None:
                continue
            db.add(
                VitalSign(
                    patient_id=patient.id,
                    sign_type=sign_type,
                    value=float(value),
                    value_secondary=float(secondary) if secondary is not None else None,
                    unit=threshold.unit,
                    recorded_at=recorded_at,
                    source="manual",
                    # The server's own rule, so the stored flag and the flag a
                    # live reading would receive cannot disagree.
                    is_abnormal=_is_abnormal(threshold, float(value), secondary),
                    recorded_by=users["dr_wang"].id,
                )
            )
            counts["vitals"] += 1

    # The previous month, so the assessment the demonstration writes for the
    # current one is version 1 of a new period rather than version 2 of this.
    period = _previous_month(now).strftime("%Y-%m")
    assessment = db.scalar(
        select(HealthAssessment).where(
            HealthAssessment.patient_id == patient.id, HealthAssessment.period == period
        )
    )
    if assessment is None:
        db.add(
            HealthAssessment(
                patient_id=patient.id,
                period=period,
                conclusion=(
                    "Blood pressure is trending down, but one reading reached 160/100 mmHg; "
                    "the diuretic dose and the allergy flags were reviewed."
                ),
                plan_adjustment="Keep the 09:00 reminder and add a morning reading to the diary.",
                assessed_by=users["dr_li"].id,
                assessed_at=_previous_month(now),
            )
        )
        counts["assessments"] += 1


def seed_flow(settings: Settings | None = None) -> dict[str, int]:
    """Insert whatever of the full-flow baseline is missing; never overwrite.

    Additive for the same reason `app.seed_demo` is: a database that has been
    used for a demonstration is not a database to rewrite under the person
    using it. A second run against a seeded database adds nothing.
    """
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    upload_dir = Path(settings.upload_dir)
    counts = dict.fromkeys(COUNTERS, 0)
    try:
        with session_factory(engine)() as db:
            users, patients, departments = _resolve(db)
            now = datetime.now(UTC)
            _group(db, users, patients, departments, counts)
            _consultations(db, users, patients, now, counts)
            _records(db, users, patients, now, counts)
            _meeting(db, users, patients, now, counts)
            _health(db, users, patients, now, counts)
            db.commit()
            # The attachments are written after the commit and before the check:
            # a file has no rollback, and a row whose file is missing is the one
            # outcome worth avoiding. Writing them first also means the report
            # below describes the state the next run will see.
            files = write_files(upload_dir)
            problems = verify(db, upload_dir)
    finally:
        engine.dispose()

    print(f"Full-flow data ready: {sum(counts.values())} row(s) and {files} file(s) written.")
    for line in SUMMARY:
        print(line)
    if problems:
        print()
    report(problems)
    return counts


def _state_gaps(db) -> list[str]:
    """The states the three flows walk through that nothing in the database is in.

    A state can be missing while every count above is met, so this is checked by
    name: the review queue is empty when nothing is `pending`, however many
    records exist, and the workbench shows no room to accept when nothing is
    `waiting`.
    """
    gaps = []
    for model, column, wanted in (
        (Consultation, Consultation.status, ("waiting", "active", "ended")),
        (EmrRecord, EmrRecord.status, ("draft", "pending", "archived")),
    ):
        present = set(db.scalars(select(column)))
        gaps += [
            f"{model.__tablename__}: nothing is in state '{state}'"
            for state in wanted
            if state not in present
        ]
    return gaps


def verify(db, upload_dir: Path) -> list[str]:
    """Everything the flow baseline should have and does not.

    Read-only, so `--check` can run it against a database in use, and it reports
    a *shortfall* rather than inequality: this seeder's rows are a floor, and a
    demonstration that reviews the pending record, amends an archived one or
    creates a second consultation leaves the count above the baseline rather
    than below it. `scripts/build_db.py` checks exact counts against the fresh
    database it just built, which is the one place equality is the right test.
    """
    problems = []
    for model, expected in EXPECTED_COUNTS.items():
        found = db.scalar(select(func.count()).select_from(model))
        if found < expected:
            problems.append(f"{model.__tablename__}: {found} row(s), expected at least {expected}")
    # A count cannot see a slot someone else's row is sitting in. A demonstration
    # that filed its own draft for a patient satisfies `emr_record: 3` while
    # leaving the review queue empty, and `consultation: 3` says nothing about
    # whether one of them is still waiting. The states are what the flows use, so
    # they are checked by name.
    problems += _state_gaps(db)
    for name in SEEDED_FILES:
        if not (Path(upload_dir) / name).is_file():
            problems.append(f"the attachment {Path(upload_dir) / name} is missing")
    return problems


def report(problems: list[str]) -> None:
    if not problems:
        print("The full-flow baseline is complete.")
        return
    print("The full-flow baseline is incomplete:")
    for line in problems:
        print(f"  - {line}")
    # Not a blanket "run it again": a row a demonstration created in a slot the
    # baseline wanted is left exactly as it is, so a transcript or a record gap
    # behind one of those stays a gap however often this runs.
    print("Re-run `python -m app.seed_flow` to add what is missing, except where a")
    print("row already in place holds the slot -- that one is left alone.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed and check the full-flow baseline.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="report what is missing and exit 1; write nothing at all",
    )
    args = parser.parse_args(argv)
    settings = Settings()

    if args.check:
        engine = make_engine(settings.database_url)
        try:
            with session_factory(engine)() as db:
                _resolve(db)
                problems = verify(db, Path(settings.upload_dir))
        except FlowError as error:
            # The same report a missing baseline gets on the seeding path: the
            # message names the layer to run first.
            print(error)
            return 1
        finally:
            engine.dispose()
        report(problems)
        return 1 if problems else 0

    try:
        seed_flow(settings)
    except FlowError as error:
        print(error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
