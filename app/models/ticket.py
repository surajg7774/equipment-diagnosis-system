"""ORM models: a diagnosis ticket and the technician feedback on it."""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime
from app.schemas.enums import Severity


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Ticket(Base):
    """One call to /diagnose or /diagnose-image."""

    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # "text" or "image" - which endpoint produced it.
    source: Mapped[str] = mapped_column(String(16), default="text")
    description: Mapped[str] = mapped_column(Text)
    # native_enum=False stores a plain VARCHAR, so there is no PostgreSQL
    # ENUM type to migrate when severity levels change.
    severity: Mapped[Severity] = mapped_column(Enum(Severity, native_enum=False, length=16))
    diagnosis: Mapped[str] = mapped_column(Text)
    recommended_action: Mapped[str] = mapped_column(Text)
    confidence_score: Mapped[float] = mapped_column(Float)
    # Snapshot of the matches shown to the technician. SQLAlchemy's generic JSON
    # type maps to TEXT on SQLite and JSON/JSONB on PostgreSQL.
    similar_cases: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow, index=True)

    feedback: Mapped["Feedback | None"] = relationship(
        back_populates="ticket", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def feedback_was_correct(self) -> bool | None:
        """Convenience for the API schema: the feedback verdict, if any."""
        return self.feedback.was_correct if self.feedback else None


class Feedback(Base):
    """Technician verdict on a ticket. At most one per ticket."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # unique=True enforces "one feedback per ticket" in the database itself.
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), unique=True, index=True)
    was_correct: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)

    ticket: Mapped[Ticket] = relationship(back_populates="feedback")
