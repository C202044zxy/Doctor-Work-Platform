from sqlalchemy import select

from app.config import Settings
from app.database import make_engine, session_factory
from app.models import Department, Role


def seed():
    engine = make_engine(Settings().database_url)
    with session_factory(engine)() as session:
        # Order matters: these are inserted in sequence, so id 1 is Information
        # Technology. Tests and the presentation seeders index into this list,
        # and docs/02-测试场景.md pins the same three names and their order.
        for name in ("Information Technology", "Cardiology", "Neurology"):
            if session.scalar(select(Department).where(Department.name == name)) is None:
                session.add(Department(name=name))
        for name in ("admin", "senior", "junior"):
            if session.scalar(select(Role).where(Role.name == name)) is None:
                session.add(Role(name=name))
        from app.emr_seed import seed_emr

        seed_emr(session)
        session.commit()
    engine.dispose()


if __name__ == "__main__":
    seed()
