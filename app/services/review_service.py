"""Human-in-the-loop review of diagnoses.

                      confirm                          correct
    pending ──────────────────► confirmed  ──────────────────────┐
       │                                                         ▼
       └────────────────────────────────────────────────────► corrected ◄─┐ (correct again = edit)
                                                                  └────────┘

* ``confirm``  is allowed from pending (and is an idempotent no-op if already confirmed).
  It is refused once a ticket has been corrected: the technician already said the AI was wrong.
* ``correct``  is allowed from any status (pending, confirmed, or an existing correction).
* Nothing moves a ticket back to pending, and a rejected request changes nothing.

Confirming or correcting adds (or updates) the ticket's record in the knowledge base. The record
is written FIRST and the database committed second: if the vector store fails the ticket stays
as it was, and if the commit fails the new record is removed again.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import KnowledgeBaseUpdateError, ReviewConflictError, TicketNotFoundError
from app.models.ticket import Ticket
from app.schemas.enums import ReviewStatus
from app.services.knowledge_base_service import KnowledgeBaseService

logger = logging.getLogger(__name__)


def _clean_type(equipment_type: str | None) -> str | None:
    cleaned = (equipment_type or "").strip()
    return cleaned or None


class ReviewService:
    def __init__(self, session: Session, knowledge_base: KnowledgeBaseService) -> None:
        self._session = session
        self._kb = knowledge_base

    def confirm(self, ticket_id: int, equipment_type: str | None = None) -> Ticket:
        """The technician agrees the AI's diagnosis was correct."""
        ticket = self._load(ticket_id)
        if ticket.review_status == ReviewStatus.CONFIRMED:
            return ticket  # idempotent: clicking twice must not create a second record
        if ticket.review_status == ReviewStatus.CORRECTED:
            raise ReviewConflictError(
                "This ticket was already corrected by a technician; use the correction form to change it."
            )
        return self._apply(ticket, ReviewStatus.CONFIRMED, None, None, equipment_type)

    def correct(
        self, ticket_id: int, root_cause: str, recommended_fix: str, equipment_type: str | None = None
    ) -> Ticket:
        """The technician supplies the real root cause and fix (stored beside the AI's diagnosis)."""
        ticket = self._load(ticket_id)
        return self._apply(ticket, ReviewStatus.CORRECTED, root_cause.strip(), recommended_fix.strip(), equipment_type)

    # ------------------------------------------------------------------------------------------
    def _load(self, ticket_id: int) -> Ticket:
        ticket = self._session.get(Ticket, ticket_id)
        if ticket is None:
            raise TicketNotFoundError(f"Ticket {ticket_id} does not exist.")
        return ticket

    def _apply(
        self,
        ticket: Ticket,
        status: ReviewStatus,
        root_cause: str | None,
        recommended_fix: str | None,
        equipment_type: str | None,
    ) -> Ticket:
        is_new_record = ticket.kb_record_id is None
        ticket.review_status = status
        ticket.corrected_root_cause = root_cause  # None for a plain confirmation
        ticket.corrected_fix = recommended_fix
        ticket.reviewed_at = datetime.now(timezone.utc)
        ticket.kb_record_id = ticket.kb_record_id or self._kb.new_record_id(ticket.id)
        if equipment_type is not None:
            ticket.review_equipment_type = _clean_type(equipment_type)

        try:
            self._kb.upsert_ticket_case(ticket)  # 1. knowledge base first...
            self._session.commit()  # 2. ...then the database
        except KnowledgeBaseUpdateError:
            self._session.rollback()  # the ticket keeps its previous state
            raise
        except Exception:
            record_id = ticket.kb_record_id
            self._session.rollback()
            if is_new_record and record_id:
                self._kb.remove(record_id)  # do not leave a record that no ticket points to
            raise

        logger.info(
            "ticket_reviewed",
            extra={"ticket_id": ticket.id, "review_status": status.value, "record_id": ticket.kb_record_id},
        )
        return ticket
