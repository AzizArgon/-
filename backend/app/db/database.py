from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_conn, _):
    dbapi_conn.execute("PRAGMA foreign_keys=ON")


@event.listens_for(Engine, "connect")
def _register_py_lower(dbapi_conn, _):
    # SQLite lower() knows only ASCII: catalog search needs Russian words lowercased too
    dbapi_conn.create_function("py_lower", 1, lambda s: s.lower() if isinstance(s, str) else s, deterministic=True)


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app.db import models  # noqa: F401  (register models on Base.metadata)

    Base.metadata.create_all(bind=engine)

    from app.db.seed import seed_categories

    with SessionLocal() as db:
        seed_categories(db)
