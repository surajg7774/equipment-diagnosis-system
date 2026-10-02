"""Diagnosis endpoints. Handlers stay thin: validate -> call services -> shape response."""

import logging
from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from app.api.deps import DiagnosisServiceDep, SettingsDep, TicketServiceDep, VisionServiceDep
from app.schemas.common import ErrorResponse
from app.schemas.diagnosis import DiagnoseRequest, DiagnoseResponse, ImageDiagnoseResponse
from app.services.vision_service import MEDIA_TYPES, validate_image_bytes

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
        "`retrieval_confidence` is the retrieval similarity and `llm_confidence` is the model's own "
        "certainty in its diagnosis. The call is stored as a ticket "
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
            confidence_score=result.retrieval_confidence,  # stored value: retrieval similarity
            similar_cases=result.similar_cases,
        ).id
    return DiagnoseResponse(
        is_valid_issue=result.is_valid_issue,
        ticket_id=ticket_id,
        severity=result.severity,
        diagnosis=result.diagnosis,
        recommended_action=result.recommended_action,
        retrieval_confidence=result.retrieval_confidence,
        llm_confidence=result.llm_confidence,
        llm_confidence_defaulted=result.llm_confidence_defaulted,
        confidence_score=result.retrieval_confidence,  # deprecated alias
        similar_cases=result.similar_cases,
        diagnosis_basis=result.diagnosis_basis,
        note=result.note,
    )


@router.post(
    "/diagnose-image",
    response_model=ImageDiagnoseResponse,
    summary="AI visual assessment of an equipment photo",
    description=(
        "Sends a JPEG/PNG/WebP photo to a vision-language model, which describes any visible "
        "damage, wear, leaks, corrosion or abnormal conditions and rates the severity. The result "
        "is stored as a ticket, unless the photo does not show equipment (`is_equipment_photo: "
        "false`). **AI-generated visual assessment: a general-purpose model, not a substitute for "
        "professional inspection.** The free Groq tier allows only about 3 images per minute."
    ),
    responses={
        413: {"model": ErrorResponse, "description": "Image too large."},
        415: {"model": ErrorResponse, "description": "Not a JPEG/PNG/WebP image."},
        422: {"model": ErrorResponse, "description": "Missing, empty or unreadable image."},
        502: {"model": ErrorResponse, "description": "The vision model returned an unusable result."},
        503: {"model": ErrorResponse, "description": "Image analysis unavailable, disabled or rate limited."},
        500: {"model": ErrorResponse, "description": "Unexpected server error."},
    },
)
def diagnose_image(
    file: Annotated[UploadFile, File(description="Photo of the equipment (JPEG, PNG or WebP).")],
    settings: SettingsDep,
    vision_service: VisionServiceDep,
    tickets: TicketServiceDep,
) -> ImageDiagnoseResponse:
    # Read at most limit+1 bytes: enough to detect "too big" without loading a huge upload.
    data = file.file.read(settings.max_image_size_bytes + 1)
    image_format = validate_image_bytes(data, settings.max_image_size_bytes)

    analysis = vision_service.analyze(data, MEDIA_TYPES[image_format])

    ticket_id = None
    note = None
    if analysis.is_equipment_photo:
        ticket_id = tickets.create_ticket(
            source="image",
            # The filename is client-controlled: cap it before it is stored.
            description=f"[image upload] {(file.filename or 'unnamed')[:120]}",
            severity=analysis.severity,
            diagnosis=analysis.description,
            recommended_action=analysis.recommended_action,
            # Tickets need a number; when the model gave none use the neutral 0.5 (as for text).
            confidence_score=0.5 if analysis.confidence is None else analysis.confidence,
        ).id
    else:
        note = "This photo does not appear to show equipment, so it was not saved to ticket history."

    return ImageDiagnoseResponse(
        is_equipment_photo=analysis.is_equipment_photo,
        ticket_id=ticket_id,
        damage_detected=analysis.damage_detected,
        severity=analysis.severity if analysis.is_equipment_photo else None,
        description=analysis.description,
        recommended_action=analysis.recommended_action,
        confidence=analysis.confidence,
        model_name=analysis.model_name,
        provider=analysis.provider,
        note=note,
    )
