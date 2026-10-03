"""Diagnosis endpoints. Handlers stay thin: validate -> call services -> shape response."""

import logging
from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from fastapi import Depends

from app.api.deps import (
    DiagnosisServiceDep,
    SessionServiceDep,
    SettingsDep,
    TicketServiceDep,
    VisionServiceDep,
    enforce_rate_limit,
)
from app.schemas.common import ErrorResponse
from app.schemas.diagnosis import DiagnoseRequest, DiagnoseResponse, ImageDiagnoseResponse
from app.services.session_service import diagnose_response_for
from app.services.vision_service import MEDIA_TYPES, validate_image_bytes

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Diagnosis"])


@router.post(
    "/diagnose",
    dependencies=[Depends(enforce_rate_limit)],
    response_model=DiagnoseResponse,
    summary="Diagnose an equipment issue from a text description",
    description=(
        "Retrieval-Augmented Generation. (1) Embeds the description and retrieves the 3 most "
        "similar past cases from the vector database. (2) If the best match is close enough, "
        "those cases are given to a local LLM (Ollama) as *reference examples*; if not, the LLM "
        "diagnoses from general knowledge and `note` says so. (3) The LLM writes a new, tailored "
        "`diagnosis` and `recommended_action`. `similar_cases` shows what was retrieved and "
        "`retrieval_confidence` is the retrieval similarity and `llm_confidence` is the model's own "
        "certainty in its diagnosis. Any physical device or machine is accepted, not just the "
        "categories in the knowledge base. The call is stored as a ticket "
        "(see `/history`) and starts a **diagnosis session**: the response carries a `session_id`, "
        "and `POST /api/v1/sessions/{session_id}/feedback` says whether the solution worked "
        "(if not, a different one is generated). If the LLM judges that the input is not an "
        "equipment issue (`is_valid_issue: false`) nothing is stored and there is no session. "
        "Expect a few seconds per call (up to a couple of minutes if the model has to be loaded first)."
    ),
    responses={
        422: {"model": ErrorResponse, "description": "Invalid request body."},
        429: {"model": ErrorResponse, "description": "Too many requests from this client; see the Retry-After header."},
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
    sessions: SessionServiceDep,
) -> DiagnoseResponse:
    # `def` (not `async def`): embedding, vector search and the LLM call are all
    # blocking. FastAPI runs sync handlers in a thread pool, so the event loop stays free.
    result = diagnosis_service.diagnose(payload.description)

    # Input that is not an equipment problem is answered but never stored (no ticket, no session),
    # so it cannot pollute the history.
    if not result.is_valid_issue:
        return diagnose_response_for(result, ticket_id=None, session_id=None, attempt_number=None, max_attempts=None)

    ticket, session, attempt = sessions.start(
        description=payload.description, equipment_type=payload.equipment_type, result=result
    )
    return diagnose_response_for(
        result,
        ticket_id=ticket.id,
        session_id=session.session_id,
        attempt_number=attempt.attempt_number,
        max_attempts=sessions.max_attempts,
    )


@router.post(
    "/diagnose-image",
    dependencies=[Depends(enforce_rate_limit)],
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
        429: {"model": ErrorResponse, "description": "Too many requests from this client; see the Retry-After header."},
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
