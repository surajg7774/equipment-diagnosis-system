"""Shared test fixtures.

Strategy: tests never download the real embedding model or touch the real
database. Instead:
  * ``FakeEmbedder`` produces deterministic word-overlap vectors (fast, offline),
  * SQLite runs in memory,
  * ChromaDB runs in memory (``EphemeralClient``) where a real store is useful.
FastAPI's ``dependency_overrides`` swaps these in for the production wiring.
"""

import hashlib
import math
import re
import uuid
from pathlib import Path

import chromadb
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db, get_diagnosis_service, get_knowledge_base_service, get_vision_service
from app.core.config import Settings
from app.db.base import Base
from app.db.seed import load_records, seed_knowledge_base
from app.db.session import create_session_factory
from app.db.vector_store import get_or_create_collection
from app.main import create_app
from app.schemas.enums import Severity
from app.services.diagnosis_service import DiagnosisService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.llm_service import LLMDiagnosis, LLMService
from app.services.vision_service import VisionAnalysis, VisionService

KNOWLEDGE_BASE_PATH = Path(__file__).resolve().parent.parent / "data" / "knowledge_base.json"
# Wide enough that unrelated words almost never share a hash bucket, so a query of
# made-up words reliably scores ~0 similarity against every knowledge-base record.
_DIMS = 4096

FAKE_ROOT_CAUSE = "LLM-generated root cause"
FAKE_FIX = "LLM-generated fix"
FAKE_VISION_DESCRIPTION = "Heavy orange rust and flaking paint on the pump casing."
FAKE_VISION_ACTION = "Clean the casing, treat the corrosion and inspect the seals."
FAKE_LLM_CONFIDENCE = 72  # percent; distinct from any retrieval similarity so tests can tell them apart


class FakeEmbedder:
    """Bag-of-words hashing embedder: texts sharing words get similar vectors.

    Not semantically smart like the real model, but deterministic and good
    enough to make "pump grinding leaking" land near the pump records.
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    @staticmethod
    def _embed_one(text: str) -> list[float]:
        vector = [0.0] * _DIMS
        for word in re.findall(r"[a-z]+", text.lower()):
            bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % _DIMS
            vector[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


class FakeLLMService(LLMService):
    """Stands in for Ollama so no test needs a running LLM.

    Returns a canned ``LLMDiagnosis`` (or raises ``error``) and records every call,
    so tests can check exactly what the diagnosis service handed to the LLM.
    """

    def __init__(self, result: LLMDiagnosis | None = None, error: Exception | None = None, ready: bool = True):
        self.result = result or LLMDiagnosis(
            root_cause=FAKE_ROOT_CAUSE,
            recommended_fix=FAKE_FIX,
            severity=Severity.MEDIUM,
            confidence=FAKE_LLM_CONFIDENCE,
        )
        self.error = error
        self.ready = ready
        self.calls: list[tuple[str, list]] = []  # (user_input, context_examples) per call
        self.previous_attempts_per_call: list[list] = []  # the "already tried" list handed over on each call
        self.failed_examples_per_call: list[list] = []  # the "did NOT work" knowledge-base cases on each call
        # Optional: successive answers for successive calls (the last one repeats), for multi-step flows.
        self.results: list[LLMDiagnosis] | None = None

    def generate_diagnosis(self, user_input, context_examples, previous_attempts=(), failed_examples=()):
        self.calls.append((user_input, list(context_examples)))
        self.previous_attempts_per_call.append(list(previous_attempts))
        self.failed_examples_per_call.append(list(failed_examples))
        if self.error:
            raise self.error
        if self.results:
            return self.results[min(len(self.calls), len(self.results)) - 1]
        return self.result

    def is_ready(self) -> bool:
        return self.ready


class FakeVisionService(VisionService):
    """Stands in for the vision model: no network, canned assessment, records every call."""

    def __init__(self, result: VisionAnalysis | None = None, error: Exception | None = None):
        self.result = result or VisionAnalysis(
            is_equipment_photo=True,
            damage_detected=True,
            description=FAKE_VISION_DESCRIPTION,
            severity=Severity.MEDIUM,
            recommended_action=FAKE_VISION_ACTION,
            confidence=0.8,
            model_name="fake-vision-model",
            provider="fake",
        )
        self.error = error
        self.calls: list[tuple[bytes, str]] = []  # (image_bytes, media_type) per call

    def analyze(self, image_bytes, media_type):
        self.calls.append((image_bytes, media_type))
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def fake_llm() -> FakeLLMService:
    return FakeLLMService()


@pytest.fixture
def fake_vision() -> FakeVisionService:
    return FakeVisionService()


@pytest.fixture
def seeded_collection(fake_embedder):
    """A real in-memory Chroma collection holding the full knowledge base."""
    client = chromadb.EphemeralClient()
    collection = get_or_create_collection(client, f"test_{uuid.uuid4().hex}")
    seed_knowledge_base(collection, fake_embedder, load_records(KNOWLEDGE_BASE_PATH))
    yield collection
    client.delete_collection(collection.name)


@pytest.fixture
def db_session_factory():
    engine = create_engine(
        "sqlite://",  # in-memory
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # one shared connection, otherwise each gets its own empty DB
    )
    Base.metadata.create_all(engine)
    yield create_session_factory(engine)
    engine.dispose()


@pytest.fixture
def knowledge_base(seeded_collection, fake_embedder) -> KnowledgeBaseService:
    """Writes verified cases into the SAME collection the diagnosis service searches."""
    return KnowledgeBaseService(seeded_collection, fake_embedder)


@pytest.fixture
def app(db_session_factory, seeded_collection, fake_embedder, fake_llm, fake_vision, knowledge_base):
    # A high limit: only the rate-limit tests care about throttling, and they build their own limiter.
    application = create_app(Settings(environment="testing", log_level="WARNING", rate_limit_per_minute=1000))
    # Threshold 0.2 (not the production 0.5): the fake embedder's scores are on a
    # different scale from the real model's. Related text scores well above 0.2,
    # made-up words score ~0.
    service = DiagnosisService(
        embedder=fake_embedder,
        collection=seeded_collection,
        llm=fake_llm,
        top_k=3,
        low_confidence_threshold=0.2,
    )

    def override_get_db():
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    application.dependency_overrides[get_db] = override_get_db
    application.dependency_overrides[get_diagnosis_service] = lambda: service
    application.dependency_overrides[get_vision_service] = lambda: fake_vision
    application.dependency_overrides[get_knowledge_base_service] = lambda: knowledge_base
    return application


@pytest.fixture
def client(app) -> TestClient:
    # raise_server_exceptions=False => a crash becomes a real HTTP 500 response,
    # exactly what a client would see, instead of re-raising inside the test.
    return TestClient(app, raise_server_exceptions=False)
