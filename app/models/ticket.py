"""ORM models: a diagnosis ticket, the technician feedback on it, and the iterative diagnosis session.

A text diagnosis creates a Ticket (what history, review and stats are built on) AND a
DiagnosisSession that holds the "try a solution, give feedback, get the next one" loop. The first
attempt's content is also on the ticket; later attempts live only in SolutionAttempt rows.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime
from app.schemas.enums import ReviewPriority, ReviewStatus, SessionStatus, Severity


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

    # How this text diagnosis was grounded ("similar_cases" / "general_reasoning") and the LLM's own
    # certainty (0-1; null when the model gave none). Recorded so /stats can report on them.
    # Null for photo tickets and for tickets created before these columns existed.
    diagnosis_basis: Mapped[str | None] = mapped_column(String(24), nullable=True)
    llm_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Human-in-the-loop review -------------------------------------------------------
    # values_callable stores "pending"/"confirmed"... (the values), and server_default lets the
    # startup migration add these columns to a database that already has tickets.
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, native_enum=False, length=16, values_callable=lambda e: [m.value for m in e]),
        default=ReviewStatus.PENDING,
        server_default=ReviewStatus.PENDING.value,
    )
    # Medium/high severity tickets are reviewed first. Set once, when the ticket is created.
    review_priority: Mapped[ReviewPriority] = mapped_column(
        Enum(ReviewPriority, native_enum=False, length=8, values_callable=lambda e: [m.value for m in e]),
        default=ReviewPriority.LOW,
        server_default=ReviewPriority.LOW.value,
    )
    # The technician's correction, stored NEXT TO the original AI diagnosis (which is never
    # overwritten) so the two can be compared.
    corrected_root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_fix: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # The knowledge-base record created from this ticket (and the equipment type the technician
    # gave), so it can be updated if the review changes and rebuilt if the vector store is wiped.
    kb_record_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_equipment_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The "failed_fix" record created by a thumbs-down on this ticket (the AI's diagnosis did not work).
    # Separate from kb_record_id: a ticket can later ALSO get a verified record (e.g. a technician's correction).
    failed_kb_record_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    feedback: Mapped["Feedback | None"] = relationship(
        back_populates="ticket", uselist=False, cascade="all, delete-orphan"
    )
    # The iterative session started by this diagnosis (None for photo tickets and for tickets that
    # predate sessions).
    diagnosis_session: Mapped["DiagnosisSession | None"] = relationship(
        back_populates="ticket", uselist=False
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


def _new_session_id() -> str:
    # Random and unguessable: anyone holding a session id may give feedback on it.
    return uuid.uuid4().hex


class DiagnosisSession(Base):
    """One problem being worked on: the original report plus the solutions tried so far."""

    __tablename__ = "diagnosis_sessions"

    session_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_session_id)
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"), unique=True, nullable=True, index=True)
    original_description: Mapped[str] = mapped_column(Text)
    equipment_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, native_enum=False, length=16, values_callable=lambda e: [m.value for m in e]),
        default=SessionStatus.IN_PROGRESS,
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    ticket: Mapped[Ticket | None] = relationship(back_populates="diagnosis_session")
    attempts: Mapped[list["SolutionAttempt"]] = relationship(
        back_populates="session", order_by="SolutionAttempt.attempt_number", cascade="all, delete-orphan"
    )

    @property
    def latest_attempt(self) -> "SolutionAttempt | None":
        return self.attempts[-1] if self.attempts else None

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    @property
    def attempts_to_resolve(self) -> int | None:
        """How many attempts it took, once resolved (the winning attempt is the last one)."""
        return len(self.attempts) if self.status == SessionStatus.RESOLVED else None


class SolutionAttempt(Base):
    """One proposed diagnosis + fix within a session, and whether the user said it worked."""

    __tablename__ = "solution_attempts"
    # The database itself refuses two attempts with the same number (e.g. a double-clicked "No").
    __table_args__ = (UniqueConstraint("session_id", "attempt_number", name="uq_attempt_number_per_session"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("diagnosis_sessions.session_id"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)  # 1-based
    diagnosis: Mapped[str] = mapped_column(Text)
    recommended_action: Mapped[str] = mapped_column(Text)
    severity: Mapped[Severity] = mapped_column(Enum(Severity, native_enum=False, length=16))
    diagnosis_basis: Mapped[str] = mapped_column(String(24))  # "similar_cases" / "general_reasoning"
    retrieval_confidence: Mapped[float] = mapped_column(Float)
    llm_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # null: the model gave no usable number
    similar_cases: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # null = no answer yet, true = this solved it, false = it did not
    was_helpful: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow)

    session: Mapped[DiagnosisSession] = relationship(back_populates="attempts")
