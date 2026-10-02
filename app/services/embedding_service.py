"""Text -> vector embeddings using a local sentence-transformers model.

An *embedding* is a list of numbers (384 of them for all-MiniLM-L6-v2) that
captures the meaning of a sentence.  Sentences with similar meaning end up
with vectors that point in similar directions, which is what lets us do
"find similar past issues" without keyword matching.
"""

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    """Anything that can turn texts into vectors.

    The diagnosis service and seed script depend on this tiny interface rather
    than on sentence-transformers directly, so tests can plug in a fake.
    """

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OnnxEmbeddingService:
    """``Embedder`` running all-MiniLM-L6-v2 on the ONNX runtime bundled with ChromaDB.

    The same model weights as the sentence-transformers version, so the vectors are
    identical (verified: cosine similarity 1.00000 between the two on 40 texts), but with
    no PyTorch: about 210 MB of RAM instead of about 750 MB. That is what lets the backend
    fit in a 512 MB host such as Render's free/Starter instances.
    """

    # Texts are embedded a few at a time. The ONNX runtime allocates (and keeps) working memory
    # in proportion to the batch size: embedding all 28 knowledge-base records in ONE call made
    # the process grow by ~260 MB, which does not fit a 512 MB host. Small batches are barely
    # slower for this workload and keep the footprint flat.
    _BATCH_SIZE = 4

    def __init__(self) -> None:
        self._embed_fn = None

    def load(self) -> None:
        """Load the model (downloads ~80 MB from Chroma's CDN on the very first run)."""
        if self._embed_fn is None:
            from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

            logger.info("embedding_model_loading", extra={"model": "all-MiniLM-L6-v2", "backend": "onnx"})
            fn = ONNXMiniLM_L6_V2()
            fn(["warm up"])  # forces the download + session creation now, not on the first request
            self._embed_fn = fn
            logger.info("embedding_model_loaded", extra={"model": "all-MiniLM-L6-v2", "backend": "onnx"})

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.load()
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._BATCH_SIZE):
            # Output vectors are already length 1 (normalised), like the other backend's.
            batch = self._embed_fn(texts[start : start + self._BATCH_SIZE])
            vectors.extend([float(x) for x in vector] for vector in batch)
        return vectors


class EmbeddingService:
    """``Embedder`` backed by a sentence-transformers (PyTorch) model."""

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model = None  # loaded lazily; loading takes a few seconds

    def load(self) -> None:
        """Load the model into memory (downloads it on first ever run, ~90 MB)."""
        if self._model is None:
            # Imported here so that importing this module (e.g. in tests that
            # use a fake embedder) does not pull in torch.
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # optional dependency, not in requirements.txt
                raise RuntimeError(
                    "EMBEDDING_BACKEND=sentence-transformers needs `pip install sentence-transformers` "
                    "(or use the default EMBEDDING_BACKEND=onnx)."
                ) from exc

            logger.info("embedding_model_loading", extra={"model": self._model_name})
            self._model = SentenceTransformer(self._model_name)
            logger.info("embedding_model_loaded", extra={"model": self._model_name})

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.load()
        # normalize_embeddings=True scales every vector to length 1, so cosine
        # similarity reduces to a plain dot product and scores stay in [0, 1]
        # for related text.
        vectors = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return vectors.tolist()


def create_embedder(backend: str, model_name: str) -> "OnnxEmbeddingService | EmbeddingService":
    """Build the embedder chosen by the EMBEDDING_BACKEND setting."""
    if backend == "sentence-transformers":
        return EmbeddingService(model_name)
    return OnnxEmbeddingService()
