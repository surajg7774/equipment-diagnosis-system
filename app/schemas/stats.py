"""Response schema for the transparency / usage statistics endpoint."""

from pydantic import BaseModel, ConfigDict, Field


class ResolutionStats(BaseModel):
    """How text diagnoses were grounded: retrieved past cases vs the LLM's general knowledge."""

    counted: int = Field(description="Text diagnoses with a recorded basis (older tickets predate this and are excluded).")
    similar_cases: int
    general_reasoning: int
    similar_cases_pct: float | None = Field(description="Percent of counted diagnoses resolved via similar past cases; null if none counted.")
    general_reasoning_pct: float | None = Field(description="Percent resolved via the LLM's general reasoning; null if none counted.")


class AverageConfidence(BaseModel):
    """Averages on a 0-1 scale (null when there is nothing to average)."""

    retrieval: float | None = Field(description="Mean similarity of the best retrieved case, over text diagnoses.")
    llm: float | None = Field(description="Mean self-reported LLM certainty, over diagnoses where the model gave one.")
    image: float | None = Field(description="Mean self-reported certainty of photo assessments.")


class ReviewCounts(BaseModel):
    pending: int
    confirmed: int
    corrected: int


class StatsResponse(BaseModel):
    """A demo-friendly snapshot of usage and of the knowledge base's growth."""

    total_diagnoses_performed: int = Field(
        description="Stored diagnoses (text + photo). Inputs rejected as 'not an equipment issue' are answered but not stored, so not counted."
    )
    text_diagnoses: int
    image_diagnoses: int
    resolution: ResolutionStats
    knowledge_base_size: int | None = Field(description="All records retrieval can find; null if the vector store is unavailable.")
    original_seed_count: int | None = Field(description="Records that shipped with the system.")
    technician_verified_count: int | None = Field(description="Records added from technician-reviewed tickets.")
    review: ReviewCounts
    average_confidence: AverageConfidence

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "total_diagnoses_performed": 12,
                    "text_diagnoses": 10,
                    "image_diagnoses": 2,
                    "resolution": {"counted": 10, "similar_cases": 6, "general_reasoning": 4, "similar_cases_pct": 60.0, "general_reasoning_pct": 40.0},
                    "knowledge_base_size": 31,
                    "original_seed_count": 28,
                    "technician_verified_count": 3,
                    "review": {"pending": 8, "confirmed": 2, "corrected": 2},
                    "average_confidence": {"retrieval": 0.512, "llm": 0.81, "image": 0.9},
                }
            ]
        }
    )
