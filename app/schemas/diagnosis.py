"""Request/response schemas for the diagnosis endpoints."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.enums import DiagnosisBasis, Severity
from app.schemas.knowledge_base import SimilarCase


class DiagnoseRequest(BaseModel):
    """Body of ``POST /api/v1/diagnose``."""

    description: str = Field(
        min_length=10,
        max_length=2000,
        description="Free-text description of the equipment problem (10-2000 characters).",
    )

    # Strip leading/trailing whitespace *before* the length check, so
    # "          " (10 spaces) is rejected rather than accepted as valid.
    @field_validator("description", mode="before")
    @classmethod
    def _strip_whitespace(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"description": "pump making loud grinding noise and leaking oil"}]
        }
    )


class DiagnoseResponse(BaseModel):
    """Result of a text diagnosis."""

    is_valid_issue: bool = Field(
        description=(
            "False when the input does not describe an equipment problem (e.g. a general "
            "question). Such requests are answered but NOT stored: ticket_id and severity are null."
        )
    )
    ticket_id: int | None = Field(
        description="Id of the stored ticket (use it for feedback); null if is_valid_issue is false."
    )
    severity: Severity | None = Field(
        description=(
            "Urgency: the more severe of a keyword heuristic and the LLM's assessment; "
            "null if is_valid_issue is false."
        )
    )
    diagnosis: str = Field(
        description="Likely root cause, written by the LLM for this specific report (not copied from a past case)."
    )
    recommended_action: str = Field(description="Next steps for the technician, written by the LLM.")
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Cosine similarity (0-1) between the report and the best-matching past case, i.e. how "
            "well the knowledge base covers this issue. It is NOT the LLM's certainty and not a "
            "calibrated probability of being right."
        ),
    )
    similar_cases: list[SimilarCase] = Field(
        description="Top matching past cases retrieved as context, best first (shown even when they are weak matches)."
    )
    diagnosis_basis: DiagnosisBasis = Field(
        description=(
            "'similar_cases': the LLM was given the retrieved cases as reference examples. "
            "'general_reasoning': no close match existed, so the LLM relied on its own knowledge."
        )
    )
    note: str | None = Field(
        default=None, description="Set when the diagnosis is not grounded in a close past case."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "is_valid_issue": True,
                    "ticket_id": 42,
                    "severity": "high",
                    "diagnosis": "The loud grinding together with an oil leak at the shaft points to worn pump bearings and a failed shaft seal, likely from lack of lubrication.",
                    "recommended_action": "Isolate and shut down the pump, replace the bearings and the mechanical seal, re-lubricate to spec and check shaft alignment before restart.",
                    "confidence_score": 0.74,
                    "diagnosis_basis": "similar_cases",
                    "note": None,
                    "similar_cases": [
                        {
                            "id": "KB-001",
                            "equipment_type": "pump",
                            "issue_description": "Centrifugal pump makes a loud grinding noise and vibrates heavily during operation.",
                            "root_cause": "Worn or failed bearings, often caused by lack of lubrication or contamination.",
                            "recommended_fix": "Shut down the pump, replace the bearings, flush old grease and re-lubricate to manufacturer spec.",
                            "severity": "high",
                            "similarity_score": 0.74,
                        }
                    ],
                }
            ]
        }
    )


class ImageDiagnoseResponse(BaseModel):
    """Result of an image diagnosis (currently produced by a placeholder model)."""

    ticket_id: int
    severity: Severity
    diagnosis: str
    recommended_action: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    model_name: str = Field(description="Which vision model produced this result.")
    is_placeholder: bool = Field(
        description="True while a stand-in model is used. Results are NOT real predictions."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "ticket_id": 43,
                    "severity": "medium",
                    "diagnosis": "[PLACEHOLDER] Visual pattern resembling: corrosion",
                    "recommended_action": "Clean the affected area, apply a corrosion inhibitor and schedule a detailed inspection.",
                    "confidence_score": 0.5,
                    "model_name": "placeholder-vision-v0",
                    "is_placeholder": True,
                }
            ]
        }
    )
