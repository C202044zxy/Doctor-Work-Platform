"""Integration of released M3 and main schemas must preserve each order namespace."""

from collections import Counter
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, inspect, text
from test_auth_grants import client as auth_client
from test_auth_grants import headers

client = auth_client


@pytest.mark.parametrize("previous", ["c93f105d2e71", "a7f3c2e91d04"])
def test_released_head_preserves_orders(previous, tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'released.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, previous)
    engine = create_engine(url)
    metadata = MetaData()
    metadata.reflect(engine)
    tables = metadata.tables
    now = datetime.now(UTC)
    with engine.begin() as db:
        db.execute(tables["departments"].insert().values(id=1, name="Sentinel"))
        db.execute(tables["roles"].insert().values(id=1, name="senior"))
        db.execute(
            tables["users"]
            .insert()
            .values(
                id=1,
                username="sentinel",
                name="Sentinel",
                email="sentinel@example.test",
                password_hash="unused",
                role_id=1,
                department_id=1,
                status="active",
                created_at=now,
            )
        )
        patient = {
            "id": 1,
            "patient_no": "P20269999",
            "name": "Sentinel",
            "gender": "unknown",
            "department_id": 1,
            "notes": "",
            "created_at": now,
        }
        if "symptom_tags" in tables["patients"].c:
            patient["symptom_tags"] = "existing-tag"
        db.execute(tables["patients"].insert().values(**patient))
        if previous == "a7f3c2e91d04":
            db.execute(
                tables["emr_template"]
                .insert()
                .values(
                    id=1,
                    name="Sentinel",
                    description="",
                    fields_json=[],
                    is_active=True,
                )
            )
            db.execute(
                tables["emr_record"]
                .insert()
                .values(
                    id=1,
                    patient_id=1,
                    template_id=1,
                    template_snapshot={},
                    author_id=1,
                    content_json={},
                    status="draft",
                    version=1,
                    revision=1,
                    updated_at=now,
                    created_at=now,
                )
            )
        db.execute(
            tables["medical_order"]
            .insert()
            .values(
                id=41,
                record_id=1,
                patient_id=1,
                doctor_id=1,
                order_type="drug",
                content_json={"sentinel": previous},
                status="active",
                validation_status="passed",
                validation_detail=[],
                override_reason="keep me",
                created_at=now,
            )
        )
    command.upgrade(config, "head")
    retained = "legacy_medical_order" if previous == "c93f105d2e71" else "medical_order"
    other = "medical_order" if retained == "legacy_medical_order" else "legacy_medical_order"
    with engine.connect() as db:
        assert db.scalar(text(f"SELECT override_reason FROM {retained} WHERE id=41")) == "keep me"
        assert previous in db.scalar(text(f"SELECT content_json FROM {retained} WHERE id=41"))
        assert db.scalar(text(f"SELECT count(*) FROM {other}")) == 0
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
        if previous == "c93f105d2e71":
            assert (
                db.scalar(text("SELECT tag FROM patient_symptom_tags WHERE patient_id=1"))
                == "existing-tag"
            )
    assert {"medical_order", "legacy_medical_order", "call_log"} <= set(
        inspect(engine).get_table_names()
    )
    engine.dispose()
    command.downgrade(config, "base")
    engine = create_engine(url)
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_main_and_legacy_endpoints_are_distinct(client):
    registered = Counter(
        (method, route.path)
        for route in client.app.routes
        for method in getattr(route, "methods", [])
    )
    assert all(count == 1 for count in registered.values())
    main = client.get("/api/reminders/unread-count", headers=headers(client, 2))
    legacy = client.get("/api/legacy/reminders/unread-count", headers=headers(client, 2))
    assert main.status_code == legacy.status_code == 200
    assert main.json()["data"] == {"unread": 0}
    assert legacy.json()["data"] == {"unread_count": 0}


def test_access_log_redaction_preserves_uvicorn_formatter():
    import logging

    from uvicorn.logging import AccessFormatter

    from app.logging_utils import RedactWebSocketToken

    for path in ("/api/health/ready", "/ws/chat/1?token=private-test-value&other=1"):
        record = logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            "",
            1,
            '%s - "%s %s HTTP/%s" %d',
            ("127.0.0.1:1234", "GET", path, "1.1", 200),
            None,
        )
        RedactWebSocketToken().filter(record)
        rendered = AccessFormatter("%(client_addr)s - %(request_line)s %(status_code)s").format(
            record
        )
        assert "200" in rendered and "GET" in rendered
        assert "private-test-value" not in rendered
        if "token=" in path:
            assert "[redacted]" in rendered
