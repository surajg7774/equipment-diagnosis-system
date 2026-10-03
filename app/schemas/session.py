"""Schemas for iterative diagnosis sessions ("try a solution, give feedback, get the next one")."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.diagnosis import DiagnoseResponse
from app.schemas.enums import SessionStatus, Severity


class SessionFeedbackRequest(BaseModel):
    """Body of ``POST /api/v1/sessions/{session_id}/feedback``."""

    was_helpful: bool = Field(description="Did the latest solution fix the problem?")
    attempt_number: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Optional: the attempt this answer is about. If it is not the session's latest attempt "
            "(a stale tab, a double click) the request is refused with 409 instead of skipping a solution."
        ),
    )

    model_config = ConfigDict(json_schema_extra={"examples": [{"was_helpful": False, "attempt_number": 1}]})


class SessionFeedbackResponse(BaseModel):
    session_id: str
    status: SessionStatus = Field(description="in_progress, resolved, or abandoned (all attempts used: escalate).")
    resolved: bool = Field(description="True when the user said a solution worked.")
    escalate: bool = Field(description="True when every allowed attempt failed: hand this to a human technician.")
    attempt_number: int = Field(description="The attempt the user just answered about.")
    max_attempts: int
    message: str | None = Field(default=None, description="A human-readable confirmation or escalation notice.")
    added_to_knowledge_base: bool = Field(
        default=False,
        description="True when a 'yes' on a reasonably trusted solution was added to the knowledge base for future retrieval.",
    )
    next_attempt: DiagnoseResponse | None = Field(
        default=None,
        description="The new, different solution (same shape as /diagnose, with its own attempt_number); null when resolved or escalated.",
    )


class AttemptOut(BaseModel):
    """One solution attempt as shown in history."""

    attempt_number: int
    diagnosis: str
    recommended_action: str
    severity: Severity
    diagnosis_basis: str
    retrieval_confidence: float
    llm_confidence: float | None
    was_helpful: bool | None = Field(description="true = solved it, false = did not, null = no answer yet.")
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SessionOut(BaseModel):
    """A diagnosis session as shown in history."""

    session_id: str
    status: SessionStatus
    attempt_count: int
    attempts_to_resolve: int | None = Field(description="How many attempts it took, for a resolved session; otherwise null.")
    created_at: datetime
    resolved_at: datetime | None
    attempts: list[AttemptOut]

    model_config = ConfigDict(from_attributes=True)
