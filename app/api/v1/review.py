"""Human-in-the-loop review: confirm or correct a diagnosis, and see how the knowledge base grows."""

from typing import Annotated

from fastapi import APIRouter, Body, Depends

from app.api.deps import KnowledgeBaseDep, ReviewServiceDep, require_technician_code
from app.models.ticket import Ticket
from app.schemas.common import ErrorResponse
from app.schemas.review import ConfirmRequest, CorrectRequest, KnowledgeBaseStats, ReviewResponse

router = APIRouter(tags=["Review & Knowledge Base"])

_REVIEW_ERRORS = {
    401: {
        "model": ErrorResponse,
        "description": "A technician access code is required (X-Technician-Code header) and it was missing or wrong. "
        "Only when the server has TECHNICIAN_ACCESS_CODE set.",
    },
    404: {"model": ErrorResponse, "description": "Ticket does not exist."},
    409: {"model": ErrorResponse, "description": "Not allowed from the ticket's current review status."},
    422: {"model": ErrorResponse, "description": "Invalid request body."},
    503: {"model": ErrorResponse, "description": "The knowledge base could not be updated; nothing was saved."},
}


def _response(ticket: Ticket, knowledge_base: KnowledgeBaseDep) -> ReviewResponse:
    return ReviewResponse(
        ticket_id=ticket.id,
        review_status=ticket.review_status,
        review_priority=ticket.review_priority,
        reviewed_at=ticket.reviewed_at,
        corrected_root_cause=ticket.corrected_root_cause,
        corrected_fix=ticket.corrected_fix,
        added_to_knowledge_base=ticket.kb_record_id is not None,
        kb_record_id=ticket.kb_record_id,
        verification=ticket.fix_verification,
        confirmation_count=ticket.confirmation_count,
        knowledge_base=knowledge_base.stats(),
    )


@router.post(
    "/tickets/{ticket_id}/confirm",
    dependencies=[Depends(require_technician_code)],  # technician action: needs X-Technician-Code when configured
    response_model=ReviewResponse,
    summary="Confirm that the AI's diagnosis was correct",
    description=(
        "Marks the ticket `confirmed` and adds the original AI diagnosis to the knowledge base as a "
        "`verified` record, so future similar reports can retrieve it. A technician's review counts as two "
        "confirmations, so it verifies the fix; on a fix an end user already confirmed (still `provisional`) it "
        "upgrades the SAME record to `verified`. Confirming twice is harmless. "
        "A ticket that was already corrected cannot be confirmed (409). **Technician action:** when the server has "
        "`TECHNICIAN_ACCESS_CODE` set, the `X-Technician-Code` header must match it (401 otherwise)."
    ),
    responses=_REVIEW_ERRORS,
)
def confirm_ticket(
    ticket_id: int,
    review: ReviewServiceDep,
    knowledge_base: KnowledgeBaseDep,
    payload: Annotated[ConfirmRequest | None, Body()] = None,
) -> ReviewResponse:
    ticket = review.confirm(ticket_id, payload.equipment_type if payload else None)
    return _response(ticket, knowledge_base)


@router.post(
    "/tickets/{ticket_id}/correct",
    dependencies=[Depends(require_technician_code)],  # technician action: needs X-Technician-Code when configured
    response_model=ReviewResponse,
    summary="Correct a diagnosis with the real root cause and fix",
    description=(
        "Marks the ticket `corrected`, stores the technician's root cause and fix **next to** the "
        "original AI diagnosis (which is kept for comparison), and adds the *corrected* case to the "
        "knowledge base as a `verified` record. Allowed from any status; correcting again edits the "
        "existing record. **Technician action:** when the server has `TECHNICIAN_ACCESS_CODE` set, the "
        "`X-Technician-Code` header must match it (401 otherwise)."
    ),
    responses=_REVIEW_ERRORS,
)
def correct_ticket(
    ticket_id: int,
    payload: CorrectRequest,
    review: ReviewServiceDep,
    knowledge_base: KnowledgeBaseDep,
) -> ReviewResponse:
    ticket = review.correct(ticket_id, payload.root_cause, payload.recommended_fix, payload.equipment_type)
    return _response(ticket, knowledge_base)


@router.get(
    "/knowledge-base/stats",
    response_model=KnowledgeBaseStats,
    summary="How many knowledge-base records are seed, verified, provisional or failed",
    description="Makes the growth of the knowledge base visible: seed records ship with the system, "
    "verified records are confirmed fixes with enough confirmations, provisional ones were confirmed only once "
    "(an end user's click) and failed ones were reported not to work.",
    responses={503: {"model": ErrorResponse, "description": "The knowledge base is unavailable."}},
)
def knowledge_base_stats(knowledge_base: KnowledgeBaseDep) -> KnowledgeBaseStats:
    return knowledge_base.stats()
