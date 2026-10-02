"""Ticket history and technician feedback."""

from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import TicketServiceDep
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
    summary="Tell the system whether a diagnosis was correct",
    description=(
        "Stores the technician's verdict for a ticket. Submitting feedback for the same "
        "ticket again updates the earlier answer (returns 200 instead of 201)."
    ),
    responses={
        200: {"model": FeedbackResponse, "description": "Existing feedback updated."},
        404: {"model": ErrorResponse, "description": "Ticket does not exist."},
        422: {"model": ErrorResponse, "description": "Invalid request body."},
    },
)
def submit_feedback(
    payload: FeedbackRequest, response: Response, tickets: TicketServiceDep
) -> FeedbackResponse:
    feedback, created = tickets.save_feedback(payload.ticket_id, payload.was_correct)
    if not created:
        response.status_code = status.HTTP_200_OK
    return FeedbackResponse.model_validate(feedback)
