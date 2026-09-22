"""Dashboard (工作台) 功能验证.

The workbench is the first screen after login and the only screen that reads four
endpoints at once, so a drift in any one of them shows up here first. This file
pins the field names the page indexes -- it reads `count.unread`, so a response
that spells the same fact `unread_count` is a broken dashboard, not a typo -- and
the two promises `docs/演示脚本-端到端.md` makes about the red dot: drawing the
panel does not acknowledge a reminder, opening the patient's ordinary list does.

Scope is the data contract, not the pixels. The rendering is verified in the
browser per the demonstration script; this is the half that runs without Docker.
"""

import fakeredis
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import issue_token
from app.config import Settings
from app.main import create_app
from app.models import User
from app.seed import seed
from app.seed_demo import main as seed_accounts
from app.seed_flow import main as seed_clinical_state


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A database in the state the demonstration opens on: the four accounts,
    the three patients, and the clinical rows the panels summarise."""
    url = f"sqlite:///{tmp_path / 'dashboard.db'}"
    uploads = tmp_path / "uploads"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("UPLOAD_DIR", str(uploads))
    command.upgrade(Config("alembic.ini"), "head")
    seed()
    assert seed_accounts([]) == 0
    assert seed_clinical_state([]) == 0
    app = create_app(
        Settings(
            database_url=url,
            redis_url=None,
            scheduler_enabled=False,
            upload_dir=str(uploads),
            _env_file=None,
        )
    )
    app.state.cache = fakeredis.FakeRedis()
    with TestClient(app) as client:
        yield client


def auth(client, username):
    """The token the browser holds once the SMS step has been answered."""
    with client.app.state.sessions() as db:
        user = db.scalar(select(User).where(User.username == username))
        assert user is not None, f"{username} is not in the demo cast"
        token = issue_token(user, client.app.state.settings.jwt_secret)
    return {"Authorization": f"Bearer {token}"}


def payload(response):
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0, body
    return body["data"]


def missing(actual, expected):
    return set(expected) - set(actual)


def test_the_workbench_opens_on_the_demo_account(client):
    """演示脚本 step 1: the page's header reads this payload."""
    me = payload(client.get("/api/me", headers=auth(client, "dr_wang")))
    assert me["username"] == "dr_wang"
    assert me["title"] == "junior"
    assert me["department"] == "Cardiology"
    assert not missing(me, ["id", "username", "name", "title", "department"])


def test_the_bell_has_the_one_seeded_unread_reminder(client):
    """The demonstration opens with the bell showing 1."""
    headers = auth(client, "dr_wang")
    count = payload(client.get("/api/reminders/unread-count", headers=headers))
    assert count["unread"] == 1, count

    page = payload(client.get("/api/reminders?unread_only=true&size=5", headers=headers))
    assert page["total"] == 1, page
    reminder = page["items"][0]
    assert not missing(reminder, ["id", "title", "patient_no", "due_at"]), reminder
    assert reminder["patient_no"] == "P20260001"


def test_looking_at_the_dashboard_does_not_clear_the_dot(client):
    """M6-T6: the panel asks for `unread_only`, so drawing it acknowledges
    nothing. Two passes leave the count where they found it."""
    headers = auth(client, "dr_wang")
    for _ in range(2):
        page = payload(client.get("/api/reminders?unread_only=true&size=5", headers=headers))
        assert page["total"] == 1
        count = payload(client.get("/api/reminders/unread-count", headers=headers))
        assert count["unread"] == 1


def test_opening_the_patients_reminder_list_clears_the_dot(client):
    """... and the ordinary list is the reader that consumes it."""
    headers = auth(client, "dr_wang")
    ordinary = payload(client.get("/api/reminders?page=1&size=20", headers=headers))
    assert ordinary["items"], ordinary
    assert ordinary["unread"] == 0, ordinary
    count = payload(client.get("/api/reminders/unread-count", headers=headers))
    assert count["unread"] == 0


def test_the_panels_get_the_shapes_the_page_indexes(client):
    """Every attribute the template touches, checked against the service."""
    headers = auth(client, "dr_wang")

    meetings = payload(client.get("/api/meetings?page=1&size=50", headers=headers))
    assert not missing(meetings, ["items", "total"]), meetings
    assert meetings["total"] >= 1, meetings
    meeting = meetings["items"][0]
    assert not missing(
        meeting,
        [
            "id",
            "patient_no",
            "status",
            "scheduled_at",
            "initiator_name",
            "initiator_id",
            "participants",
        ],
    ), meeting
    assert not missing(meeting["participants"][0], ["user_id", "status", "name"]), meeting

    patients = payload(client.get("/api/patients?page=1&size=100", headers=headers))
    assert not missing(patients, ["items", "total"]), patients
    assert patients["total"] >= 1, patients
    assert not missing(patients["items"][0], ["patient_no", "name"]), patients["items"][0]


def test_the_screen_the_messages_panel_points_at_answers(client):
    """The panel sends the reader to the consultation screen, so that screen has
    to have something to show: M3 seeds one room per state."""
    headers = auth(client, "dr_wang")
    rooms = payload(client.get("/api/consultations?page=1&size=20", headers=headers))
    assert not missing(rooms, ["items", "total"]), rooms
    assert {room["status"] for room in rooms["items"]} == {"waiting", "active", "ended"}, rooms
