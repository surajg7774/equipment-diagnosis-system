"""Thumbs up / thumbs down on a diagnosis, and what each one teaches the knowledge base.

    thumbs up   -> the AI's diagnosis becomes a confirmed working fix (outcome "verified_fix"), through
                   the same confirm logic a technician uses on the History page.
    thumbs down -> a NEW record of the diagnosis + fix that did NOT work (outcome "failed_fix"). It
                   deletes nothing, leaves the ticket's review status alone (a technician can still
                   confirm or correct it), and blocks nothing: later diagnoses of similar problems are
                   shown it, labelled "did NOT work", so the LLM avoids repeating it.

The verdict itself is always saved first. If the vector store then fails, the response says
``knowledge_base_updated: false`` instead of failing the request.

Changing your mind: one verdict per ticket (the latest wins). Down -> up retracts that ticket's own
failed record (it was only ever created by that thumbs-down). Up -> down adds a failed record but does
not delete the verified one, which a technician may have confirmed too; see the README limitations.
"""

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.exceptions import KnowledgeBaseUpdateError
from app.models.ticket import Feedback, Ticket
from app.schemas.enums import KnowledgeOutcome, ReviewStatus
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.review_service import ReviewService
from app.services.ticket_service import TicketService

logger = logging.getLogger(__name__)


@dataclass
class FeedbackOutcome:
    feedback: Feedback
    created: bool  # first verdict for this ticket (201) or a changed/repeated one (200)
    knowledge_base_outcome: KnowledgeOutcome | None  # what the knowledge base now holds for this verdict
    knowledge_base_updated: bool  # whether THIS request wrote to the knowledge base
    kb_record_id: str | None


class FeedbackService:
    def __init__(
        self,
        db: Session,
        tickets: TicketService,
        reviews: ReviewService,
        knowledge_base: KnowledgeBaseService,
    ) -> None:
        self._db = db
        self._tickets = tickets
        self._reviews = reviews
        self._kb = knowledge_base

    def submit(self, ticket_id: int, was_correct: bool) -> FeedbackOutcome:
        """Save the verdict, then teach the knowledge base. Raises ``TicketNotFoundError``."""
        feedback, created = self._tickets.save_feedback(ticket_id, was_correct)  # committed first, whatever happens next
        ticket = feedback.ticket
        if was_correct:
            return self._positive(feedback, created, ticket)
        return self._negative(feedback, created, ticket)

    # ---------------------------------------------------------------------------------------------
    def _positive(self, feedback: Feedback, created: bool, ticket: Ticket) -> FeedbackOutcome:
        updated = False
        if ticket.review_status == ReviewStatus.PENDING:
            try:
                self._reviews.confirm(ticket.id)  # writes the verified_fix record, then commits
                updated = True
            except KnowledgeBaseUpdateError:
                logger.warning("feedback_knowledge_base_update_failed", extra={"ticket_id": ticket.id, "outcome": "verified_fix"})
        self._retract_failed_record(ticket)

        if ticket.review_status == ReviewStatus.CORRECTED:
            # A technician already recorded what really fixed it; a thumbs-up on the AI's original
            # diagnosis must not override that, so nothing is written.
            return FeedbackOutcome(feedback, created, None, False, None)
        confirmed = ticket.review_status == ReviewStatus.CONFIRMED
        return FeedbackOutcome(
            feedback,
            created,
            KnowledgeOutcome.VERIFIED_FIX if confirmed else None,
            updated,
            ticket.kb_record_id if confirmed else None,
        )

    def _retract_failed_record(self, ticket: Ticket) -> None:
        """A thumbs-up after this ticket's own thumbs-down: the user changed their mind."""
        if not ticket.failed_kb_record_id:
            return
        record_id = ticket.failed_kb_record_id
        if self._kb.remove(record_id):  # only forget the pointer once the record is really gone
            ticket.failed_kb_record_id = None
            self._db.commit()
            logger.info("feedback_failed_fix_retracted", extra={"ticket_id": ticket.id, "record_id": record_id})

    def _negative(self, feedback: Feedback, created: bool, ticket: Ticket) -> FeedbackOutcome:
        is_new_record = ticket.failed_kb_record_id is None
        record_id = ticket.failed_kb_record_id or self._kb.new_failed_record_id(ticket.id)
        ticket.failed_kb_record_id = record_id
        try:
            self._kb.upsert_failed_case(ticket)  # 1. knowledge base first...
            self._db.commit()  # 2. ...then the database
        except KnowledgeBaseUpdateError:
            self._db.rollback()  # the verdict was committed already; only the record pointer is dropped
            logger.warning("feedback_knowledge_base_update_failed", extra={"ticket_id": ticket.id, "outcome": "failed_fix"})
            return FeedbackOutcome(feedback, created, None, False, None)
        except Exception:
            self._db.rollback()
            if is_new_record:
                self._kb.remove(record_id)  # do not leave a record that no ticket points to
            raise
        logger.info("feedback_failed_fix_recorded", extra={"ticket_id": ticket.id, "record_id": record_id})
        return FeedbackOutcome(feedback, created, KnowledgeOutcome.FAILED_FIX, True, record_id)
