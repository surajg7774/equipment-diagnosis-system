"""ChromaDB setup (persistent, local)."""

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.config import Settings as ChromaSettings


def create_chroma_client(persist_dir: str) -> ClientAPI:
    """Open (or create) an on-disk Chroma database in ``persist_dir``."""
    return chromadb.PersistentClient(
        path=persist_dir,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def get_or_create_collection(client: ClientAPI, name: str) -> Collection:
    """Return the knowledge-base collection, creating it if needed.

    ``hnsw:space = cosine`` tells Chroma to rank by cosine distance, so
    ``distance = 1 - cosine_similarity`` (0 = identical meaning).
    """
    return client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})
