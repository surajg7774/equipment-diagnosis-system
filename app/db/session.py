"""Database engine and session factory.

Nothing here is created at import time: ``create_app`` builds the engine from
settings and stores it on ``app.state``; request handlers receive a session
through the ``get_db`` dependency (``app/api/deps.py``).  That keeps the code
free of module-level globals and lets tests substitute their own database.
"""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base


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
