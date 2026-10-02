"""Seed ChromaDB with the knowledge base.

Run from the project root::

    python -m app.db.seed

The script is **idempotent**: running it twice leaves the database in the same
state as running it once.  It does this by

* using each record's ``id`` as the Chroma id and calling ``upsert``
  (insert-or-update, never duplicate), and
* deleting any ids in Chroma that are no longer in the JSON file, so the
  vector store always mirrors the file exactly.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from chromadb.api.models.Collection import Collection

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.vector_store import create_chroma_client, get_or_create_collection
from app.schemas.knowledge_base import KnowledgeBaseRecord
from app.services.embedding_service import Embedder, create_embedder

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SeedReport:
    upserted: int
    deleted: int
    total_in_store: int


def load_records(path: Path) -> list[KnowledgeBaseRecord]:
    """Read and validate the JSON file. Raises on bad data or duplicate ids."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    records = [KnowledgeBaseRecord.model_validate(item) for item in raw]

    ids = [r.id for r in records]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"Duplicate record ids in knowledge base: {sorted(duplicates)}")
    return records


def record_to_embedding_text(record: KnowledgeBaseRecord) -> str:
    """The text we turn into a vector for a record.

    We embed the equipment type plus the *symptom* description, because that is
    what a technician will describe.  Root cause / fix are stored as metadata
    and returned with the match, but are not embedded: they would pull the
    vector toward words the technician never typed.
    """
    return f"{record.equipment_type}: {record.issue_description}"


def seed_knowledge_base(
    collection: Collection, embedder: Embedder, records: list[KnowledgeBaseRecord]
) -> SeedReport:
    """Make ``collection`` contain exactly ``records`` (idempotent)."""
    ids = [r.id for r in records]

    if records:
        collection.upsert(
            ids=ids,
            embeddings=embedder.embed([record_to_embedding_text(r) for r in records]),
            documents=[record_to_embedding_text(r) for r in records],
            # Chroma metadata must be flat str/int/float/bool values.
            metadatas=[r.model_dump(mode="json") for r in records],
        )

    # Remove records that were deleted from the JSON file since the last run.
    stale_ids = sorted(set(collection.get(include=[])["ids"]) - set(ids))
    if stale_ids:
        collection.delete(ids=stale_ids)

    report = SeedReport(
        upserted=len(records), deleted=len(stale_ids), total_in_store=collection.count()
    )
    logger.info("knowledge_base_seeded", extra=report.__dict__)
    return report


def seed_if_empty(collection: Collection, embedder: Embedder, path: Path) -> SeedReport | None:
    """Seed only when the collection has no records; returns None if it already had some.

    Used at server startup: hosts with an ephemeral filesystem (Render's free tier) lose
    ``chroma_db`` on every restart, so the knowledge base is rebuilt from the JSON file.
    """
    if collection.count() > 0:
        return None
    return seed_knowledge_base(collection, embedder, load_records(path))


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    records = load_records(settings.knowledge_base_path)
    client = create_chroma_client(settings.chroma_persist_dir)
    collection = get_or_create_collection(client, settings.chroma_collection_name)
    report = seed_knowledge_base(
        collection, create_embedder(settings.embedding_backend, settings.embedding_model_name), records
    )

    print(
        f"Seeded '{settings.chroma_collection_name}': {report.upserted} upserted, "
        f"{report.deleted} removed, {report.total_in_store} total in store."
    )


if __name__ == "__main__":
    main()
