"""End-to-end checks with the REAL embedding model and the REAL LLM provider.

Opt-in:  pytest -m integration

* Downloads the ~80 MB embedding model on first run.
* The LLM tests use whichever provider the settings/.env select (LLM_PROVIDER=ollama or groq):
  Ollama must be running with its model pulled, or GROQ_API_KEY must be valid. They are
  skipped if the provider is not ready. Groq calls use a little of your API quota.

They assert the *shape* of LLM output and the routing logic, not the exact wording,
because LLM text varies from run to run.
"""

import uuid

import chromadb
import pytest

from app.core.config import Settings
from app.db.seed import load_records, seed_knowledge_base
from app.db.vector_store import get_or_create_collection
from app.schemas.enums import DiagnosisBasis, Severity
from app.services.diagnosis_service import INVALID_INPUT_NOTE, NO_MATCH_NOTE, DiagnosisService
from app.services.embedding_service import create_embedder
from app.services.llm_service import create_llm_service
from tests.conftest import KNOWLEDGE_BASE_PATH, FakeLLMService

pytestmark = pytest.mark.integration

settings = Settings()  # honours .env and OLLAMA_MODEL / LOW_CONFIDENCE_THRESHOLD overrides


@pytest.fixture(scope="module")
def embedder():
    return create_embedder(settings.embedding_backend, settings.embedding_model_name)


@pytest.fixture(scope="module")
def collection(embedder):
    client = chromadb.EphemeralClient()
    coll = get_or_create_collection(client, f"it_{uuid.uuid4().hex}")
    seed_knowledge_base(coll, embedder, load_records(KNOWLEDGE_BASE_PATH))
    return coll


@pytest.fixture(scope="module")
def retrieval_only(embedder, collection):
    """Real embeddings + real Chroma, with the LLM faked (to test retrieval and routing)."""
    return DiagnosisService(
        embedder, collection, FakeLLMService(), settings.top_k, settings.low_confidence_threshold
    )


@pytest.fixture(scope="module")
def real_llm():
    llm = create_llm_service(settings)
    if not llm.is_ready():
        pytest.skip(f"LLM provider {settings.llm_provider!r} is not ready (not running / bad key / model missing)")
    yield llm
    llm.close()


@pytest.fixture(scope="module")
def full_pipeline(embedder, collection, real_llm):
    return DiagnosisService(
        embedder, collection, real_llm, settings.top_k, settings.low_confidence_threshold
    )


# --- retrieval with the real embedding model -------------------------------------------
@pytest.mark.parametrize(
    "query, expected_category",
    [
        # Different wording from the KB text, same meaning: the point of embeddings. The knowledge base holds only
        # documented records, so the check is on the equipment type of the closest record.
        ("pump making loud grinding noise and leaking oil", "pump"),
        ("my printer jammed and the paper got crumpled", "printer"),
        ("AC is running but only blowing warm air", "HVAC"),
        ("diesel genset will not crank, battery seems flat", "generator"),
    ],
)
def test_real_embeddings_retrieve_the_right_case(retrieval_only, query, expected_category):
    assert retrieval_only.find_similar_cases(query)[0].equipment_type == expected_category


def test_threshold_separates_known_issues_from_unknown_ones(retrieval_only):
    """Guards the default LOW_CONFIDENCE_THRESHOLD against embedding-model/KB drift."""
    threshold = settings.low_confidence_threshold
    known = [
        "pump making loud grinding noise and leaking oil",
        "my printer jammed and the paper got crumpled",
        "AC is running but only blowing warm air",
        "motor smells like burning and is extremely hot",
    ]
    unknown = [  # no documented record covers these (the lathe-chatter record was removed: no source states it)
        "CNC machine spindle chatters when cutting aluminium",
        "what is the best recipe for chocolate cake",
    ]
    for query in known:
        assert retrieval_only.find_similar_cases(query)[0].similarity_score >= threshold, query
    for query in unknown:
        assert retrieval_only.find_similar_cases(query)[0].similarity_score < threshold, query


# --- real LLM ------------------------------------------------------------------------------
def assert_llm_reported_a_sensible_confidence(result):
    """The model must have supplied the number itself (not the silent fallback), in a plausible range."""
    assert result.llm_confidence_defaulted is False, "the LLM gave no usable confidence"
    assert 0.05 <= result.llm_confidence <= 1.0, result.llm_confidence



def test_real_llm_diagnoses_a_known_issue_using_retrieved_cases(full_pipeline):
    result = full_pipeline.diagnose("pump making loud grinding noise and leaking oil")

    assert result.diagnosis_basis is DiagnosisBasis.SIMILAR_CASES and result.note is None
    assert_llm_reported_a_sensible_confidence(result)  # similar_cases path
    assert result.retrieval_confidence >= settings.low_confidence_threshold  # strong match
    assert result.diagnosis.strip() and result.recommended_action.strip()
    assert isinstance(result.severity, Severity)
    assert result.severity is Severity.HIGH  # the keyword heuristic is a floor
    assert result.is_valid_issue is True
    assert len(result.similar_cases) == 3
    # A NEW tailored answer, not a verbatim copy of the closest record.
    assert result.diagnosis != result.similar_cases[0].root_cause
    assert result.recommended_action != result.similar_cases[0].recommended_fix


def test_real_llm_handles_an_issue_with_no_close_match(full_pipeline):
    result = full_pipeline.diagnose("CNC machine spindle chatters when cutting aluminium")

    assert result.diagnosis_basis is DiagnosisBasis.GENERAL_REASONING
    assert result.note == NO_MATCH_NOTE
    assert result.retrieval_confidence < settings.low_confidence_threshold
    assert_llm_reported_a_sensible_confidence(result)  # general_reasoning path
    assert result.diagnosis.strip() and result.recommended_action.strip()
    assert isinstance(result.severity, Severity)


def test_real_llm_flags_a_non_equipment_question_as_invalid(full_pipeline):
    result = full_pipeline.diagnose("what is the capital of France")

    assert result.is_valid_issue is False
    assert result.severity is None
    assert result.note == INVALID_INPUT_NOTE


def test_real_llm_does_not_reject_a_genuine_emergency(full_pipeline):
    result = full_pipeline.diagnose("machine caught fire and there is smoke everywhere")

    assert result.is_valid_issue is True
    assert result.severity is Severity.HIGH


def test_onnx_batching_does_not_change_the_vectors():
    """The memory-saving small batches must give the same vectors as one big batch."""
    import numpy as np

    from app.services.embedding_service import OnnxEmbeddingService

    service = OnnxEmbeddingService()
    texts = [r.issue_description for r in load_records(KNOWLEDGE_BASE_PATH)]
    service.load()
    in_small_batches = np.array(service.embed(texts))
    in_one_batch = np.array([list(v) for v in service._embed_fn(texts)])

    cosine = (in_small_batches * in_one_batch).sum(axis=1)  # vectors are unit length
    assert cosine.min() > 0.9999


def test_real_llm_confidence_is_independent_of_how_well_the_knowledge_base_matched(full_pipeline):
    """A laptop is not in the knowledge base (weak retrieval), yet the model can be sure of a battery fault."""
    result = full_pipeline.diagnose("laptop battery drains within an hour and the laptop shuts down at 30 percent")

    assert result.diagnosis_basis is DiagnosisBasis.GENERAL_REASONING
    assert result.retrieval_confidence < settings.low_confidence_threshold  # weak match...
    assert_llm_reported_a_sensible_confidence(result)  # ...but the model still reports its own certainty
    assert result.llm_confidence > result.retrieval_confidence  # the two scores genuinely differ


# --- the human-in-the-loop feedback loop with REAL embeddings (no LLM needed) ---------------------
def test_a_confirmed_case_becomes_a_close_match_for_a_reworded_report(embedder, collection):
    """The point of the feature, measured with the real model against the real 0.50 threshold."""
    from tests.test_review import make_ticket  # reuse the ticket helper

    from app.services.knowledge_base_service import KnowledgeBaseService
    from app.services.review_service import ReviewService
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.db.base import Base
    import app.models.ticket  # noqa: F401  (registers the tables)

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    kb = KnowledgeBaseService(collection, embedder)
    service = DiagnosisService(embedder, collection, FakeLLMService(), settings.top_k, settings.low_confidence_threshold)

    first = "laptop battery drains within an hour and the laptop shuts down at 30 percent"
    reworded = "my laptop battery dies in under an hour and it powers off at around 30%"
    unrelated = "conveyor belt is drifting to one side and scraping the frame"

    before = service.find_similar_cases(reworded)[0]
    assert before.similarity_score < settings.low_confidence_threshold  # nothing like it yet: general reasoning

    ticket = make_ticket(session, description=first)
    pending_view = service.find_similar_cases(reworded)[0]
    assert pending_view.source == "seed"  # a pending ticket changes nothing

    ReviewService(session, kb).confirm(ticket.id)

    after = service.find_similar_cases(reworded)[0]
    assert after.id == ticket.kb_record_id and after.source == "verified"
    assert after.similarity_score >= settings.low_confidence_threshold  # now a CLOSE match
    assert after.similarity_score > before.similarity_score + 0.3
    assert service.find_similar_cases(unrelated)[0].source == "seed"  # and it does not leak into unrelated queries
