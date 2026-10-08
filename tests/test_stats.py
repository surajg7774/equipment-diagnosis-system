"""GET /api/v1/stats: the arithmetic (pure), the SQL aggregates (real in-memory DB) and the endpoint end to end."""

import pytest

from app.core.exceptions import KnowledgeBaseUpdateError
from app.core.rate_limit import RateLimiter
from app.schemas.enums import Severity
from app.schemas.review import KnowledgeBaseStats
from app.services.llm_service import LLMDiagnosis
from app.services.stats_service import build_stats, percentage
from app.services.ticket_service import TicketService
from tests.conftest import SEED_COUNT

RELATED = "laptop battery drains quickly and the laptop shuts down suddenly"  # lands on seed cases -> similar_cases
UNRELATED = "zqxv wplk jrmt"  # made-up words, ~0 similarity to everything -> general_reasoning
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


# --- the arithmetic, with no database -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "part, whole, expected",
    [(1, 4, 25.0), (1, 3, 33.3), (2, 3, 66.7), (3, 3, 100.0), (0, 5, 0.0), (7, 7, 100.0)],
)
def test_percentage_is_rounded_to_one_decimal(part, whole, expected):
    assert percentage(part, whole) == expected


def test_percentage_of_nothing_is_none_not_a_division_error():
    assert percentage(0, 0) is None


def _summary(**overrides):
    base = {
        "total": 0,
        "by_source": {},
        "by_basis": {},
        "by_review_status": {},
        "avg_retrieval_confidence": None,
        "avg_llm_confidence": None,
        "avg_image_confidence": None,
    }
    return {**base, **overrides}


def test_build_stats_splits_similar_cases_from_general_reasoning():
    stats = build_stats(
        _summary(total=10, by_source={"text": 8, "image": 2}, by_basis={"similar_cases": 6, "general_reasoning": 2}),
        KnowledgeBaseStats(total=31, seed=28, verified=3, verified_confirmed=2, verified_corrected=1),
    )

    assert (stats.total_diagnoses_performed, stats.text_diagnoses, stats.image_diagnoses) == (10, 8, 2)
    assert stats.resolution.counted == 8
    assert (stats.resolution.similar_cases_pct, stats.resolution.general_reasoning_pct) == (75.0, 25.0)
    assert (stats.knowledge_base_size, stats.original_seed_count, stats.technician_verified_count) == (31, 28, 3)


def test_the_two_percentages_always_add_up_to_one_hundred():
    resolution = build_stats(_summary(by_basis={"similar_cases": 1, "general_reasoning": 2}), None).resolution

    assert resolution.similar_cases_pct + resolution.general_reasoning_pct == pytest.approx(100.0, abs=0.1)


def test_build_stats_with_no_data_has_zero_counts_and_null_percentages_and_averages():
    stats = build_stats(_summary(), KnowledgeBaseStats(total=28, seed=28, verified=0, verified_confirmed=0, verified_corrected=0))

    assert stats.total_diagnoses_performed == 0
    assert stats.resolution.counted == 0
    assert stats.resolution.similar_cases_pct is None and stats.resolution.general_reasoning_pct is None
    assert (stats.average_confidence.retrieval, stats.average_confidence.llm, stats.average_confidence.image) == (None, None, None)
    assert (stats.review.pending, stats.review.confirmed, stats.review.corrected) == (0, 0, 0)


def test_build_stats_rounds_averages_to_three_decimals():
    stats = build_stats(
        _summary(avg_retrieval_confidence=0.123456, avg_llm_confidence=0.8, avg_image_confidence=2 / 3), None
    )

    assert stats.average_confidence.retrieval == 0.123
    assert stats.average_confidence.llm == 0.8
    assert stats.average_confidence.image == 0.667


def test_without_a_vector_store_the_knowledge_base_fields_are_null_but_usage_is_kept():
    stats = build_stats(_summary(total=4, by_source={"text": 4}), None)

    assert stats.total_diagnoses_performed == 4
    assert (stats.knowledge_base_size, stats.original_seed_count, stats.technician_verified_count) == (None, None, None)


# --- the SQL aggregates, against a real (in-memory) database ----------------------------------------------------
def _ticket(session, *, source="text", basis=None, retrieval=0.5, llm=None):
    return TicketService(session).create_ticket(
        source=source,
        description="d",
        severity=Severity.LOW,
        diagnosis="x",
        recommended_action="y",
        confidence_score=retrieval,
        diagnosis_basis=basis,
        llm_confidence=llm,
    )


@pytest.fixture
def session(db_session_factory):
    s = db_session_factory()
    yield s
    s.close()


def test_usage_summary_of_an_empty_database(session):
    summary = TicketService(session).usage_summary()

    assert summary["total"] == 0 and summary["by_source"] == {} and summary["by_basis"] == {}
    assert summary["avg_retrieval_confidence"] is None and summary["avg_llm_confidence"] is None


def test_usage_summary_counts_and_averages_are_exact(session):
    _ticket(session, basis="similar_cases", retrieval=0.6, llm=0.9)
    _ticket(session, basis="similar_cases", retrieval=0.8, llm=0.7)
    _ticket(session, basis="general_reasoning", retrieval=0.1, llm=0.5)
    _ticket(session, source="image", retrieval=0.9)  # a photo: its confidence is the MODEL's, not retrieval

    summary = TicketService(session).usage_summary()

    assert summary["total"] == 4
    assert summary["by_source"] == {"text": 3, "image": 1}
    assert summary["by_basis"] == {"similar_cases": 2, "general_reasoning": 1}
    assert summary["avg_retrieval_confidence"] == pytest.approx((0.6 + 0.8 + 0.1) / 3)  # text tickets only
    assert summary["avg_image_confidence"] == pytest.approx(0.9)  # not mixed into the retrieval average
    assert summary["avg_llm_confidence"] == pytest.approx((0.9 + 0.7 + 0.5) / 3)


def test_tickets_from_before_the_basis_column_existed_are_not_counted_as_either_kind(session):
    _ticket(session, basis=None)  # legacy row: basis unknown
    _ticket(session, basis="similar_cases")

    summary = TicketService(session).usage_summary()
    stats = build_stats(summary, None)

    assert summary["total"] == 2  # it is still a diagnosis that was performed...
    assert stats.resolution.counted == 1 and stats.resolution.similar_cases_pct == 100.0  # ...but not guessed into a bucket


def test_a_missing_llm_confidence_is_left_out_of_the_average_not_counted_as_zero(session):
    _ticket(session, llm=0.8)
    _ticket(session, llm=None)  # the model gave no usable number

    assert TicketService(session).usage_summary()["avg_llm_confidence"] == pytest.approx(0.8)


# --- the endpoint -------------------------------------------------------------------------------------------------------
def _diagnose(client, text):
    response = client.post("/api/v1/diagnose", json={"description": text})
    assert response.status_code == 200
    return response.json()


def _stats(client):
    response = client.get("/api/v1/stats")
    assert response.status_code == 200
    return response.json()


def test_stats_on_a_fresh_system_shows_only_the_seed_knowledge_base(client):
    body = _stats(client)

    assert body["total_diagnoses_performed"] == 0
    assert body["resolution"]["similar_cases_pct"] is None  # nothing to divide yet
    assert body["technician_verified_count"] == 0
    assert body["knowledge_base_size"] == body["original_seed_count"] == SEED_COUNT
    assert body["average_confidence"] == {"retrieval": None, "llm": None, "image": None}


def test_stats_reflect_real_diagnoses(client):
    _diagnose(client, RELATED)
    _diagnose(client, RELATED)
    _diagnose(client, RELATED)
    _diagnose(client, UNRELATED)

    body = _stats(client)

    assert body["total_diagnoses_performed"] == 4
    assert body["text_diagnoses"] == 4 and body["image_diagnoses"] == 0
    assert body["resolution"]["similar_cases"] == 3 and body["resolution"]["general_reasoning"] == 1
    assert (body["resolution"]["similar_cases_pct"], body["resolution"]["general_reasoning_pct"]) == (75.0, 25.0)
    assert body["review"] == {"pending": 4, "confirmed": 0, "corrected": 0}


def test_average_confidences_match_the_values_the_diagnoses_actually_returned(client):
    returned = [_diagnose(client, text) for text in (RELATED, RELATED, UNRELATED)]

    body = _stats(client)

    expected_retrieval = sum(r["retrieval_confidence"] for r in returned) / 3
    assert body["average_confidence"]["retrieval"] == pytest.approx(expected_retrieval, abs=0.001)
    assert body["average_confidence"]["llm"] == pytest.approx(0.72)  # the fake LLM always says 72%


def test_photo_diagnoses_are_counted_but_do_not_distort_the_text_breakdown(client):
    _diagnose(client, RELATED)
    assert client.post("/api/v1/diagnose-image", files={"file": ("pump.png", PNG_BYTES, "image/png")}).status_code == 200

    body = _stats(client)

    assert body["total_diagnoses_performed"] == 2
    assert (body["text_diagnoses"], body["image_diagnoses"]) == (1, 1)
    assert body["resolution"]["counted"] == 1  # only the text diagnosis has a retrieval basis
    assert body["average_confidence"]["image"] == pytest.approx(0.8)  # the fake vision model's certainty


def test_inputs_rejected_as_not_equipment_are_not_counted(client, fake_llm):
    fake_llm.result = LLMDiagnosis(
        root_cause="Not an equipment issue.", recommended_fix="Describe the equipment.", severity=Severity.LOW, is_valid_issue=False
    )
    _diagnose(client, "what is the capital of France")

    assert _stats(client)["total_diagnoses_performed"] == 0  # same rule as /history: it was never stored


def test_confirming_a_case_grows_the_verified_count_and_the_review_counts(client):
    first = _diagnose(client, RELATED)["ticket_id"]
    second = _diagnose(client, UNRELATED)["ticket_id"]
    _diagnose(client, RELATED)  # stays pending
    assert client.post(f"/api/v1/tickets/{first}/confirm").status_code == 200
    assert client.post(f"/api/v1/tickets/{second}/correct", json={"root_cause": "Real cause.", "recommended_fix": "Real fix."}).status_code == 200

    body = _stats(client)

    assert body["technician_verified_count"] == 2
    assert body["original_seed_count"] == SEED_COUNT
    assert body["knowledge_base_size"] == SEED_COUNT + 2  # seed + verified: the number retrieval can actually search
    assert body["review"] == {"pending": 1, "confirmed": 1, "corrected": 1}


def test_stats_still_answer_with_usage_numbers_when_the_vector_store_is_down(client, knowledge_base, monkeypatch):
    _diagnose(client, RELATED)

    def broken():
        raise KnowledgeBaseUpdateError("down")

    monkeypatch.setattr(knowledge_base, "stats", broken)
    body = _stats(client)

    assert body["total_diagnoses_performed"] == 1
    assert body["knowledge_base_size"] is None and body["technician_verified_count"] is None


def test_the_stats_endpoint_is_not_rate_limited(client, app):
    app.state.rate_limiter = RateLimiter(1, 60)  # the strictest possible limit on the AI endpoints

    assert [client.get("/api/v1/stats").status_code for _ in range(5)] == [200] * 5


def test_stats_is_documented_in_the_openapi_spec(client):
    assert "/api/v1/stats" in client.get("/openapi.json").json()["paths"]
