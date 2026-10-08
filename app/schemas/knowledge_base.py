"""Schemas for knowledge-base records and similarity-search hits."""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.enums import FixVerification, KnowledgeOutcome, Severity


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
    safety_note: str | None = Field(
        default=None,
        description="A safety warning for work on this problem (electrical, gas, pressure, rotating parts), where one applies.",
    )
    # Where the record's content comes from (seed file only; records learned from feedback have none of these).
    # Not to be confused with `source` below, which says how the record got into the knowledge base.
    source_type: Literal["documented", "general_knowledge"] | None = Field(
        default=None,
        description=(
            "'documented' = the cause and fix come from the cited public page (source_url), written in our own words; "
            "'general_knowledge' = no source was found, so it is unverified. Null for records learned from feedback."
        ),
    )
    source_name: str | None = Field(default=None, description="Publisher and title of the cited page (documented records).")
    source_url: str | None = Field(default=None, description="Public page the record is based on (documented records).")
    source: Literal["seed", "verified", "feedback"] = Field(
        default="seed",
        description=(
            "'seed' = shipped with the system; 'verified' = added from a confirmed or corrected ticket; "
            "'feedback' = added from a thumbs-down (a fix that did not work)."
        ),
    )
    outcome: KnowledgeOutcome | None = Field(
        default=None,
        description=(
            "'verified_fix' = the fix is confirmed to work; 'provisional_fix' = confirmed once but not verified yet; "
            "'failed_fix' = it was suggested and did NOT work. "
            "Null for seed records (curated resolved cases, treated as working fixes)."
        ),
    )
    verification: FixVerification | None = Field(
        default=None,
        description="'verified' or 'provisional' for a confirmed fix learned from feedback; null for seed and failed records.",
    )
    confirmation_count: int | None = Field(
        default=None,
        description="Total confirmation weight behind a learned fix (a user's click counts 1, a technician's review 2).",
    )


class SimilarCase(KnowledgeBaseRecord):
    """A knowledge-base record returned by a similarity search."""

    similarity_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Cosine similarity between the query and this case (1.0 = identical meaning).",
        examples=[0.78],
    )
