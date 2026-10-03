"""Schemas shared across endpoints: errors and health."""

from pydantic import BaseModel, ConfigDict, Field


class FieldError(BaseModel):
    field: str = Field(description="Dotted path of the invalid field, e.g. 'description'.")
    message: str


class ErrorBody(BaseModel):
    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Human-readable explanation.")
    details: list[FieldError] | None = Field(default=None, description="Per-field validation errors.")
    request_id: str | None = Field(default=None, description="Quote this when reporting a server error.")


class ErrorResponse(BaseModel):
    """Every error from this API has this shape."""

    error: ErrorBody

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "error": {
                        "code": "validation_error",
                        "message": "Request validation failed.",
                        "details": [
                            {
                                "field": "description",
                                "message": "String should have at least 10 characters",
                            }
                        ],
                    }
                }
            ]
        }
    )


class HealthResponse(BaseModel):
    status: str = Field(description="'ok' if all checks pass, otherwise 'degraded'.")
    version: str
    database: str = Field(description="'ok' or 'error'.")
    vector_store: str = Field(description="'ok' or 'error'.")
    llm: str = Field(description="'ok' if Ollama is reachable and the model is pulled, else 'error'.")
    knowledge_base_size: int = Field(description="Number of records in the vector store.")
    technician_code_required: bool = Field(
        default=False,
        description="True when Verify/Confirm/Correct need the technician access code (X-Technician-Code). Never the code itself.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "status": "ok",
                    "version": "1.0.0",
                    "database": "ok",
                    "vector_store": "ok",
                    "llm": "ok",
                    "knowledge_base_size": 28,
                }
            ]
        }
    )
