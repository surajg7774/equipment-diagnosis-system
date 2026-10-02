"""SQLAlchemy declarative base and shared column types."""

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    """All ORM models inherit from this."""


class UTCDateTime(TypeDecorator):
    """A timezone-aware UTC datetime that behaves the same on SQLite and PostgreSQL.

    SQLite has no real timezone support and hands back *naive* datetimes, which
    would then serialise to JSON without a "+00:00"/"Z" suffix and look like
    local time.  This type always returns aware UTC values.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is not None and value.tzinfo is not None:
            return value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value: datetime | None, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
