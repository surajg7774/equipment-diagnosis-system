"""The knowledge base as a living store: feedback on diagnoses is written into ChromaDB.

Every record in the vector store is one of three kinds:

* ``source: seed``                              - shipped with the system (``data/knowledge_base.json``)
* ``source: verified``                           - a ticket whose fix was confirmed to work (thumbs up, a
  technician's confirm or correction, or a resolved session); built by ``upsert_ticket_case``. It is
  ``outcome: verified_fix`` once it has enough confirmations (a technician's review, or 2+), and only
  ``outcome: provisional_fix`` while it has fewer (see app/core/confirmation.py)
* ``source: feedback``, ``outcome: failed_fix``   - a ticket whose diagnosis + fix a user reported did
  NOT work (thumbs down); built by ``upsert_failed_case``

Seed, verified and provisional records are what retrieval offers the LLM as *working* fixes (provisional ones
are labelled and ranked lower); failed records are offered separately, labelled as approaches that did not work. This service is the ONLY code that
writes feedback records. A ticket that is still ``pending`` never becomes a verified record.
"""

import logging
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone

from chromadb.api.models.Collection import Collection

from app.core.confirmation import confirmation_count, effective_sources
from app.core.exceptions import KnowledgeBaseUpdateError
from app.db.seed import embedding_text
from app.models.ticket import Ticket
from app.schemas.enums import FixVerification, KnowledgeOutcome, ReviewStatus
from app.schemas.review import KnowledgeBaseStats
from app.services.embedding_service import Embedder

logger = logging.getLogger(__name__)

VERIFIED_ID_PREFIX = "VC-"  # "verified case"; seed records are "KB-001"...
FAILED_ID_PREFIX = "FC-"  # "failed case"


def issue_text_for(ticket: Ticket) -> str:
    """The symptom text a future query should be matched against.

    A text ticket's description is the technician's own report. A photo ticket's description is
    only "[image upload] file.jpg", so the AI's visual findings stand in for it.
    """
    return ticket.description if ticket.source == "text" else ticket.diagnosis


def case_content_for(ticket: Ticket) -> tuple[str, str]:
    """(root_cause, recommended_fix) to store: the technician's correction if there is one."""
    return (
        ticket.corrected_root_cause or ticket.diagnosis,
        ticket.corrected_fix or ticket.recommended_action,
    )


class KnowledgeBaseService:
    def __init__(self, collection: Collection, embedder: Embedder) -> None:
        self._collection = collection
        self._embedder = embedder

    @staticmethod
    def new_record_id(ticket_id: int) -> str:
        # A random suffix keeps ids unique even if the SQL database is reset and ticket numbers
        # start again from 1 while old verified records are still in the vector store.
        return f"{VERIFIED_ID_PREFIX}{ticket_id}-{uuid.uuid4().hex[:6]}"

    @staticmethod
    def new_failed_record_id(ticket_id: int) -> str:
        return f"{FAILED_ID_PREFIX}{ticket_id}-{uuid.uuid4().hex[:6]}"

    def upsert_ticket_case(self, ticket: Ticket) -> None:
        """Insert or update the confirmed-fix record built from a reviewed ticket.

        The ticket must already carry its review fields (status, correction, kb_record_id, and who confirmed it,
        which decides whether the record is "verified_fix" or only "provisional_fix").
        Raises ``KnowledgeBaseUpdateError`` if the vector store fails.
        """
        if ticket.review_status == ReviewStatus.PENDING or not ticket.kb_record_id:
            raise ValueError("Only reviewed tickets with a record id can be added to the knowledge base")

        root_cause, fix = case_content_for(ticket)
        issue = issue_text_for(ticket)
        equipment_type = ticket.review_equipment_type or "unspecified"
        # A ticket reviewed before the safeguard existed has no stored verdict and stays verified.
        verification = FixVerification(ticket.kb_verification) if ticket.kb_verification else FixVerification.VERIFIED
        outcome = KnowledgeOutcome.VERIFIED_FIX if verification == FixVerification.VERIFIED else KnowledgeOutcome.PROVISIONAL_FIX
        sources = effective_sources(ticket.confirmation_sources, reviewed=True)
        self._write(
            ticket.kb_record_id,
            embedding_text(equipment_type, issue),
            {
                "id": ticket.kb_record_id,
                "equipment_type": equipment_type,
                "issue_description": issue,
                "root_cause": root_cause,
                "recommended_fix": fix,
                "severity": ticket.severity.value,
                "source": "verified",
                "outcome": outcome.value,
                "verification": verification.value,
                "confirmation_count": confirmation_count(sources),
                "confirmed_by": ",".join(sorted(sources)),
                "ticket_id": ticket.id,
                "review_status": ticket.review_status.value,
                "verified_at": (ticket.reviewed_at or datetime.now(timezone.utc)).isoformat(),
            },
            failure_message="The knowledge base could not be updated, so the review was not saved. Please try again.",
        )
        logger.info(
            "knowledge_base_case_added",
            extra={
                "ticket_id": ticket.id,
                "record_id": ticket.kb_record_id,
                "review_status": ticket.review_status.value,
                "verification": verification.value,
            },
        )

    def upsert_failed_case(self, ticket: Ticket) -> None:
        """Insert or update the "failed_fix" record for a ticket whose diagnosis did NOT work.

        It stores the original issue and the AI's ORIGINAL diagnosis + fix (the thing that failed),
        even if a technician later corrects the ticket. It is matched by symptoms exactly like a
        verified record, so similar future reports retrieve it. Raises ``KnowledgeBaseUpdateError``.
        """
        if not ticket.failed_kb_record_id:
            raise ValueError("The ticket needs a failed_kb_record_id before a failed fix can be recorded")

        issue = issue_text_for(ticket)
        equipment_type = ticket.review_equipment_type or "unspecified"
        self._write(
            ticket.failed_kb_record_id,
            embedding_text(equipment_type, issue),
            {
                "id": ticket.failed_kb_record_id,
                "equipment_type": equipment_type,
                "issue_description": issue,
                "root_cause": ticket.diagnosis,  # the diagnosis that did NOT work
                "recommended_fix": ticket.recommended_action,  # the fix that did NOT work
                "severity": ticket.severity.value,
                "source": "feedback",
                "outcome": KnowledgeOutcome.FAILED_FIX.value,
                "ticket_id": ticket.id,
                "reported_at": datetime.now(timezone.utc).isoformat(),
            },
            failure_message="The feedback was saved, but the knowledge base could not be updated.",
        )
        logger.info("knowledge_base_failed_fix_added", extra={"ticket_id": ticket.id, "record_id": ticket.failed_kb_record_id})

    def _write(self, record_id: str, document: str, metadata: dict, failure_message: str) -> None:
        """Upsert one record, make sure similarity search can find it, and wrap any failure."""
        try:
            payload = {
                "ids": [record_id],
                "embeddings": [self._embedder.embed([document])[0]],
                "documents": [document],
                "metadatas": [metadata],  # Chroma metadata must be flat str/int/float/bool values.
            }
            self._collection.upsert(**payload)
            self._ensure_searchable(payload)
        except Exception as exc:
            logger.exception("knowledge_base_upsert_failed", extra={"record_id": record_id})
            raise KnowledgeBaseUpdateError(failure_message) from exc

    def _ensure_searchable(self, payload: dict, attempts: int = 3) -> None:
        """Check that a record just written can be FOUND by similarity search, and re-write it if not.

        Why: ChromaDB's vector index sometimes leaves out a record written into a collection that
        already holds data. Measured on chromadb 1.5.9, roughly 1 in 8 single-record writes into a
        freshly seeded collection were missing from similarity results (even when asking for every
        record) although ``get(ids=...)`` returned them. A technician's verified case would then
        silently never be retrieved. Writing the same record again fixed every case we saw (12 of
        12, no delay needed), so we look after each write and retry a bounded number of times.
        """
        record_id, vector = payload["ids"][0], payload["embeddings"][0]
        for attempt in range(1, attempts + 1):
            # n_results has headroom so exact-duplicate cases (identical vectors tie) cannot push the new one out.
            found = self._collection.query(query_embeddings=[vector], n_results=10)["ids"][0]
            if record_id in found:
                if attempt > 1:
                    logger.warning("knowledge_base_index_repaired", extra={"record_id": record_id, "attempts": attempt})
                return
            if attempt < attempts:
                self._collection.upsert(**payload)
        # Still stored (and kept in the SQL ticket, so startup restore can re-add it), just not searchable.
        logger.error("knowledge_base_index_miss", extra={"record_id": record_id, "attempts": attempts})

    def remove(self, record_id: str) -> bool:
        """Best-effort removal; returns whether it worked.

        Used to undo a write when the follow-up DB commit fails, and to retract a ticket's own
        failed-fix record when its thumbs-down is changed to a thumbs-up.
        """
        try:
            self._collection.delete(ids=[record_id])
        except Exception:
            logger.exception("knowledge_base_cleanup_failed", extra={"record_id": record_id})
            return False
        return True

    def stats(self) -> KnowledgeBaseStats:
        """Counts of seed, verified, provisional and failed records, so the growth is visible."""
        provisional_outcome = KnowledgeOutcome.PROVISIONAL_FIX.value
        try:
            # "verified" = confirmed fixes that are not provisional. `$ne` keeps records that have no outcome at
            # all (written before outcomes existed), so those stay verified; a test pins this against real Chroma.
            verified = self._collection.get(
                where={"$and": [{"source": "verified"}, {"outcome": {"$ne": provisional_outcome}}]}, include=["metadatas"]
            )
            provisional = self._collection.get(where={"outcome": provisional_outcome}, include=[])
            failed = self._collection.get(where={"outcome": KnowledgeOutcome.FAILED_FIX.value}, include=[])
            total = self._collection.count()
        except Exception as exc:
            logger.exception("knowledge_base_stats_failed")
            raise KnowledgeBaseUpdateError("The knowledge base is unavailable.") from exc

        statuses = [(metadata or {}).get("review_status") for metadata in (verified.get("metadatas") or [])]
        verified_count, provisional_count, failed_count = len(verified["ids"]), len(provisional["ids"]), len(failed["ids"])
        return KnowledgeBaseStats(
            total=total,
            # records stored before "source" existed have none and count as seed
            seed=total - verified_count - provisional_count - failed_count,
            verified=verified_count,
            verified_confirmed=statuses.count(ReviewStatus.CONFIRMED.value),
            verified_corrected=statuses.count(ReviewStatus.CORRECTED.value),
            failed=failed_count,
            provisional=provisional_count,
        )

    def restore_missing(self, tickets: Iterable[Ticket]) -> int:
        """Re-add feedback records that are missing from the vector store; returns how many.

        The vector store can be wiped independently of the SQL database (a deleted ``chroma_db``
        folder, a host that resets its disk). Run at startup, this makes the database the source
        of truth so neither verified nor failed knowledge is silently lost.
        """
        tickets = list(tickets)
        reviewed = [t for t in tickets if t.kb_record_id and t.review_status != ReviewStatus.PENDING]
        failed = [t for t in tickets if t.failed_kb_record_id]
        wanted = [t.kb_record_id for t in reviewed] + [t.failed_kb_record_id for t in failed]
        if not wanted:
            return 0
        present = set(self._collection.get(ids=wanted, include=[])["ids"])
        restored = 0
        for ticket in reviewed:
            if ticket.kb_record_id not in present:
                self.upsert_ticket_case(ticket)
                restored += 1
        for ticket in failed:
            if ticket.failed_kb_record_id not in present:
                self.upsert_failed_case(ticket)
                restored += 1
        if restored:
            logger.info("knowledge_base_cases_restored", extra={"count": restored})
        return restored
