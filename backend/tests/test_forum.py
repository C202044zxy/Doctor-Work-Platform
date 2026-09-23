"""M7-T1–M7-T4: persistent, shared, authenticated professional discussions."""

import pytest
from sqlalchemy import func, select
from test_auth_grants import client as auth_client
from test_auth_grants import headers

from app.models import ForumPost, ForumReply
from app.seed_forum import seed_forum

client = auth_client


def create(client, user=1, **overrides):
    return client.post(
        "/api/forum/posts",
        headers=headers(client, user),
        json={
            "title": "Handover ideas",
            "category": "Clinical practice",
            "body": "Discuss teaching approaches.",
            **overrides,
        },
    )


def test_discussion_and_cross_department_reply(client):
    assert client.get("/api/forum/posts").status_code == 401
    assert client.post("/api/forum/posts", json={}).status_code == 401
    post = create(client).json()["data"]
    path = f"/api/forum/posts/{post['id']}"
    assert client.get(path, headers=headers(client, 3)).json()["data"]["title"] == post["title"]
    reply = client.post(
        path + "/replies", headers=headers(client, 3), json={"body": "  A learning session  "}
    )
    assert reply.status_code == 200
    assert reply.json()["data"]["body"] == "A learning session"
    assert reply.json()["data"]["author"] == "junior"
    assert client.get(path, headers=headers(client)).json()["data"]["reply_count"] == 1
    listing = client.get(path + "/replies", headers=headers(client)).json()["data"]
    assert listing["items"][0]["id"] == reply.json()["data"]["id"]
    assert listing["total"] == 1
    assert not post["is_sample"]
    for suffix in ["", "/replies"]:
        assert (
            client.get("/api/forum/posts/9999" + suffix, headers=headers(client)).status_code == 404
        )
    assert (
        client.post(
            "/api/forum/posts/9999/replies", headers=headers(client), json={"body": "hello"}
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "body",
    [
        {"title": "   "},
        {"body": ""},
        {"category": "unknown"},
        {"title": "x" * 161},
        {"patient_no": "P001"},
    ],
)
def test_invalid_posts(client, body):
    assert create(client, **body).status_code == 422


def test_search_pagination_and_validation(client):
    create(client)
    create(client, title="Communication tips", category="Patient communication")
    auth = headers(client)
    result = client.get(
        "/api/forum/posts?q=HANDOVER&category=Clinical+practice", headers=auth
    ).json()["data"]
    assert result["total"] == 1
    assert client.get("/api/forum/posts?q=%25", headers=auth).json()["data"]["total"] == 0
    result = client.get("/api/forum/posts?page=2&size=1", headers=auth).json()["data"]
    assert result["total"] == 2 and len(result["items"]) == 1 and result["page"] == 2
    for query in ["size=101", "page=0", "category=unknown"]:
        assert client.get("/api/forum/posts?" + query, headers=auth).status_code == 422
    for body in [" ", "x" * 5001]:
        assert (
            client.post("/api/forum/posts/1/replies", headers=auth, json={"body": body}).status_code
            == 422
        )


def test_seed_idempotence_and_disabled_forum(client):
    with client.app.state.sessions() as db:
        seed_forum(db)
        db.commit()
        first = db.scalar(select(ForumPost).order_by(ForumPost.id))
        first.body = "Preserve edited sample"
        db.commit()
        seed_forum(db)
        db.commit()
        assert db.scalar(select(func.count()).select_from(ForumPost)) == 4
        assert db.scalar(select(func.count()).select_from(ForumReply)) == 4
        assert first.body == "Preserve edited sample"
    assert all(
        p["is_sample"]
        for p in client.get("/api/forum/posts", headers=headers(client)).json()["data"]["items"]
    )
    client.app.state.settings.forum_enabled = False
    assert client.get("/api/forum/posts", headers=headers(client)).status_code == 404
    assert create(client).status_code == 404
