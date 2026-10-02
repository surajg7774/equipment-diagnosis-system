"""Database engine and session factory.

Nothing here is created at import time: ``create_app`` builds the engine from
settings and stores it on ``app.state``; request handlers receive a session
through the ``get_db`` dependency (``app/api/deps.py``).  That keeps the code
free of module-level globals and lets tests substitute their own database.
"""

import logging

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base

logger = logging.getLogger(__name__)


def create_db_engine(database_url: str) -> Engine:
    """Create an engine. Only SQLite needs special arguments; PostgreSQL does not."""
    connect_args = {}
    if database_url.startswith("sqlite"):
        # FastAPI runs sync endpoints/dependencies in a thread pool, so one
        # connection may be used from more than one thread. SQLite refuses that
        # by default; each request still gets its own Session, so this is safe.
        connect_args["check_same_thread"] = False
    return create_engine(database_url, connect_args=connect_args)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False: keep attributes readable after commit() so we can
    # build the response from the object without an extra SELECT.
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Create tables if they do not exist.

    Fine for a dev/portfolio setup. In production, replace with Alembic
    migrations so schema changes are versioned.
    """
    # Importing the models registers them on Base.metadata.
    from app.models import ticket  # noqa: F401

    Base.metadata.create_all(engine)
    add_missing_columns(engine)


def add_missing_columns(engine: Engine) -> list[str]:
    """Add model columns that an older database file does not have yet; returns what was added.

    ``create_all`` creates missing TABLES but never alters existing ones, so a database created
    before a column was introduced would break. This bridges that gap for simple additive
    changes (new nullable columns, or NOT NULL columns that have a server default). Anything
    more involved (renames, type changes) still needs real migrations (Alembic).
    """
    added: list[str] = []
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column.type.compile(dialect=engine.dialect)}'
            if column.server_default is not None:
                ddl += f" DEFAULT '{column.server_default.arg}'"
                if not column.nullable:
                    ddl += " NOT NULL"
            elif not column.nullable:
                continue  # cannot add a NOT NULL column without a default: leave it to a real migration
            with engine.begin() as connection:
                connection.execute(text(ddl))
            added.append(f"{table.name}.{column.name}")
            logger.info("schema_column_added", extra={"table": table.name, "column": column.name})
    return added
