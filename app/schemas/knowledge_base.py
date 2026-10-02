"""Schemas for knowledge-base records and similarity-search hits."""

from pydantic import BaseModel, Field

from app.schemas.enums import Severity


class KnowledgeBaseRecord(BaseModel):
    """One historical issue + its resolution (a row of ``knowledge_base.json``)."""

    id: str = Field(description="Unique record id", examples=["KB-001"])
    equipment_type: str = Field(examples=["pump"])
    issue_description: str = Field(
        examples=["Centrifugal pump makes a loud grinding noise and vibrates heavily."]
    )
    root_cause: str = Field(examples=["Worn or failed bearings."])
    recommended_fix: str = Field(examples=["Replace the bearings and re-lubricate."])
    severity: Severity


class SimilarCase(KnowledgeBaseRecord):
    """A knowledge-base record returned by a similarity search."""

    similarity_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Cosine similarity between the query and this case (1.0 = identical meaning).",
        examples=[0.78],
    )
