"""`app.seed_flow` seeds the state the three demonstration flows start from.

The seeder exists so a freshly built database does not open on empty
workbenches, and it is additive for the same reason `app.seed_demo` is: a
database that has been used for a demonstration is not a database to rewrite
under the person using it. These tests hold both halves of that promise, plus
the three assumptions the scenario document makes about the seeded rows -- the
ended consultation is last month's, the leftover grant is already expired, and
the stored `is_abnormal` flag agrees with the threshold table.
"""

import contextlib
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from app.database import make_engine, session_factory
from app.emr_models import EmrRecord, EmrTemplate, EmrVersion, MedicalOrder
from app.health import _is_abnormal
from app.models import (
    HealthPlan,
    Meeting,
    Patient,
    ReminderLog,
    TempGrant,
    User,
    VitalSign,
    VitalThreshold,
)
from app.seed import seed
from app.seed_demo import main as demo_main
from app.seed_flow import (
    ACTIVE_CHAT,
    CHAT_SCRIPT,
    EXPECTED_COUNTS,
    SEEDED_FILES,
    main,
    seed_flow,
    verify,
)
from app.work_models import CallLog, Consultation, ConsultMessage, ImageUpload


@pytest.fixture
def database(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'flow.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    # Point the attachments at the test directory: the seeder writes real files,
    # and a test run must not leave them in the backend's upload directory.
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    command.upgrade(Config("alembic.ini"), "head")
    seed()
    assert demo_main([]) == 0
    return url


@pytest.fixture
def uploads(tmp_path):
    return tmp_path / "uploads"


@contextlib.contextmanager
def opened(url):
    engine = make_engine(url)
    try:
        with session_factory(engine)() as db:
            yield db
    finally:
        engine.dispose()


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_the_baseline_is_seeded_once_and_verifies_clean(database, uploads):
    assert main([]) == 0
    assert main([]) == 0  # Repeating it must not duplicate anything.
    with opened(database) as db:
        for model, expected in EXPECTED_COUNTS.items():
            assert count(db, model) == expected, model.__tablename__
        assert verify(db, uploads) == []
    assert main(["--check"]) == 0


def test_the_rows_counted_as_written_are_the_rows_the_baseline_promises(database):
    """The "N row(s) written" line and EXPECTED_COUNTS describe one database.

    A counter left out of the tally (the group's members, a meeting's material)
    makes the run report fewer rows than a reader finds, which reads as a seed
    that half-ran. Counting every row the baseline names keeps the two equal.
    """
    counts = seed_flow()
    assert sum(counts.values()) == sum(EXPECTED_COUNTS.values()), counts
    # And a second run has nothing to count: the total is rows added, not rows
    # that happen to exist.
    assert seed_flow() == dict.fromkeys(counts, 0)


def test_without_the_demo_baseline_it_stops_instead_of_half_seeding(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'bare.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    command.upgrade(Config("alembic.ini"), "head")
    seed()

    # Master data alone is not a demonstration baseline: there are no accounts
    # to attribute a consultation to, so the run stops rather than inventing one.
    assert main([]) == 1
    with opened(url) as db:
        assert count(db, Consultation) == 0
        assert count(db, User) == 0


def test_the_workbench_has_one_consultation_in_each_state(database):
    assert main([]) == 0
    with opened(database) as db:
        states = {row.status for row in db.scalars(select(Consultation))}
        assert states == {"waiting", "active", "ended"}
        waiting = db.scalar(select(Consultation).where(Consultation.status == "waiting"))
        # A waiting room has no reader but the department, so it carries no
        # attending physician and no transcript.
        assert waiting.doctor_id is None
        assert count(db, ConsultMessage) == len(CHAT_SCRIPT) + len(ACTIVE_CHAT) + 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(ConsultMessage)
                .where(ConsultMessage.consultation_id == waiting.id)
            )
            == 0
        )


def test_a_room_the_demonstration_created_is_left_alone(database):
    """Matching the identity triple is not licence to write into someone's room.

    The seeder matches a session by (patient, creator, state). If a
    demonstration has already opened a room under the same triple, attaching
    fifty scripted lines, an image and a call to it would be the opposite of the
    additive promise -- so the transcript and its attachments are written only
    alongside the session this run creates.
    """
    with opened(database) as db:
        patient = db.scalar(select(Patient).where(Patient.patient_no == "P20260001"))
        dr_wang = db.scalar(select(User).where(User.username == "dr_wang"))
        created = Consultation(
            patient_id=patient.id,
            created_by=dr_wang.id,
            doctor_id=dr_wang.id,
            status="ended",
            created_at=datetime.now(UTC),
        )
        db.add(created)
        db.commit()
        created_id = created.id

    assert main([]) == 0
    with opened(database) as db:
        for model in (ConsultMessage, CallLog, ImageUpload):
            attached = db.scalar(
                select(func.count()).select_from(model).where(model.consultation_id == created_id)
            )
            assert attached == 0, model.__tablename__


def test_a_state_someone_else_s_own_record_took_is_reported(database, uploads):
    """Counting rows cannot see this, which is exactly why it is checked.

    A demonstration that filed its own admission note for P20260002 holds the
    slot the baseline wanted for the pending record. The count still comes to
    three, so a count-only check calls the baseline clean while `/review` opens
    with nothing to review.
    """
    with opened(database) as db:
        patient = db.scalar(select(Patient).where(Patient.patient_no == "P20260002"))
        template = db.scalar(select(EmrTemplate).where(EmrTemplate.name == "Admission note"))
        author = db.scalar(select(User).where(User.username == "dr_wang"))
        db.add(
            EmrRecord(
                patient_id=patient.id,
                template_id=template.id,
                template_snapshot={},
                author_id=author.id,
                content_json={},
                status="draft",
                version=1,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        db.commit()

    assert main([]) == 0
    with opened(database) as db:
        assert count(db, EmrRecord) == 3  # The count the baseline asks for.
        problems = verify(db, uploads)
    assert any("'pending'" in line for line in problems), problems


def test_the_recorded_call_matches_the_sixty_second_baseline(database):
    """§4.4 pins the baseline call at 60 seconds, which S3 replays.

    `duration_seconds` is what the runtime derives from the two instants
    (`app.calls`), so it is derived here the same way -- a stored number that
    disagreed with its own timestamps would make the playback page and the call
    log disagree.
    """
    assert main([]) == 0
    with opened(database) as db:
        call = db.scalar(select(CallLog))
        assert call.end_reason == "hangup"
        assert call.duration_seconds == 60
        assert int((call.ended_at - call.connected_at).total_seconds()) == call.duration_seconds
        assert call.started_at <= call.connected_at <= call.ended_at


def test_the_ended_consultation_is_last_month_so_the_month_filter_stays_true(database):
    """M3-T9 filters by "this month" and expects the consultation created live.

    A seeded session dated inside the current month would make that step pass
    with two hits instead of one, so the history is kept in the previous month
    however late in the month the database is built.
    """
    assert main([]) == 0
    with opened(database) as db:
        ended = db.scalar(select(Consultation).where(Consultation.status == "ended"))
        assert ended.created_at.strftime("%Y-%m") != datetime.now(UTC).strftime("%Y-%m")
        archived = db.scalar(select(EmrRecord).where(EmrRecord.status == "archived"))
        assert archived.created_at.strftime("%Y-%m") != datetime.now(UTC).strftime("%Y-%m")
        meeting = db.scalar(select(Meeting))
        assert meeting.scheduled_at.strftime("%Y-%m") != datetime.now(UTC).strftime("%Y-%m")


def test_the_review_queue_covers_all_three_record_states(database):
    assert main([]) == 0
    with opened(database) as db:
        states = sorted(row.status for row in db.scalars(select(EmrRecord)))
        assert states == ["archived", "draft", "pending"]
        archived = db.scalar(select(EmrRecord).where(EmrRecord.status == "archived"))
        # Three versions with exactly one reviewer, which is what the history
        # panel walks: v1 frozen on first submission, then the amendment.
        assert archived.version == 3
        assert archived.reviewer_id is not None
        assert (
            db.scalar(
                select(func.count())
                .select_from(EmrVersion)
                .where(EmrVersion.record_id == archived.id)
            )
            == archived.version
        )
        # The pending record is the one a senior opens and reviews.
        pending = db.scalar(select(EmrRecord).where(EmrRecord.status == "pending"))
        assert pending.submitted_at is not None
        assert pending.reviewer_id is None


def test_the_seeded_orders_cover_pass_warn_and_stop(database):
    assert main([]) == 0
    with opened(database) as db:
        rows = db.scalars(select(MedicalOrder).order_by(MedicalOrder.id)).all()
        assert [row.validation_status for row in rows] == ["passed", "warning", "passed"]
        assert [row.status for row in rows] == ["active", "active", "stopped"]
        # The reasons are the ones app.emr_validation produces, not a paraphrase.
        warning = rows[1]
        assert [reason["kind"] for reason in warning.validation_detail] == ["dose"]
        assert warning.validation_detail[0]["normal_range"] == "20-40mg/day"
        # A blocked order is never stored; the flow's blocked attempt is the one
        # the demonstration performs live (M4-T14).
        assert all(row.validation_status != "blocked" for row in rows)


def test_the_leftover_grant_is_expired_so_the_pre_invitation_404_holds(database):
    """Flow 2 step 2 needs dr_chen to see a 404 *before* the invitation.

    A valid grant left behind by the seeder would make that step pass for the
    wrong reason, so the meeting's grant is written already expired.
    """
    assert main([]) == 0
    with opened(database) as db:
        grant = db.scalar(select(TempGrant))
        assert grant.is_valid is False
        assert grant.expire_at.replace(tzinfo=UTC) < datetime.now(UTC)


def test_the_dashboard_has_one_unread_reminder(database):
    assert main([]) == 0
    with opened(database) as db:
        unread = db.scalar(
            select(func.count()).select_from(ReminderLog).where(ReminderLog.read.is_(False))
        )
        assert unread == 1
        assert count(db, ReminderLog) == 3


def test_a_seeded_reading_agrees_with_the_threshold_table(database):
    """The stored flag and the server's rule must not disagree.

    A reading the chart draws as normal while the API would call it abnormal is
    worse than a missing reading, so the seeder runs `app.health._is_abnormal`
    rather than copying its answer.
    """
    assert main([]) == 0
    with opened(database) as db:
        thresholds = {row.sign_type: row for row in db.scalars(select(VitalThreshold))}
        readings = db.scalars(select(VitalSign)).all()
        assert readings
        for row in readings:
            expected = _is_abnormal(thresholds[row.sign_type], row.value, row.value_secondary)
            assert row.is_abnormal is expected, (row.sign_type, row.value)
        # The 160/100 reading M6-T4 hovers over is abnormal; the ordinary
        # readings around it are not, or the chart's red point proves nothing.
        systolic = [row for row in readings if row.sign_type == "bp"]
        assert [row.is_abnormal for row in systolic].count(True) == 1
        abnormal = next(row for row in systolic if row.is_abnormal)
        assert (abnormal.value, abnormal.value_secondary) == (160.0, 100.0)


def test_the_attachments_are_real_files_under_the_upload_directory(database, uploads):
    assert main([]) == 0
    for name in SEEDED_FILES:
        payload = (uploads / name).read_bytes()
        assert payload, name
    # M5-T4 downloads the material and opens it; a placeholder would be a blank
    # page there, so the PDF has to be a PDF.
    assert (uploads / SEEDED_FILES[1]).read_bytes().startswith(b"%PDF")
    assert (uploads / SEEDED_FILES[0]).read_bytes().startswith(b"\x89PNG")


def test_a_deleted_attachment_is_reported_and_written_again(database, uploads):
    assert main([]) == 0
    (uploads / SEEDED_FILES[0]).unlink()
    with opened(database) as db:
        assert any("missing" in line for line in verify(db, uploads))
    assert main(["--check"]) == 1

    # A row whose file is gone is half a pair, which is the one outcome the
    # additive path repairs rather than preserves.
    assert main([]) == 0
    with opened(database) as db:
        assert verify(db, uploads) == []


def test_a_used_database_is_never_rewritten(database):
    assert main([]) == 0
    with opened(database) as db:
        plan = db.scalar(select(HealthPlan))
        plan.goals = "Edited during a demonstration."
        db.commit()

    assert main([]) == 0
    with opened(database) as db:
        assert db.scalar(select(HealthPlan.goals)) == "Edited during a demonstration."
        assert count(db, HealthPlan) == 1


def test_the_seeder_never_adds_accounts_or_patients(database):
    """The contract scripts/build_db.py verifies has to survive this layer."""
    with opened(database) as db:
        assert (count(db, User), count(db, Patient)) == (4, 3)

    assert main([]) == 0
    with opened(database) as db:
        assert (count(db, User), count(db, Patient)) == (4, 3)
