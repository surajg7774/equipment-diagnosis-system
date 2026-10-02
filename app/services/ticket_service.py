"""Reads and writes tickets and feedback (the only place that queries the SQL DB)."""

import math

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import TicketNotFoundError
from app.models.ticket import Feedback, Ticket
from app.schemas.enums import Severity
from app.schemas.knowledge_base import SimilarCase


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
    ) -> Ticket:
        ticket = Ticket(
            source=source,
            description=description,
            severity=severity,
            diagnosis=diagnosis,
            recommended_action=recommended_action,
            confidence_score=confidence_score,
            similar_cases=[c.model_dump(mode="json") for c in similar_cases or []],
        )
        self._session.add(ticket)
        self._session.commit()
        return ticket

    def list_tickets(self, page: int, page_size: int) -> tuple[list[Ticket], int, int]:
        """Return ``(tickets_on_page, total_count, total_pages)``, newest first."""
        total = self._session.scalar(select(func.count()).select_from(Ticket)) or 0
        tickets = self._session.scalars(
            select(Ticket)
            # Load feedback for the whole page in one extra query (avoids N+1).
            .options(selectinload(Ticket.feedback))
            # id is a tie-breaker so ordering is stable when timestamps collide,
            # which keeps pages from overlapping or skipping rows.
            .order_by(Ticket.created_at.desc(), Ticket.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return list(tickets), total, math.ceil(total / page_size)

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
