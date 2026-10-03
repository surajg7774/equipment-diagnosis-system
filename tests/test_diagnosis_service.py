"""Unit tests for the RAG diagnosis service with ChromaDB and the LLM both mocked.

* ChromaDB: a ``MagicMock`` collection whose ``query`` returns a dict shaped
  exactly like real Chroma output.
* LLM: ``FakeLLMService`` (tests/conftest.py) returns a canned diagnosis and
  records what it was given, so no test needs Ollama running.
"""

from unittest.mock import MagicMock

import json

import pytest

from app.core.exceptions import KnowledgeBaseEmptyError, LLMResponseError, LLMUnavailableError
from app.schemas.enums import DiagnosisBasis, Severity
from app.services.diagnosis_service import (
    INVALID_INPUT_NOTE,
    NO_MATCH_NOTE,
    DiagnosisService,
    distance_to_similarity,
    has_close_match,
    parse_chroma_results,
)
from app.services.llm_service import DEFAULT_LLM_CONFIDENCE, LLMDiagnosis, LLMService, parse_llm_output
from tests.conftest import FAKE_FIX, FAKE_LLM_CONFIDENCE, FAKE_ROOT_CAUSE, FakeLLMService


def _metadata(case_id: str, severity: str = "high", equipment_type: str = "pump") -> dict:
    return {
        "id": case_id,
        "equipment_type": equipment_type,
        "issue_description": f"issue for {case_id}",
        "root_cause": f"root cause of {case_id}",
        "recommended_fix": f"fix for {case_id}",
        "severity": severity,
    }


_METADATAS = [_metadata("KB-001"), _metadata("KB-003", "medium"), _metadata("KB-006", "high", "motor")]

# Chroma returns one inner list per query; we send one query => outer length 1.
CLOSE_MATCH_RESPONSE = {
    "ids": [["KB-001", "KB-003", "KB-006"]],
    "metadatas": [_METADATAS],
    "distances": [[0.20, 0.45, 0.80]],  # cosine distance, nearest first => similarity 0.8 / 0.55 / 0.2
}
NO_MATCH_RESPONSE = {**CLOSE_MATCH_RESPONSE, "distances": [[0.90, 0.95, 0.99]]}  # similarity 0.1 / 0.05 / 0.01
EMPTY_RESPONSE = {"ids": [[]], "metadatas": [[]], "distances": [[]]}

THRESHOLD = 0.35


class StubEmbedder:
    def __init__(self):
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(texts)
        return [[0.1, 0.2, 0.3] for _ in texts]


@pytest.fixture
def mock_collection():
    collection = MagicMock()
    collection.query.return_value = CLOSE_MATCH_RESPONSE

    # The service searches twice: working fixes, then failed fixes. This mocked knowledge base holds no
    # failed-fix records, so that search finds nothing; every other search returns `query.return_value`.
    def query(**kwargs):
        if kwargs.get("where") == {"outcome": "failed_fix"}:
            return EMPTY_RESPONSE
        return collection.query.return_value

    collection.query.side_effect = query
    return collection


@pytest.fixture
def llm():
    return FakeLLMService()


@pytest.fixture
def service(mock_collection, llm):
    return DiagnosisService(
        embedder=StubEmbedder(),
        collection=mock_collection,
        llm=llm,
        top_k=3,
        low_confidence_threshold=THRESHOLD,
    )


# --- pure helpers ----------------------------------------------------------
@pytest.mark.parametrize(
    "distance, similarity",
    [(0.0, 1.0), (0.25, 0.75), (1.0, 0.0), (-0.0001, 1.0), (1.3, 0.0)],  # last two: clamping
)
def test_distance_to_similarity(distance, similarity):
    assert distance_to_similarity(distance) == pytest.approx(similarity)


def test_parse_chroma_results_builds_ranked_cases():
    cases = parse_chroma_results(CLOSE_MATCH_RESPONSE)

    assert [c.id for c in cases] == ["KB-001", "KB-003", "KB-006"]  # order preserved
    assert [c.similarity_score for c in cases] == [0.8, 0.55, 0.2]  # 1 - distance
    assert cases[0].severity == Severity.HIGH
    assert cases[2].equipment_type == "motor"


@pytest.mark.parametrize("empty", [EMPTY_RESPONSE, {}])
def test_parse_chroma_results_handles_empty_response(empty):
    assert parse_chroma_results(empty) == []


def test_has_close_match_compares_best_case_to_threshold():
    cases = parse_chroma_results(CLOSE_MATCH_RESPONSE)  # best similarity = 0.8

    assert has_close_match(cases, 0.5)
    assert has_close_match(cases, 0.8)  # exactly at the threshold counts as close
    assert not has_close_match(cases, 0.81)
    assert not has_close_match([], 0.1)


# --- retrieval -------------------------------------------------------------
def test_find_similar_cases_embeds_query_and_asks_chroma_for_top_k(service, mock_collection):
    cases = service.find_similar_cases("pump is loud")

    assert service._embedder.calls == [["pump is loud"]]
    mock_collection.query.assert_called_once()
    kwargs = mock_collection.query.call_args.kwargs
    assert kwargs["query_embeddings"] == [[0.1, 0.2, 0.3]]
    assert kwargs["n_results"] == 3
    assert len(cases) == 3 and cases[0].id == "KB-001"


# --- RAG: close match -------------------------------------------------------
def test_close_match_passes_the_top_cases_to_the_llm_as_context(service, llm):
    service.diagnose("pump making loud grinding noise and leaking oil")

    assert len(llm.calls) == 1
    user_input, context = llm.calls[0]
    assert user_input == "pump making loud grinding noise and leaking oil"
    assert [c.id for c in context] == ["KB-001", "KB-003", "KB-006"]


def test_diagnosis_comes_from_the_llm_not_from_the_closest_record(service):
    result = service.diagnose("pump making loud grinding noise and leaking oil")

    assert result.diagnosis == FAKE_ROOT_CAUSE
    assert result.recommended_action == FAKE_FIX
    # The old lookup behaviour would have returned the best record's text.
    assert "root cause of KB-001" not in result.diagnosis
    assert "fix for KB-001" not in result.recommended_action


def test_close_match_result_is_grounded_and_keeps_retrieval_metadata(service):
    result = service.diagnose("pump making loud grinding noise and leaking oil")

    assert result.diagnosis_basis == DiagnosisBasis.SIMILAR_CASES
    assert result.note is None
    assert result.retrieval_confidence == 0.8  # retrieval similarity of the best case
    assert [c.id for c in result.similar_cases] == ["KB-001", "KB-003", "KB-006"]


# --- RAG: no close match -----------------------------------------------------
def test_no_close_match_still_calls_the_llm_but_without_context(mock_collection, service, llm):
    mock_collection.query.return_value = NO_MATCH_RESPONSE

    result = service.diagnose("forklift hydraulic lift is slow and the mast jerks")

    assert len(llm.calls) == 1  # the LLM IS still called...
    assert llm.calls[0][1] == []  # ...but is not shown the weak, irrelevant matches
    assert result.diagnosis == FAKE_ROOT_CAUSE  # and its answer is still what we return


def test_no_close_match_adds_note_and_keeps_low_confidence_and_retrieved_cases(mock_collection, service):
    mock_collection.query.return_value = NO_MATCH_RESPONSE

    result = service.diagnose("forklift hydraulic lift is slow and the mast jerks")

    assert result.diagnosis_basis == DiagnosisBasis.GENERAL_REASONING
    assert result.note == NO_MATCH_NOTE
    assert "no closely matching past case found" in result.note.lower()
    assert result.retrieval_confidence == pytest.approx(0.1)
    assert len(result.similar_cases) == 3  # still reported for transparency


# --- severity: the heuristic is a floor under the LLM's opinion ---------------
@pytest.mark.parametrize(
    "description, llm_level, expected",
    [
        ("there is smoke coming out of the pump", Severity.LOW, Severity.HIGH),  # LLM can't downplay a safety keyword
        ("the display looks different today", Severity.HIGH, Severity.HIGH),  # LLM can escalate what keywords miss
        ("the display looks different today", Severity.LOW, Severity.LOW),
        ("generator won't start at all today", Severity.LOW, Severity.MEDIUM),  # heuristic says medium
    ],
)
def test_final_severity_is_the_more_severe_of_heuristic_and_llm(service, llm, description, llm_level, expected):
    llm.result = LLMDiagnosis(root_cause="x", recommended_fix="y", severity=llm_level)

    assert service.diagnose(description).severity == expected


# --- failure handling ----------------------------------------------------------
def test_empty_knowledge_base_raises_and_never_calls_the_llm(mock_collection, service, llm):
    mock_collection.query.return_value = EMPTY_RESPONSE

    with pytest.raises(KnowledgeBaseEmptyError):
        service.diagnose("anything at all here")
    assert llm.calls == []


@pytest.mark.parametrize("error", [LLMUnavailableError("down"), LLMResponseError("garbage")])
def test_llm_failures_propagate_instead_of_falling_back_to_a_raw_lookup(service, llm, error):
    llm.error = error

    with pytest.raises(type(error)):
        service.diagnose("pump making loud grinding noise")


# --- the LLM's raw text is parsed into a well-formed result ----------------------
class RawTextLLM(LLMService):
    """An LLM that 'answers' with raw text, which goes through the real parser."""

    def __init__(self, raw: str):
        self.raw = raw

    def generate_diagnosis(self, user_input, context_examples, previous_attempts=(), failed_examples=()):
        return parse_llm_output(self.raw)

    def is_ready(self):
        return True


def test_service_returns_well_formed_result_when_llm_output_is_parsed(mock_collection):
    messy_output = (
        "Sure! Here is my diagnosis:\n```json\n"
        '{"root_cause": "  Worn bearings and a failed shaft seal.  ",'
        ' "recommended_fix": "Replace both and re-lubricate.", "severity": "High"}\n```'
    )
    service = DiagnosisService(StubEmbedder(), mock_collection, RawTextLLM(messy_output), 3, THRESHOLD)

    result = service.diagnose("pump making loud grinding noise and leaking oil")

    assert result.diagnosis == "Worn bearings and a failed shaft seal."  # whitespace stripped
    assert result.recommended_action == "Replace both and re-lubricate."
    assert result.severity is Severity.HIGH  # "High" normalised to the enum
    assert 0.0 <= result.retrieval_confidence <= 1.0
    assert len(result.similar_cases) == 3


def test_unparseable_llm_output_surfaces_as_llm_response_error(mock_collection):
    service = DiagnosisService(StubEmbedder(), mock_collection, RawTextLLM("I cannot help."), 3, THRESHOLD)

    with pytest.raises(LLMResponseError):
        service.diagnose("pump making loud grinding noise")


# --- logging -------------------------------------------------------------------
def test_diagnose_logs_confidence_phase_timings_and_basis(service, caplog):
    with caplog.at_level("INFO", logger="app.services.diagnosis_service"):
        service.diagnose("pump making loud grinding noise")

    record = next(r for r in caplog.records if r.getMessage() == "diagnosis_completed")
    assert record.retrieval_confidence == 0.8
    assert record.latency_ms >= 0 and record.retrieval_ms >= 0 and record.llm_ms >= 0
    assert record.diagnosis_basis == "similar_cases"
    assert record.severity in {"low", "medium", "high"}
    # The raw user text must not be written to logs.
    assert "grinding" not in caplog.text


# --- health hooks ------------------------------------------------------------------
def test_health_helpers_delegate_to_dependencies(service, llm, mock_collection):
    mock_collection.count.return_value = 28
    assert service.knowledge_base_size() == 28

    llm.ready = False
    assert service.llm_is_ready() is False


# --- non-equipment input -----------------------------------------------------------------
def _llm_says_invalid(llm):
    llm.result = LLMDiagnosis(
        root_cause="Not an equipment issue.", recommended_fix="Describe the problem.",
        severity=Severity.LOW, is_valid_issue=False,
    )


def test_input_the_llm_rejects_is_flagged_invalid_with_no_severity_and_no_cases(service, llm):
    _llm_says_invalid(llm)

    result = service.diagnose("what is the capital of France")

    assert result.is_valid_issue is False
    assert result.severity is None
    assert result.note == INVALID_INPUT_NOTE
    assert result.similar_cases == []  # retrieved cases would be irrelevant noise
    assert result.diagnosis == "Not an equipment issue."


def test_llm_rejection_is_overruled_when_the_keyword_heuristic_sees_a_real_problem(service, llm):
    _llm_says_invalid(llm)  # a small model wrongly calls a fire report "not an issue"

    result = service.diagnose("machine caught fire and there is smoke everywhere")

    assert result.is_valid_issue is True
    assert result.severity is Severity.HIGH
    assert len(result.similar_cases) == 3


def test_ordinary_reports_are_valid(service):
    assert service.diagnose("pump making loud grinding noise").is_valid_issue is True


# --- two different confidences ---------------------------------------------------------------------
def test_llm_confidence_is_the_models_own_number_scaled_to_0_1(service):
    result = service.diagnose("pump making loud grinding noise and leaking oil")

    assert result.llm_confidence == FAKE_LLM_CONFIDENCE / 100  # 0.72
    assert result.llm_confidence_defaulted is False


def test_the_two_confidences_are_independent_a_weak_match_can_still_be_a_confident_diagnosis(
    mock_collection, service, llm
):
    """The motivating case: no close KB match, yet the LLM is fairly sure of its general diagnosis."""
    mock_collection.query.return_value = NO_MATCH_RESPONSE  # retrieval similarity 0.1
    llm.result = LLMDiagnosis(root_cause="x", recommended_fix="y", severity=Severity.MEDIUM, confidence=80)

    result = service.diagnose("laptop battery drains fast and the laptop shuts down at 30 percent")

    assert result.retrieval_confidence == pytest.approx(0.1)  # low: nothing similar in the KB
    assert result.llm_confidence == 0.8  # high: the model is sure anyway
    assert result.diagnosis_basis == DiagnosisBasis.GENERAL_REASONING


def test_a_close_match_does_not_inflate_the_llms_own_confidence(service, llm):
    llm.result = LLMDiagnosis(root_cause="x", recommended_fix="y", severity=Severity.LOW, confidence=30)

    result = service.diagnose("pump making loud grinding noise and leaking oil")

    assert result.retrieval_confidence == 0.8  # strong match
    assert result.llm_confidence == 0.3  # but the model says it is unsure


def test_missing_llm_confidence_falls_back_to_the_default_and_the_request_still_succeeds(service, llm):
    llm.result = LLMDiagnosis(root_cause="x", recommended_fix="y", severity=Severity.LOW)  # confidence=None

    result = service.diagnose("pump making loud grinding noise")

    assert result.llm_confidence == DEFAULT_LLM_CONFIDENCE / 100 == 0.5
    assert result.llm_confidence_defaulted is True
    assert result.diagnosis == "x"  # the rest of the answer is untouched


@pytest.mark.parametrize("garbage", ["very sure", 150, -3, True, None])
def test_unusable_confidence_in_raw_llm_output_defaults_and_warns_without_failing(mock_collection, caplog, garbage):
    raw = json.dumps(
        {"root_cause": "Worn bearings.", "recommended_fix": "Replace them.", "severity": "high", "confidence": garbage}
    )
    service = DiagnosisService(StubEmbedder(), mock_collection, RawTextLLM(raw), 3, THRESHOLD)

    with caplog.at_level("WARNING", logger="app.services.llm_service"):
        result = service.diagnose("pump making loud grinding noise")

    assert result.llm_confidence == 0.5 and result.llm_confidence_defaulted is True
    assert any(r.getMessage() == "llm_confidence_unusable" for r in caplog.records)


def test_valid_confidence_in_raw_llm_output_is_used_as_is(mock_collection):
    raw = '```json\n{"root_cause": "a", "recommended_fix": "b", "severity": "low", "confidence": "88%"}\n```'
    service = DiagnosisService(StubEmbedder(), mock_collection, RawTextLLM(raw), 3, THRESHOLD)

    result = service.diagnose("pump making loud grinding noise")

    assert result.llm_confidence == 0.88 and result.llm_confidence_defaulted is False


def test_log_line_reports_both_confidences_and_whether_the_llm_one_was_defaulted(service, caplog):
    with caplog.at_level("INFO", logger="app.services.diagnosis_service"):
        service.diagnose("pump making loud grinding noise")

    record = next(r for r in caplog.records if r.getMessage() == "diagnosis_completed")
    assert (record.retrieval_confidence, record.llm_confidence, record.llm_confidence_defaulted) == (0.8, 0.72, False)
