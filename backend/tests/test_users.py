"""M1-07 acceptance: the directory, administrator CRUD and the role dictionary.

This module also carries the acceptance test M5's invite picker lost when its
private `/api/meetings/doctors` route was retired: the picker reads
`GET /api/users?status=active` now, and that read is the reason the list route is
open to any authenticated caller while every write stays administrator-only.

The cast is `test_auth_grants`'s: 1 = admin, 2 = senior, 3 = junior, 4 = outsider,
with 3 and 4 both in Cardiology and 1 and 2 in Information Technology.
"""

import json
from datetime import datetime

from sqlalchemy import select
from test_auth_grants import client as auth_client
from test_auth_grants import headers

from app.auth import hash_password, verify_password
from app.models import AuditLog, Department, Role, User
from app.security import PERMISSIONS

client = auth_client

# What a caller without `user.manage` gets, and what an administrator adds.
DIRECTORY_FIELDS = {"id", "username", "name", "title", "department"}
FULL_FIELDS = DIRECTORY_FIELDS | {"email", "status", "created_at"}

NEW_USER = {
    "username": "dr_new",
    "password": "correct-horse",
    "name": "New Doctor",
    "email": "new@example.test",
    "title": "junior",
    "department": "Cardiology",
}


def add_user(client, username, title, department, **overrides):
    """Insert an account the `test_auth_grants` cast does not have."""

    with client.app.state.sessions() as db:
        roles = {row.name: row.id for row in db.scalars(select(Role))}
        departments = {row.name: row.id for row in db.scalars(select(Department))}
        db.add(
            User(
                username=username,
                name=overrides.pop("name", username),
                email=f"{username}@example.test",
                password_hash=hash_password("test-password"),
                role_id=roles[title],
                department_id=departments[department],
                **overrides,
            )
        )
        db.commit()


def directory(client, user_id=1, **params):
    response = client.get("/api/users", params=params, headers=headers(client, user_id))
    assert response.status_code == 200, response.text
    return response.json()["data"]


def names(data):
    return [row["name"] for row in data["items"]]


def stored(client, user_id):
    """The live row, so a test can see what the API actually wrote."""

    with client.app.state.sessions() as db:
        row = db.get(User, user_id)
        return row.name, row.status, row.role.name, row.department.name


def test_the_directory_is_readable_by_anyone_signed_in(client):
    for path in ("/api/users", "/api/users/1", "/api/roles"):
        assert client.get(path).status_code == 401

    response = client.get("/api/users", headers=headers(client, 3))
    assert response.status_code == 200
    body = response.json()["data"]
    assert {row["username"] for row in body["items"]} == {"admin", "senior", "junior", "outsider"}
    assert all(set(row) == DIRECTORY_FIELDS for row in body["items"])
    # Absent, not null: `response_model_exclude_none` on the route.
    assert "email" not in response.text and "created_at" not in response.text

    # The same route, one permission level up, carries the contact fields.
    admin = directory(client, 1)
    assert set(admin["items"][0]) == FULL_FIELDS
    assert set(admin["items"][0]) - DIRECTORY_FIELDS == {"email", "status", "created_at"}
    assert datetime.fromisoformat(admin["items"][0]["created_at"]).tzinfo is not None


def test_the_detail_read_and_the_writes_stay_administrator_only(client):
    for user_id in (2, 3):
        auth = headers(client, user_id)
        assert client.get("/api/users/1", headers=auth).status_code == 403
        assert client.post("/api/users", json=NEW_USER, headers=auth).status_code == 403
        assert (
            client.patch("/api/users/1", json={"name": "hijacked"}, headers=auth).status_code == 403
        )
        assert client.get("/api/users/1", headers=auth).json()["message"] == (
            "Missing permission: user.manage"
        )

    with client.app.state.sessions() as db:
        assert len(list(db.scalars(select(User.id)))) == 4
    assert stored(client, 1)[0] == "admin"


def test_a_disabled_account_is_refused_while_its_token_is_still_valid(client):
    auth = headers(client, 3)
    assert client.get("/api/users", headers=auth).status_code == 200
    with client.app.state.sessions() as db:
        db.get(User, 3).status = "disabled"
        db.commit()
    assert client.get("/api/users", headers=auth).status_code == 401


def test_the_directory_still_feeds_the_invite_picker(client):
    """The M5 migration, moved here from `test_meetings.py`.

    The picker's operator is a *junior*, and the expert it has to offer is in
    another department -- that pair is the whole reason this route is not
    administrator-only and not department-scoped.
    """
    assert client.get("/api/users", params={"status": "active"}).status_code == 401
    add_user(client, "dr_chen", "senior", "Neurology")
    add_user(client, "dr_retired", "senior", "Cardiology", status="disabled")

    body = directory(client, 3, q="chen", status="active")
    assert [row["name"] for row in body["items"]] == ["dr_chen"]
    assert set(body["items"][0]) == DIRECTORY_FIELDS
    assert body["total"] == 1

    offered = {row["name"]: row for row in directory(client, 3, status="active")["items"]}
    assert "dr_chen" in offered and "dr_retired" not in offered
    # Cardiology (the caller) sees Neurology (the expert): not department-scoped.
    assert offered["dr_chen"]["department"] == "Neurology"


def test_the_directory_pages_and_filters(client):
    page = directory(client, 1, size=2)
    assert (page["total"], page["page"], page["size"]) == (4, 1, 2)
    assert names(page) == ["admin", "junior"]

    second = directory(client, 1, size=2, page=2)
    # `order_by(User.name, User.id)` is a total order, so the two pages are
    # disjoint and together cover everyone.
    assert names(second) == ["outsider", "senior"]

    add_user(client, "jdoe", "junior", "Cardiology", name="Jane Doe")
    assert names(directory(client, 1, q="Jane")) == ["Jane Doe"]
    assert names(directory(client, 1, q="jdoe")) == ["Jane Doe"]
    # `total` counts the filtered whole, not the page.
    filtered = directory(client, 1, q="Jane", size=1)
    assert filtered["total"] == 1 and len(filtered["items"]) == 1

    assert {row["name"] for row in directory(client, 1, title="senior")["items"]} == {
        "outsider",
        "senior",
    }
    assert names(directory(client, 1, department="Cardiology")) == [
        "Jane Doe",
        "junior",
        "outsider",
    ]

    for params in ({"title": "wizard"}, {"status": "retired"}, {"page": 0}, {"size": 101}):
        response = client.get("/api/users", params=params, headers=headers(client, 1))
        assert response.status_code == 422, params

    # An unregistered department name is an empty page, not a 404: the name is
    # data, not a route. `/api/patients` reads the same way.
    unknown = client.get(
        "/api/users", params={"department": "Oncology"}, headers=headers(client, 1)
    )
    assert unknown.status_code == 200 and unknown.json()["data"]["items"] == []


def test_create_user(client):
    response = client.post("/api/users", json=NEW_USER, headers=headers(client, 1))
    assert response.status_code == 200
    created = response.json()["data"]
    assert set(created) == FULL_FIELDS
    assert created["username"] == "dr_new" and created["title"] == "junior"
    assert created["department"] == "Cardiology" and created["status"] == "active"
    assert datetime.fromisoformat(created["created_at"]).tzinfo is not None

    with client.app.state.sessions() as db:
        row = db.scalar(select(User).where(User.username == "dr_new"))
        assert row.password_hash != NEW_USER["password"]
        assert verify_password(NEW_USER["password"], row.password_hash)

    # The account is real, not just a row: it can complete the login handshake.
    credentials = {"username": NEW_USER["username"], "password": NEW_USER["password"]}
    assert client.post("/api/auth/login", json=credentials).status_code == 200

    # Both unique columns are guarded, case-insensitively.
    auth = headers(client, 1)
    assert (
        client.post(
            "/api/users", json={**NEW_USER, "email": "x@example.test"}, headers=auth
        ).status_code
        == 409
    )
    assert (
        client.post("/api/users", json={**NEW_USER, "username": "DR_NEW"}, headers=auth).status_code
        == 409
    )
    assert (
        client.post(
            "/api/users", json={**NEW_USER, "email": "NEW@EXAMPLE.TEST"}, headers=auth
        ).status_code
        == 409
    )


def test_create_user_validates_every_field(client):
    auth = headers(client, 1)
    for field in sorted(NEW_USER):
        broken = {key: value for key, value in NEW_USER.items() if key != field}
        response = client.post("/api/users", json=broken, headers=auth)
        assert response.status_code == 422, field
        assert field in response.json()["message"]

    for override in (
        {"password": "short"},
        # 73 UTF-8 bytes: past bcrypt's ceiling, and a 422 rather than the 500
        # `hash_password` would raise if the schema let it through.
        {"password": "a" * 73},
        {"password": "密码" * 25},
        {"name": "   "},
        {"username": "  "},
        {"email": "not-an-address"},
        {"department": "Oncology"},
        {"title": "wizard"},
        {"ic": "unexpected"},
    ):
        response = client.post("/api/users", json={**NEW_USER, **override}, headers=auth)
        assert response.status_code == 422, override

    with client.app.state.sessions() as db:
        assert db.scalar(select(User.id).where(User.username == "dr_new")) is None


def test_update_user(client):
    auth = headers(client, 1)
    assert client.patch("/api/users/999", json={"name": "x"}, headers=auth).status_code == 404
    assert client.patch("/api/users/abc", json={"name": "x"}, headers=auth).status_code == 422

    for field in ("name", "title", "department", "status"):
        response = client.patch("/api/users/3", json={field: None}, headers=auth)
        assert response.status_code == 422, field
        assert field in response.json()["message"]
    assert stored(client, 3) == ("junior", "active", "junior", "Cardiology")

    # An empty body changes nothing and still answers 200.
    assert client.patch("/api/users/3", json={}, headers=auth).status_code == 200
    assert stored(client, 3) == ("junior", "active", "junior", "Cardiology")

    # The token `current_user` honours is the one already in the caller's hand:
    # it reads the live row rather than the `title` claim it was minted with.
    junior = headers(client, 3)
    assert client.get("/api/users/1", headers=junior).status_code == 403
    assert client.patch("/api/users/3", json={"title": "admin"}, headers=auth).status_code == 200
    assert client.get("/api/users/1", headers=junior).status_code == 200

    assert (
        client.patch("/api/users/3", json={"status": "disabled"}, headers=auth).status_code == 200
    )
    assert client.get("/api/users", headers=junior).status_code == 401
    assert (
        client.post(
            "/api/auth/login", json={"username": "junior", "password": "test-password"}
        ).status_code
        == 401
    )
    assert client.patch("/api/users/3", json={"status": "active"}, headers=auth).status_code == 200
    assert client.get("/api/users", headers=junior).status_code == 200

    assert (
        client.patch(
            "/api/users/3", json={"name": "Renamed", "department": "Neurology"}, headers=auth
        ).status_code
        == 200
    )
    assert stored(client, 3) == ("Renamed", "active", "admin", "Neurology")
    assert (
        client.patch("/api/users/3", json={"department": "Oncology"}, headers=auth).status_code
        == 422
    )


def test_user_management_is_audited_without_the_password(client):
    auth = headers(client, 1)
    created = client.post("/api/users", json=NEW_USER, headers=auth).json()["data"]
    client.patch(f"/api/users/{created['id']}", json={"name": "Renamed"}, headers=auth)

    with client.app.state.sessions() as db:
        rows = list(
            db.scalars(select(AuditLog).where(AuditLog.action.like("user.%")).order_by(AuditLog.id))
        )
    assert [row.action for row in rows] == ["user.create", "user.update"]
    assert {row.object_type for row in rows} == {"user"}
    assert {row.object_id for row in rows} == {str(created["id"])}
    assert {row.user_id for row in rows} == {1}
    assert {row.username for row in rows} == {"admin"}
    assert {row.result for row in rows} == {"success"}
    assert rows[1].detail["changed"] == ["name"]
    assert NEW_USER["password"] not in json.dumps([row.detail for row in rows])


def test_the_role_dictionary_matches_the_permission_matrix(client):
    assert client.get("/api/roles").status_code == 401
    rows = client.get("/api/roles", headers=headers(client, 3)).json()["data"]
    assert [row["code"] for row in rows] == ["admin", "senior", "junior"]
    assert {row["code"] for row in rows} == set(PERMISSIONS)
    assert all(row["label"] for row in rows)


def test_the_directory_query_shape_is_the_contract(client):
    """Four filters, and no silent drift in either direction.

    A filter the contract declares but the code drops is invisible at runtime --
    FastAPI ignores the query string -- so the parameter set is pinned here.
    """

    parameters = client.app.openapi()["paths"]["/api/users"]["get"]["parameters"]
    assert {parameter["name"] for parameter in parameters} == {
        "q",
        "title",
        "department",
        "status",
        "page",
        "size",
    }
