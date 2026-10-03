"""Diagnosis endpoints. Handlers stay thin: validate -> call services -> shape response."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import ValidationError
from starlette.datastructures import Headers
from starlette.routing import Match

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
from app.services.diagnosis_service import DiagnosisResult
from app.services.session_service import SessionService, diagnose_response_for
from app.services.vision_service import MEDIA_TYPES, describe_photo_for_diagnosis, validate_image_bytes

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Diagnosis"])


class MultipartOnlyRoute(APIRoute):
    """A route that only matches ``multipart/form-data`` requests.

    It lets ONE URL (POST /diagnose) serve two kinds of request without touching the existing one: this
    route, registered first, takes the multipart upload (description + optional photo); every other request
    falls through to the plain JSON route, which is exactly the route that existed before photos.
    """

    def matches(self, scope):
        match, child_scope = super().matches(scope)
        if match != Match.NONE and not Headers(scope=scope).get("content-type", "").lower().startswith("multipart/form-data"):
            return Match.NONE, {}
        return match, child_scope


def _respond(
    result: DiagnosisResult, payload: DiagnoseRequest, sessions: SessionService, image_note: str | None = None
) -> DiagnoseResponse:
    """Store a valid diagnosis (ticket + session) and shape the response; shared by both /diagnose routes."""
    # Input that is not an equipment problem is answered but never stored (no ticket, no session),
    # so it cannot pollute the history.
    if not result.is_valid_issue:
        return diagnose_response_for(
            result, ticket_id=None, session_id=None, attempt_number=None, max_attempts=None, image_note=image_note
        )

    ticket, session, attempt = sessions.start(
        description=payload.description, equipment_type=payload.equipment_type, result=result
    )
    return diagnose_response_for(
        result,
        ticket_id=ticket.id,
        session_id=session.session_id,
        attempt_number=attempt.attempt_number,
        max_attempts=sessions.max_attempts,
        image_note=image_note,
    )


def _validated_form(description: str | None, equipment_type: str | None) -> DiagnoseRequest:
    """Validate the multipart text fields with the SAME model as the JSON body, and fail the same way (422)."""
    fields = {"description": description, "equipment_type": equipment_type}
    try:
        # A field that was not sent is omitted (not None), so a missing description says "Field required".
        return DiagnoseRequest.model_validate({k: v for k, v in fields.items() if v is not None})
    except ValidationError as exc:
        # Same shape FastAPI builds for a JSON body: loc is ("body", <field>), which the shared handler formats.
        raise RequestValidationError([{**err, "loc": ("body", *err["loc"])} for err in exc.errors(include_url=False)]) from exc


# Documents the multipart variant on the JSON route's Swagger entry (the multipart route itself is hidden,
# because two operations cannot share one path + method in an OpenAPI document).
_MULTIPART_DOCS = {
    "requestBody": {
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["description"],
                    "properties": {
                        "description": {
                            "type": "string",
                            "minLength": 10,
                            "maxLength": 2000,
                            "description": "Free-text description of the problem (10-2000 characters).",
                        },
                        "equipment_type": {"type": "string", "maxLength": 64, "description": "Optional kind of equipment."},
                        "image": {
                            "type": "string",
                            "format": "binary",
                            "description": "Optional photo (JPEG, PNG or WebP, up to 5 MB). A vision model describes it and the "
                            "findings go into the same LLM call as the description.",
                        },
                    },
                }
            }
        }
    }
}


def diagnose_with_photo(
    diagnosis_service: DiagnosisServiceDep,
    sessions: SessionServiceDep,
    vision_service: VisionServiceDep,
    settings: SettingsDep,
    description: Annotated[str | None, Form(description="Description of the problem (10-2000 characters).")] = None,
    equipment_type: Annotated[str | None, Form(description="Optional kind of equipment.")] = None,
    image: Annotated[UploadFile | None, File(description="Optional photo of the equipment (JPEG, PNG or WebP).")] = None,
) -> DiagnoseResponse:
    """The multipart variant of POST /diagnose: a description plus an optional photo, as ONE diagnosis."""
    payload = _validated_form(description, equipment_type)

    findings, image_note = None, None
    if image is not None:
        # Read at most limit+1 bytes: enough to detect "too big" without loading a huge upload.
        data = image.file.read(settings.max_image_size_bytes + 1)
        # A browser form whose file box was left empty still sends an (empty, nameless) file part: no photo.
        if data or image.filename:
            media_type = MEDIA_TYPES[validate_image_bytes(data, settings.max_image_size_bytes)]  # 415 / 413 / 422
            findings, image_note = describe_photo_for_diagnosis(vision_service, data, media_type)
            logger.info(
                "photo_attached_to_diagnosis",
                extra={"image_bytes": len(data), "photo_used": findings is not None},  # never the image itself
            )

    # The photo's findings are passed only when there are some, so a text-only request makes exactly the
    # same call as the JSON route.
    photo = {"image_findings": findings} if findings is not None else {}
    result = diagnosis_service.diagnose(payload.description, **photo)
    return _respond(result, payload, sessions, image_note)


router.add_api_route(
    "/diagnose",
    diagnose_with_photo,
    methods=["POST"],
    route_class_override=MultipartOnlyRoute,
    dependencies=[Depends(enforce_rate_limit)],  # the same shared allowance as every other AI endpoint
    response_model=DiagnoseResponse,
    include_in_schema=False,
    responses={
        413: {"model": ErrorResponse, "description": "Image too large."},
        415: {"model": ErrorResponse, "description": "Not a JPEG/PNG/WebP image."},
        422: {"model": ErrorResponse, "description": "Invalid fields, or an empty/unreadable image."},
        429: {"model": ErrorResponse, "description": "Too many requests from this client; see the Retry-After header."},
    },
)


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
        "**Optionally attach a photo:** send the same request as `multipart/form-data` with the fields "
        "`description`, `equipment_type` and `image` (JPEG/PNG/WebP). A vision model describes the photo and "
        "its findings go into the SAME LLM call as the description, so the result is ONE diagnosis based on "
        "both: `input_sources` is `[\"text\", \"image\"]` and `image_analysis` shows what the photo "
        "contributed. If the photo is not equipment or image analysis is unavailable, the diagnosis goes "
        "ahead on the description alone and `image_note` says why. A JSON request behaves exactly as before. "
        "Expect a few seconds per call (up to a couple of minutes if the model has to be loaded first)."
    ),
    openapi_extra=_MULTIPART_DOCS,
    responses={
        413: {"model": ErrorResponse, "description": "(Multipart only) the photo is too large."},
        415: {"model": ErrorResponse, "description": "(Multipart only) the photo is not a JPEG/PNG/WebP image."},
        422: {"model": ErrorResponse, "description": "Invalid request body, or an empty/unreadable photo."},
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
    return _respond(result, payload, sessions)


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
