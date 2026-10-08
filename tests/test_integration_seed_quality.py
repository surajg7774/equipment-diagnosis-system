"""Seed quality with the REAL embedding model (opt-in: pytest -m integration tests/test_integration_seed_quality.py).

No LLM and no Groq quota: embeddings only. Checks the two things the fake embedder cannot:
  * no two records are near-duplicates (cosine >= 0.90 on the text the system embeds), and
  * the frozen retrieval test sets (data/eval/) still retrieve what they should, and unrelated problems are not
    grounded on a wrong case more often than measured when the knowledge base was expanded.
"""

import json
import uuid
from itertools import combinations
from pathlib import Path

import chromadb
import pytest

from app.core.config import Settings
from app.db.seed import load_records, record_to_embedding_text, seed_knowledge_base
from app.db.vector_store import get_or_create_collection
from app.services.diagnosis_service import cosine_similarity
from app.services.embedding_service import create_embedder
from tests.conftest import KNOWLEDGE_BASE_PATH

pytestmark = pytest.mark.integration

settings = Settings()
EVAL = Path(__file__).resolve().parent.parent / "data" / "eval"
DUPLICATE_THRESHOLD = 0.90


@pytest.fixture(scope="module")
def embedder():
    return create_embedder(settings.embedding_backend, settings.embedding_model_name)


@pytest.fixture(scope="module")
def collection(embedder):
    coll = get_or_create_collection(chromadb.EphemeralClient(), f"seedq_{uuid.uuid4().hex}")
    seed_knowledge_base(coll, embedder, load_records(KNOWLEDGE_BASE_PATH))
    return coll


def _top3(embedder, collection, query):
    raw = collection.query(query_embeddings=[embedder.embed([query])[0]], n_results=3, include=["metadatas", "distances"])
    return [(i, m["equipment_type"], 1 - d) for i, m, d in zip(raw["ids"][0], raw["metadatas"][0], raw["distances"][0])]


def test_no_two_records_are_near_duplicates(embedder):
    records = load_records(KNOWLEDGE_BASE_PATH)
    vectors = embedder.embed([record_to_embedding_text(r) for r in records])
    pairs = [(cosine_similarity(vectors[i], vectors[j]), records[i].id, records[j].id) for i, j in combinations(range(len(records)), 2)]

    too_close = [p for p in pairs if p[0] >= DUPLICATE_THRESHOLD]

    assert too_close == [], f"merge these: {too_close}"


def test_the_frozen_queries_find_their_category_and_their_expected_record(embedder, collection):
    queries = json.loads((EVAL / "retrieval_queries.json").read_text(encoding="utf-8"))
    category_hits = strict = strict_total = grounded = 0
    for item in queries:
        top = _top3(embedder, collection, item["q"])
        category_hits += any(t.lower() == item["category"].lower() for _, t, _ in top)
        grounded += top[0][2] >= settings.low_confidence_threshold
        if "expected_id" in item:
            strict_total += 1
            strict += any(i == item["expected_id"] for i, _, _ in top)

    assert category_hits / len(queries) >= 0.90  # measured 31/31 when the knowledge base was expanded
    assert strict == strict_total  # the original records are still found
    assert grounded / len(queries) >= 0.85  # measured 29/31


def test_unrelated_problems_are_rarely_grounded_on_a_wrong_case(embedder, collection):
    negatives = json.loads((EVAL / "negative_queries.json").read_text(encoding="utf-8"))
    grounded = [n["q"] for n in negatives if _top3(embedder, collection, n["q"])[0][2] >= settings.low_confidence_threshold]

    assert len(grounded) <= 3, grounded  # measured 2 of 15, both sensible near-matches
