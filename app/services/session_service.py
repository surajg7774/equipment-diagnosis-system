"""Iterative diagnosis sessions: "try a solution, give feedback, get the next one".

    POST /diagnose                      -> session (in_progress) + attempt 1
    POST /sessions/{id}/feedback  yes   -> session resolved (+ maybe added to the knowledge base)
                                  no    -> attempt 2, 3, ... each told what already failed
                                  no, at the cap -> session abandoned: "escalate to a human"

The ticket stays the unit of history, review and statistics: the FIRST attempt creates it exactly as
before, and the session hangs off it. Later attempts live only in ``SolutionAttempt`` rows.

A "no" is only saved together with the new attempt it produces (one commit). If the LLM fails in
between, nothing is written and the user can simply press "No" again.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    KnowledgeBaseUpdateError,
    SessionConflictError,
    SessionNotFoundError,
)
from app.models.ticket import DiagnosisSession, SolutionAttempt, Ticket
from app.schemas.diagnosis import DiagnoseResponse, ImageFindings
from app.schemas.enums import DiagnosisBasis, ReviewStatus, SessionStatus
from app.services.diagnosis_service import DiagnosisResult, DiagnosisService
from app.services.llm_service import PreviousAttempt
from app.services.review_service import ReviewService
from app.services.ticket_service import TicketService

logger = logging.getLogger(__name__)

# A "yes" only feeds the knowledge base when the solution was reasonably trustworthy: it was grounded
# in similar past cases, or the model itself was at least this sure. A shaky guess that happened to
# work once is not something to teach the system.
TRUSTED_LLM_CONFIDENCE = 0.6


@dataclass
class FeedbackOutcome:
    session: DiagnosisSession
    rated_attempt: SolutionAttempt  # the attempt the user just answered about
    message: str | None
    escalate: bool = False
    added_to_knowledge_base: bool = False
    next_result: DiagnosisResult | None = None  # the new solution, when "no" produced one
    next_attempt: SolutionAttempt | None = None


def is_trusted_solution(attempt: SolutionAttempt) -> bool:
    """Whether a solution that worked is solid enough to add to the knowledge base."""
    return attempt.diagnosis_basis == DiagnosisBasis.SIMILAR_CASES.value or (
        attempt.llm_confidence is not None and attempt.llm_confidence >= TRUSTED_LLM_CONFIDENCE
    )


def diagnose_response_for(
    result: DiagnosisResult,
    *,
    ticket_id: int | None,
    session_id: str | None,
    attempt_number: int | None,
    max_attempts: int | None,
    image_note: str | None = None,
) -> DiagnoseResponse:
    """The API shape of one diagnosis (first attempt or follow-up).

    ``input_sources`` says what the diagnosis was really based on: the description, plus the photo when
    its findings went into the LLM call. ``image_note`` explains a photo that was attached but not used.
    """
    return DiagnoseResponse(
        input_sources=["text", "image"] if result.image_findings is not None else ["text"],
        image_analysis=result.image_findings,
        image_note=image_note,
        is_valid_issue=result.is_valid_issue,
        ticket_id=ticket_id,
        session_id=session_id,
        attempt_number=attempt_number,
        max_attempts=max_attempts,
        severity=result.severity,
        diagnosis=result.diagnosis,
        recommended_action=result.recommended_action,
        retrieval_confidence=result.retrieval_confidence,
        llm_confidence=result.llm_confidence,
        llm_confidence_defaulted=result.llm_confidence_defaulted,
        confidence_score=result.retrieval_confidence,  # deprecated alias
        similar_cases=result.similar_cases,
        similar_failed_cases=result.failed_cases,
        diagnosis_basis=result.diagnosis_basis,
        note=result.note,
    )


def _attempt_from(result: DiagnosisResult, number: int) -> SolutionAttempt:
    assert result.severity is not None  # only valid issues become attempts
    return SolutionAttempt(
        attempt_number=number,
        diagnosis=result.diagnosis,
        recommended_action=result.recommended_action,
        severity=result.severity,
        diagnosis_basis=result.diagnosis_basis.value,
        retrieval_confidence=result.retrieval_confidence,
        # Only the model's real number: a defaulted 0.5 would pass for certainty it never expressed.
        llm_confidence=None if result.llm_confidence_defaulted else result.llm_confidence,
        similar_cases=[c.model_dump(mode="json") for c in result.similar_cases],
        note=result.note,
    )


class SessionService:
    def __init__(
        self,
        db: Session,
        diagnosis: DiagnosisService,
        tickets: TicketService,
        reviews: ReviewService,
        max_attempts: int,
    ) -> None:
        self._db = db
        self._diagnosis = diagnosis
        self._tickets = tickets
        self._reviews = reviews
        self._max_attempts = max_attempts

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    # ---------------------------------------------------------------------------------------------
    def start(
        self, *, description: str, equipment_type: str | None, result: DiagnosisResult
    ) -> tuple[Ticket, DiagnosisSession, SolutionAttempt]:
        """Store a valid first diagnosis: the ticket (as before) plus a new session with attempt 1."""
        ticket = self._tickets.create_ticket(
            source="text",
            description=description,
            severity=result.severity,
            diagnosis=result.diagnosis,
            recommended_action=result.recommended_action,
            confidence_score=result.retrieval_confidence,  # stored value: retrieval similarity
            similar_cases=result.similar_cases,
            diagnosis_basis=result.diagnosis_basis.value,
            llm_confidence=None if result.llm_confidence_defaulted else result.llm_confidence,
        )
        session = DiagnosisSession(
            ticket_id=ticket.id,
            original_description=description,
            equipment_type=(equipment_type or "").strip() or None,
            status=SessionStatus.IN_PROGRESS,
            image_findings=result.image_findings.model_dump(mode="json") if result.image_findings else None,
        )
        attempt = _attempt_from(result, 1)
        session.attempts.append(attempt)
        self._db.add(session)
        self._db.commit()
        logger.info("session_started", extra={"session_id": session.session_id, "ticket_id": ticket.id})
        return ticket, session, attempt

    # ---------------------------------------------------------------------------------------------
    def give_feedback(
        self,
        session_id: str,
        was_helpful: bool,
        attempt_number: int | None = None,
        before_new_attempt: Callable[[], None] | None = None,
    ) -> FeedbackOutcome:
        """Record whether the latest solution worked, and act on it.

        ``before_new_attempt`` runs just before a new LLM call (the API uses it to apply the rate
        limit only to the answers that actually cost quota).
        """
        session = self._db.get(DiagnosisSession, session_id)
        if session is None:
            raise SessionNotFoundError(f"Session {session_id} does not exist.")
        latest = session.latest_attempt
        assert latest is not None  # a session is never created without its first attempt

        if attempt_number is not None and attempt_number != latest.attempt_number:
            raise SessionConflictError(
                f"That answer is about attempt {attempt_number}, but the session is already on attempt "
                f"{latest.attempt_number}. Reload to see the current solution."
            )

        if session.status != SessionStatus.IN_PROGRESS:
            return self._repeat_of_closed_session(session, latest, was_helpful)

        if was_helpful:
            return self._resolve(session, latest)
        return self._try_next_solution(session, latest, before_new_attempt)

    # ---------------------------------------------------------------------------------------------
    def _resolve(self, session: DiagnosisSession, latest: SolutionAttempt) -> FeedbackOutcome:
        latest.was_helpful = True
        session.status = SessionStatus.RESOLVED
        session.resolved_at = datetime.now(timezone.utc)
        self._db.commit()
        logger.info(
            "session_resolved",
            extra={"session_id": session.session_id, "attempts": session.attempt_count},
        )
        added = self._maybe_add_to_knowledge_base(session, latest)
        return FeedbackOutcome(
            session=session,
            rated_attempt=latest,
            message=self._resolved_message(session),
            added_to_knowledge_base=added,
        )

    @staticmethod
    def _resolved_message(session: DiagnosisSession) -> str:
        count = session.attempt_count
        return f"Resolved after {count} attempt{'s' if count != 1 else ''}. Glad that fixed it!"

    def _maybe_add_to_knowledge_base(self, session: DiagnosisSession, winner: SolutionAttempt) -> bool:
        """Feed a trusted, working solution into the existing human-in-the-loop knowledge-base logic.

        Attempt 1 is what the ticket already says, so it is a plain *confirmation*. A later attempt
        differs from the ticket, so it is recorded as a *correction* carrying that attempt's text.
        A ticket a technician already reviewed is left alone. The session is already resolved at this
        point, so a vector-store failure is logged and reported, not raised.
        """
        ticket = session.ticket
        if ticket is None or ticket.review_status != ReviewStatus.PENDING:
            return False
        if not is_trusted_solution(winner):
            logger.info("session_solution_not_trusted", extra={"session_id": session.session_id})
            return False
        try:
            if winner.attempt_number == 1:
                self._reviews.confirm(ticket.id, session.equipment_type)
            else:
                self._reviews.correct(ticket.id, winner.diagnosis, winner.recommended_action, session.equipment_type)
        except KnowledgeBaseUpdateError:
            logger.warning("session_knowledge_base_add_failed", extra={"session_id": session.session_id})
            return False
        return True

    def _try_next_solution(
        self,
        session: DiagnosisSession,
        latest: SolutionAttempt,
        before_new_attempt: Callable[[], None] | None,
    ) -> FeedbackOutcome:
        latest.was_helpful = False  # in memory only until the whole step commits

        if latest.attempt_number >= self._max_attempts:
            session.status = SessionStatus.ABANDONED
            self._db.commit()
            logger.info("session_escalated", extra={"session_id": session.session_id, "attempts": session.attempt_count})
            return FeedbackOutcome(session=session, rated_attempt=latest, message=self._escalation_message(session), escalate=True)

        if before_new_attempt:
            before_new_attempt()
        previous = [PreviousAttempt(a.attempt_number, a.diagnosis, a.recommended_action) for a in session.attempts]
        # A session that began with a photo keeps weighing that same photo on every later attempt (only
        # passed when there is one, so a text-only session calls diagnose() exactly as before).
        photo = {"image_findings": ImageFindings.model_validate(session.image_findings)} if session.image_findings else {}
        result = self._diagnosis.diagnose(session.original_description, previous, **photo)

        new_attempt = _attempt_from(result, latest.attempt_number + 1)
        session.attempts.append(new_attempt)
        try:
            self._db.commit()
        except IntegrityError as exc:  # two "No"s raced: the database refused the duplicate attempt number
            self._db.rollback()
            raise SessionConflictError("This session just moved on to its next solution. Reload to see it.") from exc
        logger.info(
            "session_next_attempt",
            extra={"session_id": session.session_id, "attempt_number": new_attempt.attempt_number},
        )
        return FeedbackOutcome(
            session=session,
            rated_attempt=latest,
            message=None,
            next_result=result,
            next_attempt=new_attempt,
        )

    def _escalation_message(self, session: DiagnosisSession) -> str:
        return (
            f"None of the {session.attempt_count} suggested solutions worked. "
            "Please escalate this to a qualified human technician."
        )

    def _repeat_of_closed_session(self, session: DiagnosisSession, latest: SolutionAttempt, was_helpful: bool) -> FeedbackOutcome:
        """Answering a finished session: a repeat of the same answer is harmless, anything else is a conflict."""
        if session.status == SessionStatus.RESOLVED and was_helpful and latest.was_helpful is True:
            return FeedbackOutcome(session=session, rated_attempt=latest, message=self._resolved_message(session))
        if session.status == SessionStatus.ABANDONED and not was_helpful and latest.was_helpful is False:
            return FeedbackOutcome(
                session=session, rated_attempt=latest, message=self._escalation_message(session), escalate=True
            )
        raise SessionConflictError(f"This session is already {session.status.value}.")
