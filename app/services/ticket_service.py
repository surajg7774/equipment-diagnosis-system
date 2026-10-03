"""Reads and writes tickets and feedback (the only place that queries the SQL DB)."""

import math

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import TicketNotFoundError
from app.models.ticket import DiagnosisSession, Feedback, SolutionAttempt, Ticket
from app.schemas.enums import ReviewPriority, ReviewStatus, SessionStatus, Severity
from app.schemas.knowledge_base import SimilarCase


def review_priority_for(severity: Severity) -> ReviewPriority:
    """Medium and high severity diagnoses are reviewed first; low severity ones can wait."""
    return ReviewPriority.HIGH if severity in (Severity.MEDIUM, Severity.HIGH) else ReviewPriority.LOW


class TicketService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_ticket(
        self,
        *,
        source: str,
        description: str,
        severity: Severity,
        diagnosis: str,
        recommended_action: str,
        confidence_score: float,
        similar_cases: list[SimilarCase] | None = None,
        diagnosis_basis: str | None = None,
        llm_confidence: float | None = None,
    ) -> Ticket:
        ticket = Ticket(
            source=source,
            description=description,
            severity=severity,
            diagnosis=diagnosis,
            recommended_action=recommended_action,
            confidence_score=confidence_score,
            similar_cases=[c.model_dump(mode="json") for c in similar_cases or []],
            diagnosis_basis=diagnosis_basis,
            llm_confidence=llm_confidence,
            # Every new diagnosis starts "pending"; only the priority depends on severity.
            review_status=ReviewStatus.PENDING,
            review_priority=review_priority_for(severity),
        )
        self._session.add(ticket)
        self._session.commit()
        return ticket

    def list_tickets(
        self, page: int, page_size: int, review_status: ReviewStatus | None = None
    ) -> tuple[list[Ticket], int, int]:
        """Return ``(tickets_on_page, total_count, total_pages)``, newest first.

        With ``review_status`` only tickets in that state are listed. For ``pending`` the ones that
        most need a human look (medium/high severity) come first, then newest first.
        """
        count_query = select(func.count()).select_from(Ticket)
        query = select(Ticket)
        if review_status is not None:
            count_query = count_query.where(Ticket.review_status == review_status)
            query = query.where(Ticket.review_status == review_status)
        order = [Ticket.created_at.desc(), Ticket.id.desc()]  # id breaks ties so pages never overlap
        if review_status == ReviewStatus.PENDING:
            order.insert(0, case((Ticket.review_priority == ReviewPriority.HIGH, 0), else_=1))

        total = self._session.scalar(count_query) or 0
        tickets = self._session.scalars(
            # Load feedback and sessions (with their attempts) for the whole page in a few extra
            # queries, instead of one per row (N+1).
            query.options(
                selectinload(Ticket.feedback),
                selectinload(Ticket.diagnosis_session).selectinload(DiagnosisSession.attempts),
            )
            .order_by(*order)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return list(tickets), total, math.ceil(total / page_size)

    def usage_summary(self) -> dict:
        """Raw usage numbers for /stats, computed with SQL aggregates (no rows loaded into Python)."""
        s = self._session

        def grouped(column, *where):
            query = select(column, func.count()).group_by(column)
            for condition in where:
                query = query.where(condition)
            return {(getattr(key, "value", key)): count for key, count in s.execute(query).all()}

        def average(column, *where):
            query = select(func.avg(column))  # AVG ignores NULLs; None if there are no rows
            for condition in where:
                query = query.where(condition)
            return s.scalar(query)

        # Attempts per RESOLVED session (the winning attempt is the last one, so the count is the number tried).
        attempts_per_resolved = (
            select(func.count(SolutionAttempt.id).label("n"))
            .join(DiagnosisSession, DiagnosisSession.session_id == SolutionAttempt.session_id)
            .where(DiagnosisSession.status == SessionStatus.RESOLVED)
            .group_by(SolutionAttempt.session_id)
            .subquery()
        )

        return {
            "sessions": {
                "by_status": grouped(DiagnosisSession.status),
                "avg_attempts_to_resolve": s.scalar(select(func.avg(attempts_per_resolved.c.n))),
            },
            "total": s.scalar(select(func.count()).select_from(Ticket)) or 0,
            "by_source": grouped(Ticket.source),
            "by_basis": grouped(Ticket.diagnosis_basis, Ticket.diagnosis_basis.is_not(None)),
            "by_review_status": grouped(Ticket.review_status),
            # confidence_score holds the RETRIEVAL similarity for text tickets but the model's own
            # certainty for photo tickets, so the two are averaged separately.
            "avg_retrieval_confidence": average(Ticket.confidence_score, Ticket.source == "text"),
            "avg_llm_confidence": average(Ticket.llm_confidence),
            "avg_image_confidence": average(Ticket.confidence_score, Ticket.source == "image"),
        }

    def save_feedback(self, ticket_id: int, was_correct: bool) -> tuple[Feedback, bool]:
        """Store feedback; returns ``(feedback, created)``.

        If feedback already exists for the ticket it is updated (a technician
        may correct their answer), so ``created`` is False in that case.
        """
        ticket = self._session.get(Ticket, ticket_id)
        if ticket is None:
            raise TicketNotFoundError(f"Ticket {ticket_id} does not exist.")

        created = ticket.feedback is None
        if created:
            ticket.feedback = Feedback(ticket_id=ticket_id, was_correct=was_correct)
        else:
            ticket.feedback.was_correct = was_correct
        self._session.commit()
        return ticket.feedback, created
