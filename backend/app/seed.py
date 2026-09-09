from sqlalchemy import select

from app.config import Settings
from app.database import make_engine, session_factory
from app.models import Department, Role


def seed():
    engine = make_engine(Settings().database_url)
    with session_factory(engine)() as session:
        for name in ("General Medicine", "Cardiology"):
            if session.scalar(select(Department).where(Department.name == name)) is None:
                session.add(Department(name=name))
        for name in ("administrator", "doctor", "department_manager"):
            if session.scalar(select(Role).where(Role.name == name)) is None:
                session.add(Role(name=name))
        session.commit()
    engine.dispose()


if __name__ == "__main__":
    seed()
