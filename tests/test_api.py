"""API tests using FastAPI's TestClient (in-memory SQLite + in-memory Chroma)."""

from app.api.deps import get_diagnosis_service
from app.core.exceptions import LLMResponseError, LLMUnavailableError
from app.schemas.enums import Severity
from app.services.llm_service import LLMDiagnosis
from tests.conftest import FAKE_FIX, FAKE_ROOT_CAUSE

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
# Words that appear nowhere in the knowledge base => no close match.
NO_MATCH_TEXT = "quantum zebra teapot marmalade volcano"


def _diagnose(client, text="pump making loud grinding noise and leaking oil"):
    return client.post("/api/v1/diagnose", json={"description": text})


# --- /health ---------------------------------------------------------------
def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["llm"] == "ok"
    assert body["knowledge_base_size"] >= 25


def test_health_reports_degraded_with_503_when_the_llm_is_down(client, fake_llm):
    fake_llm.ready = False

    response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["llm"] == "error"
    assert body["database"] == "ok" and body["vector_store"] == "ok"


# --- /diagnose -------------------------------------------------------------
def test_diagnose_returns_llm_diagnosis_with_retrieved_context(client, fake_llm):
    response = _diagnose(client)

    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"ticket_id", "severity", "diagnosis", "recommended_action",
                         "confidence_score", "similar_cases", "diagnosis_basis", "note"}

    # diagnosis / recommended_action come from the LLM, not from a knowledge-base record...
    assert body["diagnosis"] == FAKE_ROOT_CAUSE
    assert body["recommended_action"] == FAKE_FIX
    assert body["diagnosis"] != body["similar_cases"][0]["root_cause"]
    # ...grounded in the retrieved cases, which are also returned for transparency.
    assert body["diagnosis_basis"] == "similar_cases" and body["note"] is None
    assert len(body["similar_cases"]) == 3
    assert [c.id for c in fake_llm.calls[0][1]] == [c["id"] for c in body["similar_cases"]]
    # Best match first, and it should be a pump issue for a pump description.
    scores = [c["similarity_score"] for c in body["similar_cases"]]
    assert scores == sorted(scores, reverse=True)
    assert body["similar_cases"][0]["equipment_type"] == "pump"
    # confidence = retrieval similarity of the best case.
    assert body["confidence_score"] == scores[0] and 0 < body["confidence_score"] <= 1
    # Severity: heuristic says HIGH (grinding + leaking + noise); the fake LLM said MEDIUM.
    assert body["severity"] == "high"
    assert response.headers["X-Request-ID"]


def test_diagnose_with_no_close_match_uses_general_reasoning_and_says_so(client, fake_llm):
    response = _diagnose(client, NO_MATCH_TEXT)

    assert response.status_code == 200
    body = response.json()
    assert body["diagnosis_basis"] == "general_reasoning"
    assert body["note"] == "No closely matching past case found - diagnosis based on general reasoning."
    assert body["note"].isascii()  # must survive clients that mis-decode UTF-8 JSON (see NO_MATCH_NOTE)
    assert body["confidence_score"] < 0.2  # low retrieval similarity is reported honestly
    assert body["diagnosis"] == FAKE_ROOT_CAUSE  # the LLM still produced the diagnosis
    assert len(body["similar_cases"]) == 3  # retrieved cases are still shown
    assert fake_llm.calls[0][1] == []  # but the LLM was not given them as context


def test_final_severity_is_never_lower_than_the_keyword_heuristic(client, fake_llm):
    fake_llm.result = LLMDiagnosis(root_cause="a", recommended_fix="b", severity=Severity.LOW)

    assert _diagnose(client, "the printer is smoking and smells burnt").json()["severity"] == "high"


def test_llm_can_raise_severity_above_the_keyword_heuristic(client, fake_llm):
    fake_llm.result = LLMDiagnosis(root_cause="a", recommended_fix="b", severity=Severity.HIGH)

    assert _diagnose(client, "the conveyor chain snapped overnight").json()["severity"] == "high"


def test_llm_unavailable_returns_503_with_clean_error_and_stores_nothing(client, fake_llm):
    fake_llm.error = LLMUnavailableError("The diagnosis language model is currently unavailable.")

    response = _diagnose(client)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "llm_unavailable"
    assert "Traceback" not in response.text
    assert client.get("/api/v1/history").json()["total"] == 0  # no ticket for a failed diagnosis


def test_unusable_llm_output_returns_502(client, fake_llm):
    fake_llm.error = LLMResponseError("The language model returned an unusable response.")

    response = _diagnose(client)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "llm_bad_response"


def test_diagnose_rejects_too_short_description_with_clear_message(client):
    response = client.post("/api/v1/diagnose", json={"description": "pump"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["field"] == "description"
    assert "at least 10 characters" in error["details"][0]["message"]


def test_diagnose_rejects_whitespace_only_and_missing_description(client):
    assert client.post("/api/v1/diagnose", json={"description": " " * 20}).status_code == 422
    assert client.post("/api/v1/diagnose", json={}).status_code == 422


def test_unexpected_error_returns_generic_500_without_leaking_details(app, client):
    class Exploding:
        def diagnose(self, _):
            raise RuntimeError("secret internal detail /etc/passwd")

    app.dependency_overrides[get_diagnosis_service] = lambda: Exploding()

    response = _diagnose(client)

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert error["request_id"]
    assert "secret" not in response.text and "Traceback" not in response.text


def test_unknown_route_uses_standard_error_shape(client):
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_error"


# --- /history --------------------------------------------------------------
def test_history_lists_every_diagnosis_newest_first(client):
    first = _diagnose(client, "printer has a paper jam in the tray").json()["ticket_id"]
    second = _diagnose(client, "motor overheating with burning smell").json()["ticket_id"]

    body = client.get("/api/v1/history").json()

    assert body["total"] == 2
    assert [t["id"] for t in body["items"]] == [second, first]
    assert body["items"][0]["feedback_was_correct"] is None
    # Timezone-aware UTC (pydantic renders UTC as a trailing "Z"), not a naive local time.
    assert body["items"][0]["created_at"].endswith(("Z", "+00:00"))


def test_history_pagination(client):
    for i in range(5):
        _diagnose(client, f"pump leaking oil near seal, report number {i}")

    page1 = client.get("/api/v1/history", params={"page": 1, "page_size": 2}).json()
    page3 = client.get("/api/v1/history", params={"page": 3, "page_size": 2}).json()
    beyond = client.get("/api/v1/history", params={"page": 9, "page_size": 2}).json()

    assert (page1["total"], page1["total_pages"], len(page1["items"])) == (5, 3, 2)
    assert len(page3["items"]) == 1
    assert beyond["items"] == []
    ids = [t["id"] for t in page1["items"]] + [t["id"] for t in
          client.get("/api/v1/history", params={"page": 2, "page_size": 2}).json()["items"]]
    assert len(set(ids)) == 4  # no overlap between pages


def test_history_rejects_invalid_pagination(client):
    assert client.get("/api/v1/history", params={"page": 0}).status_code == 422
    assert client.get("/api/v1/history", params={"page_size": 101}).status_code == 422


# --- /feedback -------------------------------------------------------------
def test_feedback_is_stored_and_visible_in_history(client):
    ticket_id = _diagnose(client).json()["ticket_id"]

    response = client.post("/api/v1/feedback", json={"ticket_id": ticket_id, "was_correct": True})

    assert response.status_code == 201
    assert response.json()["ticket_id"] == ticket_id and response.json()["was_correct"] is True
    assert client.get("/api/v1/history").json()["items"][0]["feedback_was_correct"] is True


def test_feedback_resubmission_updates_instead_of_duplicating(client):
    ticket_id = _diagnose(client).json()["ticket_id"]
    client.post("/api/v1/feedback", json={"ticket_id": ticket_id, "was_correct": True})

    response = client.post("/api/v1/feedback", json={"ticket_id": ticket_id, "was_correct": False})

    assert response.status_code == 200
    assert response.json()["was_correct"] is False


def test_feedback_for_unknown_ticket_is_404(client):
    response = client.post("/api/v1/feedback", json={"ticket_id": 9999, "was_correct": True})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ticket_not_found"


def test_feedback_validates_body(client):
    assert client.post("/api/v1/feedback", json={"ticket_id": 1}).status_code == 422
    assert client.post("/api/v1/feedback", json={"ticket_id": 1, "was_correct": "maybe"}).status_code == 422


# --- /diagnose-image -------------------------------------------------------
def test_diagnose_image_returns_flagged_placeholder_result(client):
    response = client.post("/api/v1/diagnose-image", files={"file": ("pump.png", PNG_BYTES, "image/png")})

    assert response.status_code == 200
    body = response.json()
    assert body["is_placeholder"] is True
    assert body["diagnosis"].startswith("[PLACEHOLDER]")
    # Deterministic: same image => same answer.
    again = client.post("/api/v1/diagnose-image", files={"file": ("pump.png", PNG_BYTES, "image/png")})
    assert again.json()["diagnosis"] == body["diagnosis"]
    # And it is recorded in history.
    assert client.get("/api/v1/history").json()["items"][0]["source"] == "image"


def test_diagnose_image_rejects_non_images(client):
    response = client.post("/api/v1/diagnose-image", files={"file": ("notes.png", b"not an image", "image/png")})
    assert response.status_code == 415


def test_diagnose_image_rejects_empty_and_oversized_files(app, client):
    empty = client.post("/api/v1/diagnose-image", files={"file": ("a.png", b"", "image/png")})
    assert empty.status_code == 422

    limit = app.state.settings.max_image_size_bytes
    huge = PNG_BYTES + b"\x00" * limit
    too_big = client.post("/api/v1/diagnose-image", files={"file": ("a.png", huge, "image/png")})
    assert too_big.status_code == 413


def test_diagnose_image_requires_file(client):
    assert client.post("/api/v1/diagnose-image").status_code == 422


# --- docs ------------------------------------------------------------------
def test_openapi_documents_all_endpoints(client):
    spec = client.get("/openapi.json").json()
    for path in ["/health", "/api/v1/diagnose", "/api/v1/diagnose-image", "/api/v1/history", "/api/v1/feedback"]:
        assert path in spec["paths"]
    assert client.get("/docs").status_code == 200


# --- non-equipment input is answered but never stored -----------------------------------------
def _llm_rejects(fake_llm):
    fake_llm.result = LLMDiagnosis(
        root_cause="This is a general question, not an equipment issue.",
        recommended_fix="Please describe the equipment problem.",
        severity=Severity.LOW,
        is_valid_issue=False,
    )


def test_valid_issue_is_flagged_valid_and_stored(client):
    body = _diagnose(client).json()

    assert body["is_valid_issue"] is True
    assert body["ticket_id"] is not None
    assert client.get("/api/v1/history").json()["total"] == 1


def test_non_equipment_input_is_flagged_and_not_saved_to_history(client, fake_llm):
    _llm_rejects(fake_llm)

    response = _diagnose(client, "what is the capital of France")

    assert response.status_code == 200
    body = response.json()
    assert body["is_valid_issue"] is False
    assert body["ticket_id"] is None and body["severity"] is None
    assert body["similar_cases"] == []
    assert body["note"] == "This does not appear to describe an equipment issue, so it was not saved to ticket history."
    assert body["diagnosis"] == "This is a general question, not an equipment issue."
    assert client.get("/api/v1/history").json()["total"] == 0  # history stays clean


def test_rejected_input_does_not_consume_ticket_ids_or_block_later_tickets(client, fake_llm):
    _llm_rejects(fake_llm)
    _diagnose(client, "what is the capital of France")
    fake_llm.result = type(fake_llm)().result  # back to the default "valid issue" answer

    assert _diagnose(client).json()["ticket_id"] == 1


def test_a_real_emergency_is_saved_even_if_the_llm_calls_it_invalid(client, fake_llm):
    _llm_rejects(fake_llm)

    body = _diagnose(client, "machine caught fire and there is smoke everywhere").json()

    assert body["is_valid_issue"] is True and body["severity"] == "high"
    assert client.get("/api/v1/history").json()["total"] == 1
