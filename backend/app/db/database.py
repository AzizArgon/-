from sqlalchemy import create_engine, event, inspect, text
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


def add_missing_columns() -> None:
    """create_all makes only new tables: new columns of old tables are added here (no Alembic)."""
    existing = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not existing.has_table(table.name):
                continue
            have = {c["name"] for c in existing.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                default = f" DEFAULT '{col.server_default.arg}'" if col.server_default is not None else ""
                conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}{default}"))


def init_db():
    from app.db import models  # noqa: F401  (register models on Base.metadata)

    Base.metadata.create_all(bind=engine)
    add_missing_columns()

    from app.db.seed import seed_categories

    with SessionLocal() as db:
        seed_categories(db)
