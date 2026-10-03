"""Iterative diagnosis: say whether the solution worked and, if not, get a different one."""

from fastapi import APIRouter, Request

from app.api.deps import SessionServiceDep, check_rate_limit
from app.schemas.common import ErrorResponse
from app.schemas.enums import SessionStatus
from app.schemas.session import SessionFeedbackRequest, SessionFeedbackResponse
from app.services.session_service import diagnose_response_for

router = APIRouter(tags=["Diagnosis sessions"])


@router.post(
    "/sessions/{session_id}/feedback",
    response_model=SessionFeedbackResponse,
    summary="Did the latest solution work? If not, get a different one",
    description=(
        "`was_helpful: true` marks the session resolved (and, if the solution was reasonably trusted, "
        "adds it to the knowledge base). `was_helpful: false` generates a NEW solution for the same "
        "original description; the earlier failed attempts are passed to the LLM so it must propose a "
        "different cause and fix. After the maximum number of attempts the session is closed with "
        "`escalate: true` instead of looping. Only a `false` answer that triggers a new LLM call counts "
        "against the rate limit."
    ),
    responses={
        404: {"model": ErrorResponse, "description": "Unknown session."},
        409: {
            "model": ErrorResponse,
            "description": "The session is already closed, or the answer is about an attempt that is no longer the latest.",
        },
        429: {"model": ErrorResponse, "description": "Too many requests from this client; see the Retry-After header."},
        502: {"model": ErrorResponse, "description": "The LLM returned an unusable answer (nothing was saved; try again)."},
        503: {"model": ErrorResponse, "description": "The LLM is unavailable (nothing was saved; try again)."},
    },
)
def session_feedback(
    session_id: str,
    payload: SessionFeedbackRequest,
    request: Request,
    sessions: SessionServiceDep,
) -> SessionFeedbackResponse:
    outcome = sessions.give_feedback(
        session_id,
        payload.was_helpful,
        payload.attempt_number,
        before_new_attempt=lambda: check_rate_limit(request),
    )
    session = outcome.session
    next_attempt = None
    if outcome.next_result is not None and outcome.next_attempt is not None:
        next_attempt = diagnose_response_for(
            outcome.next_result,
            ticket_id=session.ticket_id,
            session_id=session.session_id,
            attempt_number=outcome.next_attempt.attempt_number,
            max_attempts=sessions.max_attempts,
        )
    return SessionFeedbackResponse(
        session_id=session.session_id,
        status=session.status,
        resolved=session.status == SessionStatus.RESOLVED,
        escalate=outcome.escalate,
        attempt_number=outcome.rated_attempt.attempt_number,
        max_attempts=sessions.max_attempts,
        message=outcome.message,
        added_to_knowledge_base=outcome.added_to_knowledge_base,
        next_attempt=next_attempt,
    )
