"""Both released module heads upgrade to the merged schema without losing data."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.models import Base


@pytest.mark.parametrize("previous_head", ["7ad4cb527bd2", "a3d9e5f21c70"])
def test_upgrade_from_either_module_head(tmp_path, monkeypatch, previous_head):
    url = f"sqlite:///{tmp_path / 'upgrade.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, previous_head)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO departments (name) VALUES ('Existing department')"))
    command.upgrade(config, "head")
    assert set(inspect(engine).get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalars().all() == ["b4c6d0192026"]
        assert (
            connection.execute(text("SELECT name FROM departments")).scalar_one()
            == "Existing department"
        )
        triggers = set(
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='trigger'")
            ).scalars()
        )
        assert {"audit_logs_no_update", "audit_logs_no_delete"} <= triggers
    engine.dispose()
