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
    retrieval_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Retrieval similarity (0-1): cosine similarity between the report and the best-matching "
            "past case, i.e. how well the knowledge base covers this issue. Says nothing about "
            "whether the diagnosis is right."
        ),
    )
    llm_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "The LLM's own self-reported certainty (0-1) that its diagnosis is correct, independent "
            "of whether a similar past case was found. Self-reported, so only roughly calibrated. "
            "0.5 if the model gave no usable value."
        ),
    )
    llm_confidence_defaulted: bool = Field(
        description=(
            "True when the model returned no usable confidence and `llm_confidence` is the 0.5 "
            "default rather than the model's own value. Clients should not present it as the AI's certainty."
        )
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        deprecated=True,
        description="DEPRECATED alias of `retrieval_confidence`, kept for backward compatibility.",
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
                    "retrieval_confidence": 0.74,
                    "llm_confidence": 0.9,
                    "llm_confidence_defaulted": False,
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
    """Result of an AI visual assessment of an equipment photo."""

    is_equipment_photo: bool = Field(
        description=(
            "False when the photo does not show equipment (a person, animal, scenery...). Such "
            "photos are answered but NOT stored: ticket_id and severity are null."
        )
    )
    ticket_id: int | None = Field(description="Id of the stored ticket; null if is_equipment_photo is false.")
    damage_detected: bool = Field(description="Whether the model sees damage, wear, leaks, corrosion or other abnormal conditions.")
    severity: Severity | None = Field(description="The model's urgency rating (low when normal); null if not an equipment photo.")
    description: str = Field(description="What the model sees: the findings, in its own words.")
    recommended_action: str = Field(description="Suggested next step for the technician.")
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="The model's self-reported certainty (0-1); null if it gave no usable number.",
    )
    model_name: str = Field(description="The vision model that produced this assessment.")
    provider: str = Field(description="Who runs the model (e.g. 'groq').")
    note: str | None = Field(default=None, description="Set when the photo was not stored.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "is_equipment_photo": True,
                    "ticket_id": 43,
                    "damage_detected": True,
                    "severity": "high",
                    "description": "A stack of steel pipes with heavy orange-brown surface rust and corroded threads on the pipe ends.",
                    "recommended_action": "Do not use these pipes for pressure service; inspect wall thickness and replace corroded sections.",
                    "confidence": 0.85,
                    "model_name": "qwen/qwen3.8-27b",
                    "provider": "groq",
                    "note": None,
                }
            ]
        }
    )
