"""The knowledge base as a living store: verified technician cases are added to ChromaDB.

Every record in the vector store is one of two kinds, marked by its ``source`` metadata:

* ``seed``     - shipped with the system (``data/knowledge_base.json``), loaded by the seed script
* ``verified`` - built from a ticket a technician confirmed or corrected

This service is the ONLY code that writes verified cases, and ``ReviewService`` is the only
caller, so a ticket that is still ``pending`` can never reach the knowledge base.
"""

import logging
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone

from chromadb.api.models.Collection import Collection

from app.core.exceptions import KnowledgeBaseUpdateError
from app.db.seed import embedding_text
from app.models.ticket import Ticket
from app.schemas.enums import ReviewStatus
from app.schemas.review import KnowledgeBaseStats
from app.services.embedding_service import Embedder

logger = logging.getLogger(__name__)

VERIFIED_ID_PREFIX = "VC-"  # "verified case"; seed records are "KB-001"...


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

    def upsert_ticket_case(self, ticket: Ticket) -> None:
        """Insert or update the knowledge-base record built from a reviewed ticket.

        The ticket must already carry its review fields (status, correction, kb_record_id).
        Raises ``KnowledgeBaseUpdateError`` if the vector store fails.
        """
        if ticket.review_status == ReviewStatus.PENDING or not ticket.kb_record_id:
            raise ValueError("Only reviewed tickets with a record id can be added to the knowledge base")

        root_cause, fix = case_content_for(ticket)
        issue = issue_text_for(ticket)
        equipment_type = ticket.review_equipment_type or "unspecified"
        document = embedding_text(equipment_type, issue)
        try:
            payload = {
                "ids": [ticket.kb_record_id],
                "embeddings": [self._embedder.embed([document])[0]],
                "documents": [document],
                # Chroma metadata must be flat str/int/float/bool values.
                "metadatas": [
                    {
                        "id": ticket.kb_record_id,
                        "equipment_type": equipment_type,
                        "issue_description": issue,
                        "root_cause": root_cause,
                        "recommended_fix": fix,
                        "severity": ticket.severity.value,
                        "source": "verified",
                        "ticket_id": ticket.id,
                        "review_status": ticket.review_status.value,
                        "verified_at": (ticket.reviewed_at or datetime.now(timezone.utc)).isoformat(),
                    }
                ],
            }
            self._collection.upsert(**payload)
            self._ensure_searchable(payload)
        except Exception as exc:
            logger.exception("knowledge_base_upsert_failed", extra={"ticket_id": ticket.id})
            raise KnowledgeBaseUpdateError(
                "The knowledge base could not be updated, so the review was not saved. Please try again."
            ) from exc
        logger.info(
            "knowledge_base_case_added",
            extra={"ticket_id": ticket.id, "record_id": ticket.kb_record_id, "review_status": ticket.review_status.value},
        )

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

    def remove(self, record_id: str) -> None:
        """Best-effort removal (used to undo a write when the follow-up DB commit fails)."""
        try:
            self._collection.delete(ids=[record_id])
        except Exception:
            logger.exception("knowledge_base_cleanup_failed", extra={"record_id": record_id})

    def stats(self) -> KnowledgeBaseStats:
        """Counts of seed vs verified records, so the growth is visible."""
        try:
            verified = self._collection.get(where={"source": "verified"}, include=["metadatas"])
            total = self._collection.count()
        except Exception as exc:
            logger.exception("knowledge_base_stats_failed")
            raise KnowledgeBaseUpdateError("The knowledge base is unavailable.") from exc

        statuses = [(metadata or {}).get("review_status") for metadata in (verified.get("metadatas") or [])]
        count = len(verified["ids"])
        return KnowledgeBaseStats(
            total=total,
            seed=total - count,  # records stored before "source" existed have none and count as seed
            verified=count,
            verified_confirmed=statuses.count(ReviewStatus.CONFIRMED.value),
            verified_corrected=statuses.count(ReviewStatus.CORRECTED.value),
        )

    def restore_missing(self, tickets: Iterable[Ticket]) -> int:
        """Re-add reviewed tickets whose record is missing from the vector store; returns how many.

        The vector store can be wiped independently of the SQL database (a deleted ``chroma_db``
        folder, a host that resets its disk). Run at startup, this makes the database the source
        of truth so verified knowledge is not silently lost.
        """
        reviewed = [t for t in tickets if t.kb_record_id and t.review_status != ReviewStatus.PENDING]
        if not reviewed:
            return 0
        present = set(self._collection.get(ids=[t.kb_record_id for t in reviewed], include=[])["ids"])
        restored = 0
        for ticket in reviewed:
            if ticket.kb_record_id not in present:
                self.upsert_ticket_case(ticket)
                restored += 1
        if restored:
            logger.info("knowledge_base_cases_restored", extra={"count": restored})
        return restored
