"""M6: vitals, health plans, reminder rules and their log, assessments.

The suite is organised around the claims that would fail silently rather than
loudly. A threshold applied to only half a blood pressure, a trend range whose
last day is dropped, a reminder written twice because the job ran twice -- none
of those raise, they just produce wrong data quietly. Everything else here is
plumbing.
"""

from datetime import UTC, date, datetime, timedelta

import fakeredis
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import hash_password, issue_token
from app.config import Settings
from app.health import generate_reminders
from app.main import create_app
from app.models import (
    AuditLog,
    Department,
    ReminderLog,
    Role,
    User,
)
from app.seed import seed

TODAY = date(2026, 9, 18)
YESTERDAY = datetime.now(UTC) - timedelta(days=1)


@pytest.fixture
def client(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'health.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    seed()
    app = create_app(
        Settings(database_url=url, redis_url=None, scheduler_enabled=False, _env_file=None)
    )
    app.state.cache = fakeredis.FakeRedis()
    with app.state.sessions() as db:
        roles = {r.name: r.id for r in db.scalars(select(Role))}
        departments = list(db.scalars(select(Department).order_by(Department.id)))
        for index, (name, role, dept) in enumerate(
            [
                ("admin", "admin", 0),
                ("senior", "senior", 0),
                ("junior", "junior", 1),
                ("outsider", "senior", 1),
            ],
            1,
        ):
            db.add(
                User(
                    id=index,
                    username=name,
                    name=name,
                    email=f"{name}@example.test",
                    password_hash=hash_password("test-password"),
                    role_id=roles[role],
                    department_id=departments[dept].id,
                )
            )
        db.commit()
    with TestClient(app) as client:
        yield client


def headers(client, user_id=1):
    with client.app.state.sessions() as db:
        token = issue_token(db.get(User, user_id), client.app.state.settings.jwt_secret)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def patient_no(client):
    """A patient in Information Technology: visible to admin (1) and senior (2),
    out of scope for junior (3) and outsider (4), who are in Cardiology."""
    response = client.post(
        "/api/patients",
        json={"name": "Zhang Wei", "gender": "male", "department": "Information Technology"},
        headers=headers(client),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["patient_no"]


def record(client, patient_no, **overrides):
    body = {
        "sign_type": "bp",
        "value": 120,
        "value_secondary": 80,
        "recorded_at": YESTERDAY.isoformat(),
    }
    body.update(overrides)
    return client.post(f"/api/patients/{patient_no}/vitals", json=body, headers=headers(client))


# ------------------------------------------------------------------- vitals


def test_systolic_and_diastolic_are_both_judged(client, patient_no):
    """A normal systolic with a high diastolic is abnormal.

    The case a single-value check misses, and the reason `vital_thresholds`
    carries four numbers for `bp` instead of two.
    """
    high_bottom = record(client, patient_no, value=120, value_secondary=95)
    assert high_bottom.status_code == 200, high_bottom.text
    assert high_bottom.json()["data"]["is_abnormal"] is True

    high_top = record(client, patient_no, value=160, value_secondary=80)
    assert high_top.json()["data"]["is_abnormal"] is True

    normal = record(client, patient_no, value=118, value_secondary=76)
    assert normal.json()["data"]["is_abnormal"] is False


def test_glucose_and_heart_rate_use_their_own_thresholds(client, patient_no):
    """Each sign is judged against its own row, not against blood pressure's."""
    glucose = record(client, patient_no, sign_type="gl", value=9.4, value_secondary=None)
    assert glucose.json()["data"]["is_abnormal"] is True
    assert glucose.json()["data"]["unit"] == "mmol/L"

    heart_rate = record(client, patient_no, sign_type="hr", value=72, value_secondary=None)
    assert heart_rate.json()["data"]["is_abnormal"] is False
    assert heart_rate.json()["data"]["unit"] == "bpm"


def test_a_future_reading_is_refused_and_named(client, patient_no):
    """T33 scenario S2 submits a future timestamp and requires a 422."""
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    response = record(client, patient_no, recorded_at=tomorrow.isoformat())
    assert response.status_code == 422
    assert "recorded_at" in response.json()["message"]


def test_a_blood_pressure_without_its_second_value_is_refused(client, patient_no):
    response = record(client, patient_no, value_secondary=None)
    assert response.status_code == 422
    assert "value_secondary" in response.json()["message"]


def test_non_numeric_and_unknown_sign_types_are_refused(client, patient_no):
    assert record(client, patient_no, value="abc").status_code == 422
    # `weight` is not in the enum: M6's criteria say the three are bp/gl/hr.
    assert record(client, patient_no, sign_type="weight").status_code == 422


def test_the_recording_is_attributed_to_its_author(client, patient_no):
    """The audit middleware names the actor from `request.state.identity`, which
    only this module's own dependency sets. Without it the row would say a
    reading was recorded but not by whom."""
    assert record(client, patient_no).status_code == 200
    with client.app.state.sessions() as db:
        row = db.scalar(select(AuditLog).where(AuditLog.action == "vital.create"))
    assert row is not None
    assert row.username == "admin"
    assert row.patient_id is not None


def test_a_patient_outside_the_department_is_a_404(client, patient_no):
    """403 and 404 are not interchangeable: outside the scope the object does not
    exist for this caller, and saying "forbidden" would confirm it does."""
    for user_id in (3, 4):
        response = client.get(
            f"/api/patients/{patient_no}/vitals", headers=headers(client, user_id)
        )
        assert response.status_code == 404, response.text


def test_the_list_is_newest_first_and_filters_by_sign(client, patient_no):
    record(client, patient_no, value=118, value_secondary=76)
    record(client, patient_no, sign_type="gl", value=5.2, value_secondary=None)
    response = client.get(
        f"/api/patients/{patient_no}/vitals?sign_type=bp", headers=headers(client)
    )
    body = response.json()["data"]
    assert body["total"] == 1
    assert body["items"][0]["sign_type"] == "bp"


# -------------------------------------------------------------------- trend


def test_the_trend_carries_the_threshold_for_both_halves(client, patient_no):
    """T34 scenario S1's tooltip has to read "160/100 mmHg（超出阈值 140/90）",
    so a point must be able to produce the secondary bound too."""
    record(client, patient_no, value=160, value_secondary=100)
    response = client.get(
        f"/api/patients/{patient_no}/vitals/trend"
        f"?sign_type=bp&from={TODAY - timedelta(days=7)}&to={TODAY}",
        headers=headers(client),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["threshold"]["max"] == 139
    assert data["threshold"]["max_secondary"] == 89
    point = data["points"][0]
    assert point["is_abnormal"] is True
    assert point["value_secondary"] == 100
    assert point["threshold"]["max_secondary"] == 89


def test_an_empty_range_is_an_empty_list_not_a_blank_chart(client, patient_no):
    response = client.get(
        f"/api/patients/{patient_no}/vitals/trend"
        f"?sign_type=hr&from={TODAY - timedelta(days=7)}&to={TODAY}",
        headers=headers(client),
    )
    assert response.json()["data"]["points"] == []


def test_the_trend_range_includes_its_last_day(client, patient_no):
    """`to` is a date, so it has to cover the whole day. Comparing against
    midnight would silently drop everything recorded on the day the user picked
    -- a filter that looks like it works and loses the newest reading."""
    # Just inside the current hour, so it is both today (UTC) and in the past.
    recorded = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    record(
        client,
        patient_no,
        sign_type="hr",
        value=71,
        value_secondary=None,
        recorded_at=recorded.isoformat(),
    )
    today = recorded.date()
    response = client.get(
        f"/api/patients/{patient_no}/vitals/trend?sign_type=hr&from={today}&to={today}",
        headers=headers(client),
    )
    assert len(response.json()["data"]["points"]) == 1


# ------------------------------------------------------------- health plans


def plan_body(patient_no, **overrides):
    body = {
        "patient_no": patient_no,
        "title": "Blood pressure management plan",
        "goals": "Keep the systolic under 139",
        "entries": [{"kind": "medication", "text": "Amlodipine 5mg once daily"}],
        "start_date": str(TODAY),
        "end_date": str(TODAY + timedelta(days=30)),
    }
    body.update(overrides)
    return body


def test_a_plan_can_create_its_reminder_rules_in_the_same_call(client, patient_no):
    """Scenario S1 ticks "daily 09:00 medication reminder" on the plan form and
    then finds the matching rule in the T36 list."""
    response = client.post(
        "/api/health-plans",
        json=plan_body(
            patient_no,
            new_reminder_rules=[
                {
                    "patient_no": patient_no,
                    "rtype": "medication",
                    "title": "Daily 09:00 medication reminder",
                    "cron_expr": "0 9 * * *",
                }
            ],
        ),
        headers=headers(client),
    )
    assert response.status_code == 200, response.text
    plan = response.json()["data"]
    assert len(plan["reminder_rule_ids"]) == 1

    rules = client.get(
        f"/api/reminder-rules?patient_no={patient_no}", headers=headers(client)
    ).json()["data"]
    assert rules[0]["health_plan_id"] == plan["id"]
    assert rules[0]["active"] is True


def test_an_end_date_before_the_start_is_a_422_naming_the_field(client, patient_no):
    response = client.post(
        "/api/health-plans",
        json=plan_body(patient_no, end_date=str(TODAY - timedelta(days=1))),
        headers=headers(client),
    )
    assert response.status_code == 422
    assert "end_date" in response.json()["message"]


def test_a_plan_for_another_department_is_a_404(client, patient_no):
    response = client.post(
        "/api/health-plans", json=plan_body(patient_no), headers=headers(client, 4)
    )
    assert response.status_code == 404


def test_a_status_change_is_audited(client, patient_no):
    plan = client.post(
        "/api/health-plans", json=plan_body(patient_no), headers=headers(client)
    ).json()["data"]
    response = client.patch(
        f"/api/health-plans/{plan['id']}",
        json=plan_body(patient_no, status="completed"),
        headers=headers(client),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "completed"
    with client.app.state.sessions() as db:
        row = db.scalar(select(AuditLog).where(AuditLog.action == "health_plan.update"))
    assert row.detail["status_from"] == "active"
    assert row.detail["status_to"] == "completed"


def test_a_plan_cannot_be_moved_to_another_patient(client, patient_no):
    """The PATCH body carries `patient_no`, per the contract. It is checked, not
    applied: retargeting would move a record out of its department."""
    plan = client.post(
        "/api/health-plans", json=plan_body(patient_no), headers=headers(client)
    ).json()["data"]
    response = client.patch(
        f"/api/health-plans/{plan['id']}",
        json=plan_body("P20269999"),
        headers=headers(client),
    )
    assert response.status_code == 404


# ----------------------------------------------------------------- reminders


def make_rule(client, patient_no, **overrides):
    body = {
        "patient_no": patient_no,
        "rtype": "checkin",
        "title": "Weekly check-in",
        "cron_expr": "0 9 * * 1",
    }
    body.update(overrides)
    return client.post("/api/reminder-rules", json=body, headers=headers(client))


def test_a_rule_is_deactivated_by_a_partial_body(client, patient_no):
    """T36 §4 and scenario S2: `{"active": false}` on its own is a complete
    request."""
    rule = make_rule(client, patient_no).json()["data"]
    response = client.patch(
        f"/api/reminder-rules/{rule['id']}", json={"active": False}, headers=headers(client)
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["active"] is False
    # Untouched fields survive: the body was partial, not a replacement.
    assert response.json()["data"]["cron_expr"] == rule["cron_expr"]


def test_a_malformed_cron_is_refused_at_write_time(client, patient_no):
    """Stored happily, it would generate nothing forever and the failure would
    only show up as an empty reminder list during the demonstration."""
    response = make_rule(client, patient_no, cron_expr="not a cron")
    assert response.status_code == 422
    assert "cron_expr" in response.json()["message"]


def test_generation_is_idempotent_and_a_restart_adds_nothing(client, patient_no):
    """T36 scenario S2 restarts twice and requires no duplicates. The job is
    called three times over the same minute, which is what a restart does."""
    make_rule(client, patient_no, cron_expr="* * * * *")
    with client.app.state.sessions() as db:
        # Two calls, no restart, the same minute.
        generate_reminders(client.app.state.sessions)
        generate_reminders(client.app.state.sessions)
        assert db.scalar(select(ReminderLog.id)) is not None
        count = len(list(db.scalars(select(ReminderLog.id))))
    assert count == 1


def test_an_inactive_rule_generates_nothing_new(client, patient_no):
    rule = make_rule(client, patient_no, cron_expr="* * * * *").json()["data"]
    client.patch(
        f"/api/reminder-rules/{rule['id']}", json={"active": False}, headers=headers(client)
    )
    generate_reminders(client.app.state.sessions)
    with client.app.state.sessions() as db:
        assert list(db.scalars(select(ReminderLog.id))) == []


def test_opening_the_list_clears_the_red_dot(client, patient_no):
    """Criterion 2: the dot is driven by unread entries, and reading the list is
    what clears them."""
    make_rule(client, patient_no, cron_expr="* * * * *")
    generate_reminders(client.app.state.sessions)

    before = client.get("/api/reminders/unread-count", headers=headers(client)).json()["data"]
    assert before["unread"] == 1

    listed = client.get("/api/reminders", headers=headers(client)).json()["data"]
    assert listed["total"] == 1
    # The count comes back with the list, so the shell reads one response rather
    # than two, and it is the post-clear number: the dot is not left lit over a
    # list the user is looking at.
    assert listed["unread"] == 0
    after = client.get("/api/reminders/unread-count", headers=headers(client)).json()["data"]
    assert after["unread"] == 0


def test_unread_only_does_not_consume_the_dot(client, patient_no):
    make_rule(client, patient_no, cron_expr="* * * * *")
    generate_reminders(client.app.state.sessions)
    listed = client.get("/api/reminders?unread_only=true", headers=headers(client)).json()["data"]
    assert listed["total"] == 1
    assert listed["unread"] == 1


def test_a_reminder_can_be_marked_done(client, patient_no):
    make_rule(client, patient_no, cron_expr="* * * * *")
    generate_reminders(client.app.state.sessions)
    entry = client.get("/api/reminders", headers=headers(client)).json()["data"]["items"][0]
    response = client.post(f"/api/reminders/{entry['id']}/done", headers=headers(client))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["done"] is True
    assert response.json()["data"]["done_at"] is not None


def test_a_fired_reminder_keeps_the_title_it_fired_with(client, patient_no):
    """Editing a rule later must not rewrite what the reminder said."""
    rule = make_rule(client, patient_no, cron_expr="* * * * *").json()["data"]
    generate_reminders(client.app.state.sessions)
    client.patch(
        f"/api/reminder-rules/{rule['id']}",
        json={"title": "Renamed after firing"},
        headers=headers(client),
    )
    with client.app.state.sessions() as db:
        log = db.scalar(select(ReminderLog))
    assert log.title == "Weekly check-in"


# --------------------------------------------------------------- assessments


def assessment(client, patient_no, **overrides):
    body = {"period": "2026-08", "conclusion": "Blood pressure is not well controlled."}
    body.update(overrides)
    return client.post(
        f"/api/patients/{patient_no}/assessments", json=body, headers=headers(client)
    )


def test_a_revision_is_a_new_row_and_the_original_stays_readable(client, patient_no):
    """T37: a revision does not overwrite the original in place, so the earlier
    conclusion stays readable exactly as it was written."""
    original = assessment(client, patient_no).json()["data"]
    revised = client.patch(
        f"/api/assessments/{original['id']}",
        json={"period": "2026-08", "conclusion": "Add an ACE inhibitor and recheck."},
        headers=headers(client),
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["data"]["version"] == 2
    assert revised.json()["data"]["updated_at"] is not None

    again = client.get(f"/api/assessments/{original['id']}", headers=headers(client))
    assert again.json()["data"]["conclusion"] == "Blood pressure is not well controlled."
    assert again.json()["data"]["version"] == 1

    listed = client.get(f"/api/patients/{patient_no}/assessments", headers=headers(client)).json()[
        "data"
    ]
    assert [row["version"] for row in listed] == [2, 1]


def test_only_the_assessing_physician_may_revise(client, patient_no):
    """T37 scenario S2 has a second physician attempt it and requires 403."""
    original = assessment(client, patient_no).json()["data"]
    response = client.patch(
        f"/api/assessments/{original['id']}",
        json={"period": "2026-08", "conclusion": "Someone else's opinion."},
        headers=headers(client, 2),
    )
    assert response.status_code == 403


def test_the_period_must_be_a_calendar_month(client, patient_no):
    assert assessment(client, patient_no, period="2026-13").status_code == 422
    assert assessment(client, patient_no, period="August").status_code == 422


def test_an_empty_conclusion_is_refused_by_the_server(client, patient_no):
    response = assessment(client, patient_no, conclusion="")
    assert response.status_code == 422
    assert "conclusion" in response.json()["message"]


def test_a_future_assessment_date_is_refused(client, patient_no):
    response = assessment(
        client, patient_no, assessed_at=(datetime.now(UTC) + timedelta(days=1)).isoformat()
    )
    assert response.status_code == 422
    assert "assessed_at" in response.json()["message"]


def test_an_assessment_outside_the_department_is_a_404(client, patient_no):
    created = assessment(client, patient_no).json()["data"]
    assert (
        client.get(f"/api/assessments/{created['id']}", headers=headers(client, 4)).status_code
        == 404
    )


# ------------------------------------------------------------------- access


def test_every_health_route_refuses_an_anonymous_caller(client, patient_no):
    """Default-protected: none of these paths are on the anonymous allowlist."""
    for path in (
        "/api/health-plans",
        f"/api/patients/{patient_no}/vitals",
        f"/api/patients/{patient_no}/vitals/trend?sign_type=bp&from=2026-09-01&to=2026-09-18",
        "/api/reminder-rules",
        "/api/reminders",
        "/api/reminders/unread-count",
        f"/api/patients/{patient_no}/assessments",
    ):
        assert client.get(path).status_code == 401, path
