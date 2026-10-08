"""Review endpoints and the feedback loop, through FastAPI's TestClient.

The test app's diagnosis service and knowledge-base service share ONE in-memory Chroma collection,
exactly like production, so these tests can prove that a confirmed case is retrieved afterwards.
"""

import pytest

from app.schemas.enums import Severity
from app.services.llm_service import LLMDiagnosis

REPORT_A = "laptop battery drains quickly and the laptop shuts down suddenly"
REPORT_B = "my laptop battery drains quickly and shuts down suddenly"  # a different report, same problem


def _diagnose(client, text=REPORT_A):
    response = client.post("/api/v1/diagnose", json={"description": text})
    assert response.status_code == 200
    return response.json()


def _verified_ids(body):
    return [c["id"] for c in body["similar_cases"] if c["source"] == "verified"]


# --- confirm ------------------------------------------------------------------------------------------------
def test_confirm_marks_the_ticket_confirmed_and_adds_it_to_the_knowledge_base(client):
    ticket_id = _diagnose(client)["ticket_id"]
    before = client.get("/api/v1/knowledge-base/stats").json()

    response = client.post(f"/api/v1/tickets/{ticket_id}/confirm")

    assert response.status_code == 200
    body = response.json()
    assert (body["ticket_id"], body["review_status"]) == (ticket_id, "confirmed")
    assert body["added_to_knowledge_base"] is True and body["kb_record_id"].startswith(f"VC-{ticket_id}-")
    assert body["reviewed_at"] is not None and body["corrected_root_cause"] is None
    assert body["knowledge_base"]["verified"] == 1 and body["knowledge_base"]["total"] == before["total"] + 1


def test_confirm_accepts_an_optional_equipment_type(client):
    ticket_id = _diagnose(client)["ticket_id"]

    assert client.post(f"/api/v1/tickets/{ticket_id}/confirm", json={"equipment_type": "laptop"}).status_code == 200


def test_confirming_twice_is_harmless(client):
    ticket_id = _diagnose(client)["ticket_id"]
    first = client.post(f"/api/v1/tickets/{ticket_id}/confirm").json()
    second = client.post(f"/api/v1/tickets/{ticket_id}/confirm").json()

    assert second["kb_record_id"] == first["kb_record_id"]
    assert second["knowledge_base"]["verified"] == 1  # still one record


# --- correct ---------------------------------------------------------------------------------------------------
def test_correct_stores_the_technicians_version_beside_the_original_diagnosis(client):
    original = _diagnose(client)
    payload = {"root_cause": "Swollen cell pushing the pack out of spec.", "recommended_fix": "Replace the battery pack."}

    response = client.post(f"/api/v1/tickets/{original['ticket_id']}/correct", json=payload)

    assert response.status_code == 200
    assert response.json()["review_status"] == "corrected"
    item = client.get("/api/v1/history").json()["items"][0]
    assert item["review_status"] == "corrected"
    assert (item["corrected_root_cause"], item["corrected_fix"]) == (payload["root_cause"], payload["recommended_fix"])
    assert item["diagnosis"] == original["diagnosis"]  # the AI's version is still there to compare


@pytest.mark.parametrize(
    "body",
    [{}, {"root_cause": "ok cause here"}, {"root_cause": "x", "recommended_fix": "fix that is long enough"}, {"root_cause": "   ", "recommended_fix": "fix that is long enough"}],
)
def test_correct_validates_its_body_with_clear_messages(client, body):
    ticket_id = _diagnose(client)["ticket_id"]

    response = client.post(f"/api/v1/tickets/{ticket_id}/correct", json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert client.get("/api/v1/history").json()["items"][0]["review_status"] == "pending"  # unchanged


# --- transitions & errors --------------------------------------------------------------------------------------------
def test_a_corrected_ticket_cannot_be_confirmed(client):
    ticket_id = _diagnose(client)["ticket_id"]
    client.post(f"/api/v1/tickets/{ticket_id}/correct", json={"root_cause": "The real cause.", "recommended_fix": "The real fix."})

    response = client.post(f"/api/v1/tickets/{ticket_id}/confirm")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "review_conflict"
    assert client.get("/api/v1/history").json()["items"][0]["review_status"] == "corrected"


def test_a_confirmed_ticket_can_be_corrected_afterwards(client):
    ticket_id = _diagnose(client)["ticket_id"]
    first = client.post(f"/api/v1/tickets/{ticket_id}/confirm").json()

    second = client.post(f"/api/v1/tickets/{ticket_id}/correct", json={"root_cause": "Actually a bad cell.", "recommended_fix": "Replace the pack."}).json()

    assert second["review_status"] == "corrected" and second["kb_record_id"] == first["kb_record_id"]
    assert second["knowledge_base"]["verified"] == 1  # updated in place, not duplicated


@pytest.mark.parametrize("path, body", [("confirm", None), ("correct", {"root_cause": "A cause.", "recommended_fix": "A fix."})])
def test_reviewing_an_unknown_ticket_is_a_404(client, path, body):
    response = client.post(f"/api/v1/tickets/9999/{path}", json=body)
    assert response.status_code == 404 and response.json()["error"]["code"] == "ticket_not_found"


def test_if_the_knowledge_base_cannot_be_updated_the_review_is_not_saved(client, knowledge_base, monkeypatch):
    ticket_id = _diagnose(client)["ticket_id"]

    def boom(**kwargs):
        raise RuntimeError("chroma is down")

    monkeypatch.setattr(knowledge_base._collection, "upsert", boom)

    response = client.post(f"/api/v1/tickets/{ticket_id}/confirm")

    assert response.status_code == 503 and response.json()["error"]["code"] == "knowledge_base_unavailable"
    assert "Traceback" not in response.text
    assert client.get("/api/v1/history").json()["items"][0]["review_status"] == "pending"


# --- the history list ---------------------------------------------------------------------------------------------------
def test_history_shows_review_status_and_priority(client, fake_llm):
    fake_llm.result = LLMDiagnosis(root_cause="a", recommended_fix="b", severity=Severity.LOW)
    low = _diagnose(client, "the display looks slightly different today")  # nothing alarming => low
    high = _diagnose(client, "motor overheating with smoke and burning smell")  # heuristic forces high

    items = {t["id"]: t for t in client.get("/api/v1/history").json()["items"]}

    assert (items[low["ticket_id"]]["review_status"], items[low["ticket_id"]]["review_priority"]) == ("pending", "low")
    assert (items[high["ticket_id"]]["review_status"], items[high["ticket_id"]]["review_priority"]) == ("pending", "high")


def test_pending_filter_lists_high_priority_first_and_excludes_reviewed_tickets(client, fake_llm):
    fake_llm.result = LLMDiagnosis(root_cause="a", recommended_fix="b", severity=Severity.LOW)
    high_old = _diagnose(client, "motor overheating with smoke and burning smell")["ticket_id"]
    low_mid = _diagnose(client, "the display looks slightly different today")["ticket_id"]
    reviewed = _diagnose(client, "another printer paper jam in the tray")["ticket_id"]
    client.post(f"/api/v1/tickets/{reviewed}/confirm")
    low_new = _diagnose(client, "the status light blinks once in a while")["ticket_id"]

    pending = client.get("/api/v1/history", params={"review_status": "pending"}).json()

    assert pending["total"] == 3
    assert [t["id"] for t in pending["items"]] == [high_old, low_new, low_mid]  # high priority first, then newest
    assert reviewed not in [t["id"] for t in pending["items"]]
    confirmed = client.get("/api/v1/history", params={"review_status": "confirmed"}).json()
    assert [t["id"] for t in confirmed["items"]] == [reviewed]
    assert client.get("/api/v1/history", params={"review_status": "bogus"}).status_code == 422


# --- the feedback loop itself: a confirmed case improves later retrieval -----------------------------------------------------------
def test_a_confirmed_case_is_retrieved_for_a_later_similar_report(client):
    first = _diagnose(client, REPORT_A)
    assert _verified_ids(first) == []  # nothing verified yet
    top_seed_score = first["similar_cases"][0]["similarity_score"]

    record_id = client.post(f"/api/v1/tickets/{first['ticket_id']}/confirm").json()["kb_record_id"]
    second = _diagnose(client, REPORT_B)

    best = second["similar_cases"][0]
    assert best["id"] == record_id and best["source"] == "verified"  # the confirmed case is now the closest match
    assert best["issue_description"] == REPORT_A
    assert best["similarity_score"] > top_seed_score  # and a far better match than anything seeded
    assert second["diagnosis_basis"] == "similar_cases"  # so the LLM now gets a grounded example


def test_a_corrected_case_returns_the_technicians_root_cause_and_fix(client):
    first = _diagnose(client, REPORT_A)
    fix = {"root_cause": "Battery controller board failure.", "recommended_fix": "Replace the controller board."}
    client.post(f"/api/v1/tickets/{first['ticket_id']}/correct", json=fix)

    best = _diagnose(client, REPORT_B)["similar_cases"][0]

    assert best["source"] == "verified"
    assert (best["root_cause"], best["recommended_fix"]) == (fix["root_cause"], fix["recommended_fix"])  # not the AI's guess


def test_an_unconfirmed_ticket_is_not_retrieved_later(client):
    _diagnose(client, REPORT_A)  # left pending

    second = _diagnose(client, REPORT_B)

    assert _verified_ids(second) == []
    assert client.get("/api/v1/knowledge-base/stats").json()["verified"] == 0


def test_a_thumbs_up_adds_the_diagnosis_to_the_knowledge_base_as_provisional(client):
    # Feedback teaches the knowledge base in both directions (see test_feedback_kb.py), but one end-user click is
    # only one confirmation, so the fix is provisional until a technician verifies it (see test_confirmations.py).
    ticket_id = _diagnose(client)["ticket_id"]

    client.post("/api/v1/feedback", json={"ticket_id": ticket_id, "was_correct": True})

    stats = client.get("/api/v1/knowledge-base/stats").json()
    assert (stats["provisional"], stats["verified"]) == (1, 0)


# --- statistics -------------------------------------------------------------------------------------------------------------------------
def test_stats_report_seed_versus_verified_records(client):
    stats = client.get("/api/v1/knowledge-base/stats").json()
    assert stats["seed"] == 28 and stats["verified"] == 0 and stats["total"] == 28

    a, b = _diagnose(client, REPORT_A)["ticket_id"], _diagnose(client, "pump seal leaking oil badly")["ticket_id"]
    client.post(f"/api/v1/tickets/{a}/confirm")
    client.post(f"/api/v1/tickets/{b}/correct", json={"root_cause": "Worn mechanical seal.", "recommended_fix": "Replace the seal."})

    stats = client.get("/api/v1/knowledge-base/stats").json()
    # Technician reviews are worth two confirmations, so both are verified (provisional is the new, additive key).
    assert stats == {"total": 30, "seed": 28, "verified": 2, "verified_confirmed": 1, "verified_corrected": 1, "failed": 0, "provisional": 0}


def test_openapi_documents_the_review_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path in ("/api/v1/tickets/{ticket_id}/confirm", "/api/v1/tickets/{ticket_id}/correct", "/api/v1/knowledge-base/stats"):
        assert path in paths
