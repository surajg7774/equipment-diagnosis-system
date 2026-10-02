"""Schemas for the human-in-the-loop review workflow and knowledge-base statistics."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.enums import ReviewPriority, ReviewStatus


class KnowledgeBaseStats(BaseModel):
    """How big the knowledge base is and where its records came from."""

    total: int = Field(description="All records the retrieval step can find.")
    seed: int = Field(description="Records that shipped with the system (data/knowledge_base.json).")
    verified: int = Field(description="Records added from technician-reviewed tickets.")
    verified_confirmed: int = Field(description="Verified records where the technician confirmed the AI's diagnosis.")
    verified_corrected: int = Field(description="Verified records built from the technician's own correction.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"total": 31, "seed": 28, "verified": 3, "verified_confirmed": 2, "verified_corrected": 1}]
        }
    )


def _strip(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


class ConfirmRequest(BaseModel):
    """Body of ``POST /api/v1/tickets/{id}/confirm`` (the whole body is optional)."""

    equipment_type: str | None = Field(
        default=None,
        max_length=64,
        description="Optional equipment type for the new knowledge-base record (e.g. 'pump').",
    )

    _clean = field_validator("equipment_type", mode="before")(_strip)


class CorrectRequest(BaseModel):
    """Body of ``POST /api/v1/tickets/{id}/correct``: what was really wrong, and the real fix."""

    root_cause: str = Field(min_length=5, max_length=2000, description="The actual root cause.")
    recommended_fix: str = Field(min_length=5, max_length=2000, description="The fix that actually worked.")
    equipment_type: str | None = Field(default=None, max_length=64)

    _clean = field_validator("root_cause", "recommended_fix", "equipment_type", mode="before")(_strip)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "root_cause": "The impeller key sheared, so the shaft spun without driving the impeller.",
                    "recommended_fix": "Replace the impeller key and check shaft alignment.",
                    "equipment_type": "pump",
                }
            ]
        }
    )


class ReviewResponse(BaseModel):
    """The ticket's review state after a confirm/correct, plus the knowledge base it grew."""

    ticket_id: int
    review_status: ReviewStatus
    review_priority: ReviewPriority
    reviewed_at: datetime | None
    corrected_root_cause: str | None
    corrected_fix: str | None
    added_to_knowledge_base: bool = Field(description="True once a record built from this ticket is in the knowledge base.")
    kb_record_id: str | None = Field(description="Id of that record (e.g. 'VC-12-a3f9c1'); retrievable in similar_cases.")
    knowledge_base: KnowledgeBaseStats
