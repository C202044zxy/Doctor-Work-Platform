import base64
from io import BytesIO

import pytest
from PIL import Image
from test_auth_grants import client as auth_client

from app import face_login
from app.models import User

client = auth_client


def photo():
    output = BytesIO()
    Image.new("RGB", (4, 4)).save(output, format="JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode()


def test_session_logout(client):
    response = client.post("/api/auth/face/login", json={"username": "admin", "photo": photo()})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["user"]["username"] == "admin"
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    assert client.get("/api/me", headers=headers).status_code == 200
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/me", headers=headers).status_code == 401


def test_matcher_receives_photo(client, monkeypatch):
    received = []

    def reject(user, image):
        received.append((user.username, image))
        return False

    monkeypatch.setattr(face_login, "match_face", reject)
    image = photo()
    assert (
        client.post("/api/auth/face/login", json={"username": "admin", "photo": image}).status_code
        == 401
    )
    assert received == [("admin", base64.b64decode(image.split(",")[1]))]


@pytest.mark.parametrize("username", ["missing", "admin"])
def test_unavailable_account(client, username):
    with client.app.state.sessions() as db:
        db.get(User, 1).status = "disabled"
        db.commit()
    assert (
        client.post(
            "/api/auth/face/login", json={"username": username, "photo": photo()}
        ).status_code
        == 401
    )


@pytest.mark.parametrize(
    "image",
    [
        # Explicit short ids: pytest copies the parameter id into the
        # PYTEST_CURRENT_TEST environment variable, and the oversized case below
        # would blow past the 32767-character limit Windows imposes on an
        # environment variable, turning the test into a setup error.
        pytest.param("", id="empty"),
        pytest.param("invalid", id="not-a-data-url"),
        pytest.param("data:image/jpeg;base64,%%%", id="invalid-base64"),
        pytest.param("data:image/jpeg;base64,aGVsbG8=", id="not-a-jpeg"),
        pytest.param("x" * 2796228, id="oversized"),
    ],
)
def test_invalid_photo(client, image):
    response = client.post("/api/auth/face/login", json={"username": "admin", "photo": image})
    assert response.status_code == 422
    assert response.json()["code"] != 0


def test_missing_fields_and_removed_passkeys(client):
    assert client.post("/api/auth/face/login", json={}).status_code == 422
    for path in ("register/options", "register/verify", "login/options", "login/verify"):
        assert client.post(f"/api/auth/passkeys/{path}", json={}).status_code == 404
