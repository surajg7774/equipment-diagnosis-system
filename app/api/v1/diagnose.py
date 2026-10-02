"""Diagnosis endpoints. Handlers stay thin: validate -> call services -> shape response."""

import logging
from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from app.api.deps import DiagnosisServiceDep, SettingsDep, TicketServiceDep, VisionServiceDep
from app.schemas.common import ErrorResponse
from app.schemas.diagnosis import DiagnoseRequest, DiagnoseResponse, ImageDiagnoseResponse
from app.services.vision_service import validate_image_bytes

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Diagnosis"])


@router.post(
    "/diagnose",
    response_model=DiagnoseResponse,
    summary="Diagnose an equipment issue from a text description",
    description=(
        "Retrieval-Augmented Generation. (1) Embeds the description and retrieves the 3 most "
        "similar past cases from the vector database. (2) If the best match is close enough, "
        "those cases are given to a local LLM (Ollama) as *reference examples*; if not, the LLM "
        "diagnoses from general knowledge and `note` says so. (3) The LLM writes a new, tailored "
        "`diagnosis` and `recommended_action`. `similar_cases` shows what was retrieved and "
        "`confidence_score` is the retrieval similarity. The call is stored as a ticket "
        "(see `/history`), unless the LLM judges that the input is not an equipment issue "
        "(`is_valid_issue: false`), in which case nothing is stored. Expect a few seconds "
        "per call (up to a couple of minutes if the model has to be loaded first)."
    ),
    responses={
        422: {"model": ErrorResponse, "description": "Invalid request body."},
        502: {"model": ErrorResponse, "description": "The LLM returned an unusable response."},
        503: {
            "model": ErrorResponse,
            "description": "Knowledge base not seeded, or the LLM (Ollama) is unavailable.",
        },
        500: {"model": ErrorResponse, "description": "Unexpected server error."},
    },
)
def diagnose(
    payload: DiagnoseRequest,
    diagnosis_service: DiagnosisServiceDep,
    tickets: TicketServiceDep,
) -> DiagnoseResponse:
    # `def` (not `async def`): embedding, vector search and the LLM call are all
    # blocking. FastAPI runs sync handlers in a thread pool, so the event loop stays free.
    result = diagnosis_service.diagnose(payload.description)

    # Input that is not an equipment problem is answered but never stored, so it
    # cannot pollute the ticket history.
    ticket_id = None
    if result.is_valid_issue:
        ticket_id = tickets.create_ticket(
            source="text",
            description=payload.description,
            severity=result.severity,
            diagnosis=result.diagnosis,
            recommended_action=result.recommended_action,
            confidence_score=result.confidence_score,
            similar_cases=result.similar_cases,
        ).id
    return DiagnoseResponse(
        is_valid_issue=result.is_valid_issue,
        ticket_id=ticket_id,
        severity=result.severity,
        diagnosis=result.diagnosis,
        recommended_action=result.recommended_action,
        confidence_score=result.confidence_score,
        similar_cases=result.similar_cases,
        diagnosis_basis=result.diagnosis_basis,
        note=result.note,
    )


@router.post(
    "/diagnose-image",
    response_model=ImageDiagnoseResponse,
    summary="Diagnose an equipment issue from a photo (PLACEHOLDER model)",
    description=(
        "**Placeholder endpoint.** Accepts a JPEG/PNG/WebP photo and returns a result from a "
        "stand-in model that does *not* analyse the image (`is_placeholder` is `true`). "
        "The endpoint is wired to the `VisionService` interface, so a real CNN can replace "
        "the placeholder without changing this API."
    ),
    responses={
        413: {"model": ErrorResponse, "description": "Image too large."},
        415: {"model": ErrorResponse, "description": "Not a JPEG/PNG/WebP image."},
        422: {"model": ErrorResponse, "description": "Missing or empty file."},
        500: {"model": ErrorResponse, "description": "Unexpected server error."},
    },
)
def diagnose_image(
    file: Annotated[UploadFile, File(description="Photo of the faulty equipment (JPEG, PNG or WebP).")],
    settings: SettingsDep,
    vision_service: VisionServiceDep,
    tickets: TicketServiceDep,
) -> ImageDiagnoseResponse:
    # Read at most limit+1 bytes: enough to detect "too big" without loading a huge upload.
    data = file.file.read(settings.max_image_size_bytes + 1)
    image_format = validate_image_bytes(data, settings.max_image_size_bytes)

    prediction = vision_service.analyze(data)
    logger.info(
        "image_diagnosis_completed",
        extra={
            "image_format": image_format,
            "image_bytes": len(data),
            "label": prediction.label,
            "confidence": prediction.confidence,
            "model": prediction.model_name,
        },
    )

    prefix = "[PLACEHOLDER] " if prediction.is_placeholder else ""
    diagnosis = f"{prefix}Visual pattern resembling: {prediction.label}"
    ticket = tickets.create_ticket(
        source="image",
        description=f"[image upload] {file.filename or 'unnamed'}",
        severity=prediction.severity,
        diagnosis=diagnosis,
        recommended_action=prediction.recommended_action,
        confidence_score=prediction.confidence,
    )
    return ImageDiagnoseResponse(
        ticket_id=ticket.id,
        severity=prediction.severity,
        diagnosis=diagnosis,
        recommended_action=prediction.recommended_action,
        confidence_score=prediction.confidence,
        model_name=prediction.model_name,
        is_placeholder=prediction.is_placeholder,
    )
