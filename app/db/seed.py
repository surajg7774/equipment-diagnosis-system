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

import hashlib
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

# Knowledge-base records that come from real usage rather than the seed file: "verified" (a fix that
# was confirmed to work) and "feedback" (a fix that a user reported did NOT work).
FEEDBACK_SOURCES = ("verified", "feedback")


# The model the stored vectors were made with. Vectors from another model would be meaningless, so they are ignored.
VECTORS_MODEL = "all-MiniLM-L6-v2"


@dataclass(frozen=True)
class SeedReport:
    upserted: int
    deleted: int
    total_in_store: int
    vectors_reused: int = 0  # records whose stored vector was used (no embedding work)
    vectors_computed: int = 0  # records that had to be embedded now


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
    return embedding_text(record.equipment_type, record.issue_description)


def embedding_text(equipment_type: str | None, issue_description: str) -> str:
    """"<type>: <symptoms>" when the equipment type is known, otherwise just the symptoms."""
    if equipment_type and equipment_type.lower() != "unspecified":
        return f"{equipment_type}: {issue_description}"
    return issue_description


def text_fingerprint(text: str) -> str:
    """SHA-256 of an embedding text: a stored vector is only valid for exactly the text it was made from."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_stored_vectors(path: Path | None, model: str = VECTORS_MODEL) -> dict[str, dict]:
    """Read the precomputed document vectors ({record id: {"text_sha256", "vector"}}); {} if there are none to use.

    Never raises: a missing, unreadable or foreign-model file just means "embed everything", which is slower but
    always correct.
    """
    if path is None or not Path(path).is_file():
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("model") != model:
            logger.warning("stored_vectors_ignored", extra={"reason": "different model", "file_model": data.get("model")})
            return {}
        return dict(data["vectors"])
    except Exception:
        logger.exception("stored_vectors_unreadable")
        return {}


def resolve_embeddings(
    texts: list[str], ids: list[str], embedder: Embedder, stored_vectors: dict[str, dict] | None
) -> tuple[list[list[float]], int, int]:
    """One vector per text: the stored one when its fingerprint matches, otherwise computed now.

    Returns (vectors, reused, computed). Only the records without a valid stored vector reach the embedder.
    """
    stored_vectors = stored_vectors or {}
    vectors: list = [None] * len(texts)
    missing: list[int] = []
    for index, (record_id, text) in enumerate(zip(ids, texts)):
        entry = stored_vectors.get(record_id)
        if entry and entry.get("text_sha256") == text_fingerprint(text) and entry.get("vector"):
            vectors[index] = [float(x) for x in entry["vector"]]
        else:
            missing.append(index)
    if missing:
        for index, vector in zip(missing, embedder.embed([texts[i] for i in missing])):
            vectors[index] = vector
    return vectors, len(texts) - len(missing), len(missing)


def seed_knowledge_base(
    collection: Collection,
    embedder: Embedder,
    records: list[KnowledgeBaseRecord],
    stored_vectors: dict[str, dict] | None = None,
) -> SeedReport:
    """Make the SEED part of ``collection`` match ``records`` exactly (idempotent).

    Records created from feedback (verified fixes and failed fixes) are left untouched.
    ``stored_vectors`` (see ``load_stored_vectors``) lets seeding skip the embedder for records whose text is unchanged.
    """
    ids = [r.id for r in records]
    reused = computed = 0

    if records:
        texts = [record_to_embedding_text(r) for r in records]
        embeddings, reused, computed = resolve_embeddings(texts, ids, embedder, stored_vectors)
        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            # Chroma metadata must be flat str/int/float/bool values.
            metadatas=[{**r.model_dump(mode="json"), "source": "seed"} for r in records],
        )

    # Remove SEED records that were deleted from the JSON file since the last run.
    # Records created from real usage (source "verified" = a fix that worked, "feedback" = a fix that
    # did not) are not part of the seed file, so a re-seed must never touch them. (Records stored
    # before the "source" field existed have none and count as seed.)
    stored = collection.get(include=["metadatas"])
    stale_ids = sorted(
        record_id
        for record_id, metadata in zip(stored["ids"], stored["metadatas"] or [])
        if (metadata or {}).get("source", "seed") not in FEEDBACK_SOURCES and record_id not in set(ids)
    )
    if stale_ids:
        collection.delete(ids=stale_ids)

    report = SeedReport(
        upserted=len(records),
        deleted=len(stale_ids),
        total_in_store=collection.count(),
        vectors_reused=reused,
        vectors_computed=computed,
    )
    logger.info("knowledge_base_seeded", extra=report.__dict__)
    return report


def seed_if_empty(
    collection: Collection, embedder: Embedder, path: Path, stored_vectors: dict[str, dict] | None = None
) -> SeedReport | None:
    """Seed only when the collection has no records; returns None if it already had some.

    Used at server startup: hosts with an ephemeral filesystem (Render's free tier) lose
    ``chroma_db`` on every restart, so the knowledge base is rebuilt from the JSON file.
    """
    if collection.count() > 0:
        return None
    return seed_knowledge_base(collection, embedder, load_records(path), stored_vectors)


def stored_vectors_for(settings) -> dict[str, dict]:
    """The precomputed vectors, but only when they match the embedding model the settings select."""
    if settings.embedding_backend == "sentence-transformers" and settings.embedding_model_name != VECTORS_MODEL:
        return {}
    return load_stored_vectors(settings.knowledge_base_vectors_path)


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    records = load_records(settings.knowledge_base_path)
    client = create_chroma_client(settings.chroma_persist_dir)
    collection = get_or_create_collection(client, settings.chroma_collection_name)
    report = seed_knowledge_base(
        collection,
        create_embedder(settings.embedding_backend, settings.embedding_model_name, settings.embedding_model_dir),
        records,
        stored_vectors_for(settings),
    )

    print(
        f"Seeded '{settings.chroma_collection_name}': {report.upserted} upserted, "
        f"{report.deleted} removed, {report.total_in_store} total in store "
        f"({report.vectors_reused} stored vectors used, {report.vectors_computed} embedded now)."
    )


if __name__ == "__main__":
    main()
