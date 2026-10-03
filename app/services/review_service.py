"""Human-in-the-loop review of diagnoses.

                      confirm                          correct
    pending ──────────────────► confirmed  ──────────────────────┐
       │                                                         ▼
       └────────────────────────────────────────────────────► corrected ◄─┐ (correct again = edit)
                                                                  └────────┘

* ``confirm``  is allowed from pending (and is an idempotent no-op if the same source already confirmed).
  It is refused once a ticket has been corrected: the technician already said the AI was wrong.
* ``correct``  is allowed from any status (pending, confirmed, or an existing correction).
* Nothing moves a ticket back to pending, and a rejected request changes nothing.

Confirming or correcting adds (or updates) the ticket's record in the knowledge base. The record
is written FIRST and the database committed second: if the vector store fails the ticket stays
as it was, and if the commit fails the new record is removed again.

HOW MANY CONFIRMATIONS A FIX NEEDS (see app/core/confirmation.py): every call says WHO is confirming
(``source``). An end user's click is one confirmation, a technician's review is worth two, and a fix is
only *verified* once it has ``min_confirmations`` (default 2). Below that it is stored as *provisional*:
still retrievable, but labelled and ranked lower. A second, different source on a fix that is already
confirmed upgrades the SAME record (a technician can verify what a user confirmed). A correction replaces
the fix's content, so earlier confirmations (of the old content) no longer count.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.confirmation import DEFAULT_MIN_CONFIRMATIONS, confirmation_count, effective_sources, verification_for
from app.core.exceptions import KnowledgeBaseUpdateError, ReviewConflictError, TicketNotFoundError
from app.models.ticket import Ticket
from app.schemas.enums import ConfirmationSource, ReviewStatus
from app.services.knowledge_base_service import KnowledgeBaseService

logger = logging.getLogger(__name__)


def _clean_type(equipment_type: str | None) -> str | None:
    cleaned = (equipment_type or "").strip()
    return cleaned or None


class ReviewService:
    def __init__(
        self,
        session: Session,
        knowledge_base: KnowledgeBaseService,
        min_confirmations: int = DEFAULT_MIN_CONFIRMATIONS,
    ) -> None:
        self._session = session
        self._kb = knowledge_base
        self._min_confirmations = min_confirmations

    def confirm(
        self,
        ticket_id: int,
        equipment_type: str | None = None,
        source: ConfirmationSource = ConfirmationSource.TECHNICIAN,
    ) -> Ticket:
        """``source`` agrees the AI's diagnosis was correct."""
        ticket = self._load(ticket_id)
        if ticket.review_status == ReviewStatus.CORRECTED:
            raise ReviewConflictError(
                "This ticket was already corrected by a technician; use the correction form to change it."
            )
        known = effective_sources(ticket.confirmation_sources, reviewed=ticket.review_status != ReviewStatus.PENDING)
        if ticket.review_status == ReviewStatus.CONFIRMED and source.value in known:
            return ticket  # idempotent: clicking twice must not create a second record or count twice
        return self._apply(ticket, ReviewStatus.CONFIRMED, None, None, equipment_type, sources=known | {source.value})

    def correct(
        self,
        ticket_id: int,
        root_cause: str,
        recommended_fix: str,
        equipment_type: str | None = None,
        source: ConfirmationSource = ConfirmationSource.TECHNICIAN,
    ) -> Ticket:
        """``source`` supplies the real root cause and fix (stored beside the AI's diagnosis)."""
        ticket = self._load(ticket_id)
        # New content: confirmations of the OLD text say nothing about it, so only this author counts.
        return self._apply(
            ticket, ReviewStatus.CORRECTED, root_cause.strip(), recommended_fix.strip(), equipment_type, sources={source.value}
        )

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
        sources: set[str],
    ) -> Ticket:
        is_new_record = ticket.kb_record_id is None
        ticket.review_status = status
        ticket.corrected_root_cause = root_cause  # None for a plain confirmation
        ticket.corrected_fix = recommended_fix
        ticket.reviewed_at = datetime.now(timezone.utc)
        ticket.kb_record_id = ticket.kb_record_id or self._kb.new_record_id(ticket.id)
        if equipment_type is not None:
            ticket.review_equipment_type = _clean_type(equipment_type)
        ticket.confirmation_sources = sorted(sources)
        ticket.kb_verification = verification_for(confirmation_count(sources), self._min_confirmations).value

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
            extra={
                "ticket_id": ticket.id,
                "review_status": status.value,
                "record_id": ticket.kb_record_id,
                "verification": ticket.kb_verification,
                "confirmation_count": confirmation_count(sources),
                "confirmed_by": ",".join(sorted(sources)),
            },
        )
        return ticket
