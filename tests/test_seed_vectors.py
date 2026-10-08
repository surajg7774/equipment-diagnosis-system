"""Precomputed seed vectors: the stored file is current, seeding uses it, and falls back to the embedder when it can't.

Why they exist: on Render's free instance (about 0.1 CPU) embedding every seed record at each cold start took minutes.
`scripts/build_kb_vectors.py` computes the vectors once; seeding reuses one only when the SHA-256 of the record's
current embedding text matches. These tests need no embedding model (the real-model check is in
test_integration_seed_quality.py).
"""

import json
import math
import uuid

import chromadb
import pytest

from app.core.config import Settings
from app.db.seed import (
    VECTORS_MODEL,
    load_records,
    load_stored_vectors,
    record_to_embedding_text,
    seed_if_empty,
    seed_knowledge_base,
    stored_vectors_for,
    text_fingerprint,
)
from app.db.vector_store import get_or_create_collection
from tests.conftest import KNOWLEDGE_BASE_PATH

VECTORS_PATH = KNOWLEDGE_BASE_PATH.parent / "knowledge_base_vectors.json"
RECORDS = load_records(KNOWLEDGE_BASE_PATH)


class CountingEmbedder:
    """Returns a fixed unit vector and remembers every text it was asked to embed."""

    def __init__(self, dimension: int = 384):
        self.dimension = dimension
        self.texts: list[str] = []

    def embed(self, texts):
        self.texts.extend(texts)
        return [[1.0] + [0.0] * (self.dimension - 1) for _ in texts]


@pytest.fixture
def fresh_collection():
    return get_or_create_collection(chromadb.EphemeralClient(), f"vec_{uuid.uuid4().hex}")


@pytest.fixture(scope="module")
def stored():
    return load_stored_vectors(VECTORS_PATH)


# --- the committed file ---------------------------------------------------------------------------------------------------
def test_the_stored_vectors_are_up_to_date_with_the_knowledge_base(stored):
    """Fails when a record's symptom text changed (or a record was added or removed) without regenerating the file.

    Fix: python scripts/build_kb_vectors.py
    """
    stale = [r.id for r in RECORDS if stored.get(r.id, {}).get("text_sha256") != text_fingerprint(record_to_embedding_text(r))]
    extra = sorted(set(stored) - {r.id for r in RECORDS})
    assert stale == [] and extra == [], f"run `python scripts/build_kb_vectors.py` (stale: {stale[:5]}, left over: {extra[:5]})"


def test_every_stored_vector_is_a_unit_vector_of_the_right_size(stored):
    header = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
    assert header["model"] == VECTORS_MODEL and header["dimension"] == 384
    for record_id, entry in stored.items():
        vector = entry["vector"]
        assert len(vector) == 384, record_id
        assert math.isclose(math.sqrt(sum(x * x for x in vector)), 1.0, abs_tol=1e-3), record_id


def test_the_default_settings_point_at_the_committed_file():
    assert Settings().knowledge_base_vectors_path == VECTORS_PATH.relative_to(VECTORS_PATH.parent.parent)


# --- seeding uses them ----------------------------------------------------------------------------------------------------
def test_seeding_with_up_to_date_vectors_does_not_call_the_embedder(fresh_collection, stored):
    embedder = CountingEmbedder()

    report = seed_knowledge_base(fresh_collection, embedder, RECORDS, stored)

    assert embedder.texts == []
    assert (report.vectors_reused, report.vectors_computed) == (len(RECORDS), 0)
    assert fresh_collection.count() == len(RECORDS)
    got = fresh_collection.get(ids=[RECORDS[0].id], include=["embeddings", "documents"])
    assert list(got["embeddings"][0][:3]) == pytest.approx(stored[RECORDS[0].id]["vector"][:3], abs=1e-6)
    assert got["documents"][0] == record_to_embedding_text(RECORDS[0])


def test_a_record_whose_text_changed_is_embedded_again_and_the_others_are_not(fresh_collection, stored):
    changed = RECORDS[5].model_copy(update={"issue_description": RECORDS[5].issue_description + " It also smells of smoke."})
    records = [*RECORDS[:5], changed, *RECORDS[6:]]
    embedder = CountingEmbedder()

    report = seed_knowledge_base(fresh_collection, embedder, records, stored)

    assert embedder.texts == [record_to_embedding_text(changed)]
    assert (report.vectors_reused, report.vectors_computed) == (len(RECORDS) - 1, 1)


def test_a_new_record_and_a_missing_file_fall_back_to_the_embedder(fresh_collection, stored):
    embedder = CountingEmbedder()
    seed_knowledge_base(fresh_collection, embedder, RECORDS[:3], {})  # no stored vectors at all
    assert len(embedder.texts) == 3

    extra = RECORDS[3].model_copy(update={"id": "KB-999"})
    more = CountingEmbedder()
    report = seed_knowledge_base(get_or_create_collection(chromadb.EphemeralClient(), f"vec_{uuid.uuid4().hex}"), more, [*RECORDS[:3], extra], stored)
    assert more.texts == [record_to_embedding_text(extra)] and report.vectors_computed == 1


def test_seed_if_empty_passes_the_vectors_on(fresh_collection, stored):
    embedder = CountingEmbedder()

    report = seed_if_empty(fresh_collection, embedder, KNOWLEDGE_BASE_PATH, stored)

    assert report is not None and report.vectors_reused == len(RECORDS) and embedder.texts == []
    assert seed_if_empty(fresh_collection, embedder, KNOWLEDGE_BASE_PATH, stored) is None  # already seeded: untouched


# --- loading is forgiving -------------------------------------------------------------------------------------------------
def test_missing_unreadable_or_foreign_model_files_mean_embed_everything(tmp_path):
    assert load_stored_vectors(None) == {}
    assert load_stored_vectors(tmp_path / "nope.json") == {}
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_stored_vectors(broken) == {}
    foreign = tmp_path / "foreign.json"
    foreign.write_text(json.dumps({"model": "some-other-model", "vectors": {"KB-001": {"text_sha256": "x", "vector": [1.0]}}}), encoding="utf-8")
    assert load_stored_vectors(foreign) == {}


def test_vectors_for_another_embedding_model_are_not_used():
    settings = Settings(embedding_backend="sentence-transformers", embedding_model_name="some-other-model")
    assert stored_vectors_for(settings) == {}
    assert stored_vectors_for(Settings()) != {}


# --- the model folder -------------------------------------------------------------------------------------------------------
def test_the_model_folder_setting_reaches_the_onnx_embedder(monkeypatch, tmp_path):
    from app.services.embedding_service import OnnxEmbeddingService, create_embedder

    seen = {}

    class FakeOnnx:
        MODEL_NAME = "all-MiniLM-L6-v2"
        DOWNLOAD_PATH = "default"

        def __call__(self, texts):
            seen["download_path"] = type(self).DOWNLOAD_PATH
            return [[0.0] * 384 for _ in texts]

    monkeypatch.setattr("chromadb.utils.embedding_functions.ONNXMiniLM_L6_V2", FakeOnnx, raising=True)
    embedder = create_embedder("onnx", "all-MiniLM-L6-v2", tmp_path / "models")
    assert isinstance(embedder, OnnxEmbeddingService)

    embedder.load()

    assert seen["download_path"] == str(tmp_path / "models" / "all-MiniLM-L6-v2")
