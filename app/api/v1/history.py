"""Ticket history and technician feedback."""

from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import FeedbackServiceDep, TicketServiceDep
from app.schemas.common import ErrorResponse
from app.schemas.enums import ReviewStatus
from app.schemas.history import FeedbackRequest, FeedbackResponse, HistoryItem, HistoryPage

router = APIRouter(tags=["History & Feedback"])


@router.get(
    "/history",
    response_model=HistoryPage,
    summary="List past diagnosis tickets (paginated, newest first)",
    responses={422: {"model": ErrorResponse, "description": "Invalid pagination parameters."}},
)
def list_history(
    tickets: TicketServiceDep,
    page: Annotated[int, Query(ge=1, description="Page number, starting at 1.")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Items per page (max 100).")] = 20,
    review_status: Annotated[
        ReviewStatus | None,
        Query(description="Only tickets in this review state. 'pending' lists medium/high severity first."),
    ] = None,
) -> HistoryPage:
    items, total, total_pages = tickets.list_tickets(page, page_size, review_status)
    return HistoryPage(
        items=[HistoryItem.model_validate(t) for t in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Thumbs up / down on a diagnosis (teaches the knowledge base)",
    description=(
        "Stores the verdict for a ticket, then teaches the knowledge base. **Thumbs up** "
        "(`was_correct: true`) records the AI's diagnosis as a confirmed fix, like a technician's confirm, "
        "but one end-user click is only one confirmation: it is stored as `provisional_fix` (retrieved, "
        "labelled and ranked lower) until a technician verifies it. **Thumbs down** adds a separate `failed_fix` record of the "
        "diagnosis + fix that did NOT work; it deletes nothing and does not mark the ticket reviewed. "
        "Later diagnoses of similar problems show the LLM both kinds, clearly labelled, so it steers "
        "away from known failures. Submitting feedback for the same ticket again updates the earlier "
        "answer (returns 200 instead of 201). If the vector store is unavailable the verdict is still "
        "saved and `knowledge_base_updated` is false."
    ),
    responses={
        200: {"model": FeedbackResponse, "description": "Existing feedback updated."},
        404: {"model": ErrorResponse, "description": "Ticket does not exist."},
        422: {"model": ErrorResponse, "description": "Invalid request body."},
    },
)
def submit_feedback(
    payload: FeedbackRequest, response: Response, feedback_service: FeedbackServiceDep
) -> FeedbackResponse:
    outcome = feedback_service.submit(payload.ticket_id, payload.was_correct)
    if not outcome.created:
        response.status_code = status.HTTP_200_OK
    feedback = outcome.feedback
    return FeedbackResponse(
        id=feedback.id,
        ticket_id=feedback.ticket_id,
        was_correct=feedback.was_correct,
        created_at=feedback.created_at,
        knowledge_base_outcome=outcome.knowledge_base_outcome,
        knowledge_base_updated=outcome.knowledge_base_updated,
        kb_record_id=outcome.kb_record_id,
        verification=outcome.verification,
        confirmation_count=outcome.confirmation_count,
    )
