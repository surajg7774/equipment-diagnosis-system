"""Schemas for ticket history and feedback."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import ReviewPriority, ReviewStatus, Severity


class HistoryItem(BaseModel):
    """One stored ticket (built straight from the ORM object)."""

    id: int
    created_at: datetime
    source: Literal["text", "image"] = Field(description="Which endpoint created the ticket.")
    description: str
    severity: Severity
    diagnosis: str
    recommended_action: str
    confidence_score: float
    feedback_was_correct: bool | None = Field(
        default=None, description="Technician feedback, or null if none was given yet."
    )
    review_status: ReviewStatus = Field(description="pending, confirmed or corrected by a technician.")
    review_priority: ReviewPriority = Field(description="How urgently a pending ticket needs review.")
    corrected_root_cause: str | None = Field(default=None, description="The technician's root cause, if corrected.")
    corrected_fix: str | None = Field(default=None, description="The technician's fix, if corrected.")
    reviewed_at: datetime | None = None
    kb_record_id: str | None = Field(default=None, description="Knowledge-base record built from this ticket, if reviewed.")

    model_config = ConfigDict(from_attributes=True)


class HistoryPage(BaseModel):
    """One page of tickets, newest first."""

    items: list[HistoryItem]
    total: int = Field(description="Total tickets across all pages.")
    page: int = Field(description="Current page number (1-based).")
    page_size: int
    total_pages: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "id": 42,
                            "created_at": "2026-10-02T09:15:30Z",
                            "source": "text",
                            "description": "pump making loud grinding noise and leaking oil",
                            "severity": "high",
                            "diagnosis": "Worn or failed bearings...",
                            "recommended_action": "Shut down the pump, replace the bearings...",
                            "confidence_score": 0.74,
                            "feedback_was_correct": True,
                            "review_status": "pending",
                            "review_priority": "high",
                            "corrected_root_cause": None,
                            "corrected_fix": None,
                            "reviewed_at": None,
                            "kb_record_id": None,
                        }
                    ],
                    "total": 1,
                    "page": 1,
                    "page_size": 20,
                    "total_pages": 1,
                }
            ]
        }
    )


class FeedbackRequest(BaseModel):
    """Body of ``POST /api/v1/feedback``."""

    ticket_id: int = Field(gt=0, description="Id returned by /diagnose.")
    was_correct: bool = Field(description="Did the diagnosis turn out to be correct?")

    model_config = ConfigDict(json_schema_extra={"examples": [{"ticket_id": 42, "was_correct": True}]})


class FeedbackResponse(BaseModel):
    id: int
    ticket_id: int
    was_correct: bool
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {"id": 7, "ticket_id": 42, "was_correct": True, "created_at": "2026-10-02T10:02:11Z"}
            ]
        },
    )
