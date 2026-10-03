"""Thumbs up / thumbs down teach the knowledge base in BOTH directions.

    thumbs up   -> a "verified_fix" record (as a technician's confirm does)
    thumbs down -> an additional "failed_fix" record of the diagnosis + fix that did NOT work
    later, separate, similar requests -> the LLM sees both groups, clearly labelled

The test app uses a REAL in-memory ChromaDB (shared by retrieval and the knowledge-base writer), so
these tests exercise the actual feedback -> vector store -> retrieval -> prompt chain.
"""

import json

import httpx
import pytest

from app.api.deps import get_diagnosis_service
from app.core.exceptions import KnowledgeBaseUpdateError
from app.db.seed import load_records, seed_knowledge_base
from app.models.ticket import Ticket
from app.schemas.enums import Severity
from app.services.diagnosis_service import FAILED_FIXES, REPEAT_NOTE, WORKING_FIXES, DiagnosisService
from app.services.llm_service import LLMDiagnosis, LLMService, build_messages
from app.schemas.knowledge_base import SimilarCase
from tests.conftest import KNOWLEDGE_BASE_PATH
from tests.test_groq_service import completion, make_service

FIRST = "pump making a loud grinding noise and leaking oil from the seal"
SIMILAR = "my pump grinds loudly and oil leaks near the seal"  # a different, LATER request with a similar symptom
UNRELATED = "zqxv wplk jrmt"  # shares no words with anything

# Two clearly different solutions (different words, so the fake bag-of-words embedder tells them apart).
CAUSE_A, FIX_A = "Worn bearings and a degraded shaft seal.", "Replace the bearings and the mechanical seal."
CAUSE_B, FIX_B = "Cavitation from a clogged suction strainer.", "Clean the strainer and check inlet pressure."
SOLUTION_A = LLMDiagnosis(root_cause=CAUSE_A, recommended_fix=FIX_A, severity=Severity.MEDIUM, confidence=80)
SOLUTION_B = LLMDiagnosis(root_cause=CAUSE_B, recommended_fix=FIX_B, severity=Severity.MEDIUM, confidence=70)

WORKING_HEADER = "Similar past cases with CONFIRMED WORKING fixes"
FAILED_HEADER = "Similar past cases where THIS approach did NOT resolve the issue"


def diagnose(client, text=FIRST) -> dict:
    response = client.post("/api/v1/diagnose", json={"description": text})
    assert response.status_code == 200, response.text
    return response.json()


def thumbs(client, ticket_id: int, up: bool):
    return client.post("/api/v1/feedback", json={"ticket_id": ticket_id, "was_correct": up})


def record(collection, record_id: str) -> dict:
    return collection.get(ids=[record_id], include=["metadatas"])["metadatas"][0]


def history_item(client, ticket_id: int) -> dict:
    return next(i for i in client.get("/api/v1/history?page_size=100").json()["items"] if i["id"] == ticket_id)


# =============================================================================================================
# 1. Thumbs DOWN creates a failed_fix record
# =============================================================================================================
def test_thumbs_down_creates_a_failed_fix_record_of_what_did_not_work(client, seeded_collection):
    first = diagnose(client)

    response = thumbs(client, first["ticket_id"], up=False)

    assert response.status_code == 201
    body = response.json()
    assert (body["was_correct"], body["knowledge_base_outcome"], body["knowledge_base_updated"]) == (False, "failed_fix", True)
    assert body["kb_record_id"].startswith(f"FC-{first['ticket_id']}-")
    stored = record(seeded_collection, body["kb_record_id"])
    assert (stored["outcome"], stored["source"]) == ("failed_fix", "feedback")
    assert stored["issue_description"] == FIRST  # the original issue...
    assert (stored["root_cause"], stored["recommended_fix"]) == (first["diagnosis"], first["recommended_action"])  # ...and what failed
    assert stored["ticket_id"] == first["ticket_id"]


def test_thumbs_down_is_an_extra_signal_only_it_deletes_nothing_and_reviews_nothing(client, seeded_collection):
    first = diagnose(client)
    before = set(seeded_collection.get()["ids"])

    failed_id = thumbs(client, first["ticket_id"], up=False).json()["kb_record_id"]

    assert set(seeded_collection.get()["ids"]) == before | {failed_id}  # exactly one record added, none removed
    item = history_item(client, first["ticket_id"])
    assert item["review_status"] == "pending"  # not marked reviewed: a technician can still confirm or correct
    assert item["feedback_was_correct"] is False


def test_thumbs_down_does_not_block_a_technician_from_correcting_the_ticket(client, seeded_collection):
    first = diagnose(client)
    failed_id = thumbs(client, first["ticket_id"], up=False).json()["kb_record_id"]

    correction = {"root_cause": "Cavitation at the inlet.", "recommended_fix": "Clear the suction line."}
    assert client.post(f"/api/v1/tickets/{first['ticket_id']}/correct", json=correction).status_code == 200

    verified_id = history_item(client, first["ticket_id"])["kb_record_id"]
    assert record(seeded_collection, failed_id)["outcome"] == "failed_fix"  # the failure is still remembered...
    assert record(seeded_collection, verified_id)["outcome"] == "verified_fix"  # ...next to the technician's real fix
    assert record(seeded_collection, verified_id)["root_cause"] == "Cavitation at the inlet."


def test_a_repeated_thumbs_down_updates_the_same_record_instead_of_adding_another(client, seeded_collection):
    first = diagnose(client)
    a = thumbs(client, first["ticket_id"], up=False)
    count = seeded_collection.count()

    b = thumbs(client, first["ticket_id"], up=False)

    assert b.status_code == 200 and b.json()["kb_record_id"] == a.json()["kb_record_id"]
    assert seeded_collection.count() == count


# =============================================================================================================
# 2. Thumbs UP creates / updates a verified_fix record
# =============================================================================================================
def test_thumbs_up_records_the_fix_but_only_as_provisional_one_click_does_not_verify_it(client, seeded_collection):
    """Changed on purpose by the confirmation safeguard: an end user's click is ONE confirmation (see test_confirmations.py)."""
    first = diagnose(client)

    body = thumbs(client, first["ticket_id"], up=True).json()

    assert (body["knowledge_base_outcome"], body["knowledge_base_updated"]) == ("provisional_fix", True)
    assert (body["verification"], body["confirmation_count"]) == ("provisional", 1)
    assert body["kb_record_id"].startswith(f"VC-{first['ticket_id']}-")
    stored = record(seeded_collection, body["kb_record_id"])
    assert (stored["outcome"], stored["source"], stored["verification"]) == ("provisional_fix", "verified", "provisional")
    assert (stored["confirmation_count"], stored["confirmed_by"]) == (1, "user")
    assert (stored["root_cause"], stored["recommended_fix"]) == (first["diagnosis"], first["recommended_action"])
    assert history_item(client, first["ticket_id"])["review_status"] == "confirmed"  # the same path as a technician's confirm


def test_a_repeated_thumbs_up_does_not_duplicate_the_record(client, seeded_collection):
    first = diagnose(client)
    a = thumbs(client, first["ticket_id"], up=True).json()
    count = seeded_collection.count()

    b = thumbs(client, first["ticket_id"], up=True)

    assert b.status_code == 200
    assert (b.json()["kb_record_id"], b.json()["knowledge_base_updated"]) == (a["kb_record_id"], False)
    assert seeded_collection.count() == count


def test_a_technicians_confirm_still_writes_a_verified_fix_record(client, seeded_collection):
    first = diagnose(client)

    record_id = client.post(f"/api/v1/tickets/{first['ticket_id']}/confirm").json()["kb_record_id"]

    assert record(seeded_collection, record_id)["outcome"] == "verified_fix"


def test_thumbs_up_on_a_ticket_a_technician_corrected_leaves_the_correction_alone(client, seeded_collection):
    first = diagnose(client)
    client.post(f"/api/v1/tickets/{first['ticket_id']}/correct", json={"root_cause": "Real cause.", "recommended_fix": "Real fix."})
    count = seeded_collection.count()

    body = thumbs(client, first["ticket_id"], up=True).json()

    assert (body["knowledge_base_outcome"], body["knowledge_base_updated"]) == (None, False)
    assert seeded_collection.count() == count
    assert history_item(client, first["ticket_id"])["corrected_root_cause"] == "Real cause."


def test_changing_a_thumbs_down_to_up_retracts_that_tickets_own_failed_record(client, seeded_collection):
    first = diagnose(client)
    failed_id = thumbs(client, first["ticket_id"], up=False).json()["kb_record_id"]

    body = thumbs(client, first["ticket_id"], up=True).json()

    assert body["knowledge_base_outcome"] == "provisional_fix"  # a confirmed fix, but only one end-user click so far
    assert seeded_collection.get(ids=[failed_id])["ids"] == []  # the user changed their mind: no contradiction left
    assert client.get("/api/v1/knowledge-base/stats").json()["failed"] == 0


def test_changing_a_thumbs_up_to_down_adds_a_failed_record_and_keeps_the_verified_one(client, seeded_collection):
    """Documented limitation: a verified record may also be a technician's confirmation, so a thumbs-down never deletes it."""
    first = diagnose(client)
    verified_id = thumbs(client, first["ticket_id"], up=True).json()["kb_record_id"]

    body = thumbs(client, first["ticket_id"], up=False).json()

    assert body["knowledge_base_outcome"] == "failed_fix"
    assert seeded_collection.get(ids=[verified_id])["ids"] == [verified_id]


# =============================================================================================================
# 3. If the vector store fails, the verdict is still saved
# =============================================================================================================
def test_a_thumbs_down_is_saved_even_when_the_vector_store_fails(client, knowledge_base, seeded_collection, monkeypatch):
    first = diagnose(client)
    count = seeded_collection.count()

    def broken(ticket):
        raise KnowledgeBaseUpdateError("down")

    monkeypatch.setattr(knowledge_base, "upsert_failed_case", broken)
    response = thumbs(client, first["ticket_id"], up=False)

    assert response.status_code == 201
    assert (response.json()["knowledge_base_outcome"], response.json()["knowledge_base_updated"]) == (None, False)
    assert history_item(client, first["ticket_id"])["feedback_was_correct"] is False  # the verdict itself is kept
    assert seeded_collection.count() == count


def test_a_thumbs_up_is_saved_even_when_the_vector_store_fails(client, knowledge_base, monkeypatch):
    first = diagnose(client)

    def broken(ticket):
        raise KnowledgeBaseUpdateError("down")

    monkeypatch.setattr(knowledge_base, "upsert_ticket_case", broken)
    response = thumbs(client, first["ticket_id"], up=True)

    assert response.status_code == 201 and response.json()["knowledge_base_updated"] is False
    item = history_item(client, first["ticket_id"])
    assert item["feedback_was_correct"] is True and item["review_status"] == "pending"  # nothing half-done


# =============================================================================================================
# 4. Retrieval: both outcome types, kept apart
# =============================================================================================================
def test_a_later_similar_request_gets_the_failed_fix_separately_never_as_a_working_case(client):
    first = diagnose(client)
    failed_id = thumbs(client, first["ticket_id"], up=False).json()["kb_record_id"]

    second = diagnose(client, SIMILAR)

    assert second["ticket_id"] != first["ticket_id"]  # a separate request, no link to the first one
    assert failed_id not in [c["id"] for c in second["similar_cases"]]  # never offered as a working fix
    assert [c["id"] for c in second["similar_failed_cases"]] == [failed_id]
    assert second["similar_failed_cases"][0]["outcome"] == "failed_fix"
    assert second["similar_failed_cases"][0]["root_cause"] == first["diagnosis"]


def test_the_llm_receives_the_failed_fix_as_its_own_group(client, fake_llm):
    first = diagnose(client)
    thumbs(client, first["ticket_id"], up=False)

    diagnose(client, SIMILAR)

    working, failed = fake_llm.calls[-1][1], fake_llm.failed_examples_per_call[-1]
    assert [c.outcome for c in failed] == ["failed_fix"] and failed[0].issue_description == FIRST
    assert all(c.outcome != "failed_fix" for c in working)


def test_an_unrelated_request_is_not_steered_by_the_failed_fix(client, fake_llm):
    first = diagnose(client)
    thumbs(client, first["ticket_id"], up=False)

    unrelated = diagnose(client, UNRELATED)

    assert unrelated["similar_failed_cases"] == []
    assert fake_llm.failed_examples_per_call[-1] == []  # below the similarity bar: never shown to the model


def test_before_any_thumbs_down_there_is_nothing_to_avoid(client, fake_llm):
    diagnose(client)
    second = diagnose(client, SIMILAR)

    assert second["similar_failed_cases"] == [] and fake_llm.failed_examples_per_call[-1] == []


def test_seed_records_without_an_outcome_still_count_as_working_fixes(seeded_collection, fake_embedder, fake_llm):
    """Pins ChromaDB's filter semantics: seed records have NO 'outcome' key, and `$ne` must keep them.
    If an upgrade changed that, every seed would silently vanish from retrieval; this test would fail."""
    seeds = seeded_collection.get(include=["metadatas"])["metadatas"]
    assert seeds and all("outcome" not in m for m in seeds)

    assert len(seeded_collection.get(where=WORKING_FIXES)["ids"]) == 28
    assert seeded_collection.get(where=FAILED_FIXES)["ids"] == []
    service = DiagnosisService(fake_embedder, seeded_collection, fake_llm, top_k=3, low_confidence_threshold=0.2)
    assert [c.source for c in service.find_similar_cases(FIRST)] == ["seed", "seed", "seed"]


# =============================================================================================================
# 5. The prompt: two clearly separated, labelled groups
# =============================================================================================================
def _case(outcome=None, cause="cause", fix="fix") -> SimilarCase:
    return SimilarCase(
        id="X", equipment_type="pump", issue_description="pump is noisy", root_cause=cause,
        recommended_fix=fix, severity=Severity.MEDIUM, similarity_score=0.7, outcome=outcome,
    )


def test_build_messages_labels_working_and_failed_cases_separately():
    user = build_messages(
        "pump grinds", [_case(cause="WORKING-CAUSE", fix="WORKING-FIX")], failed_examples=[_case("failed_fix", "BAD-CAUSE", "BAD-FIX")]
    )[1]["content"]

    working_at, failed_at, issue_at = user.index(WORKING_HEADER), user.index(FAILED_HEADER), user.index("<issue>")
    assert working_at < failed_at < issue_at
    assert working_at < user.index("WORKING-CAUSE") < failed_at  # the working fix sits in the working section...
    assert failed_at < user.index("Diagnosis that did NOT work: BAD-CAUSE") < issue_at  # ...the failed one in the failed section
    assert "Fix that did NOT work: BAD-FIX" in user
    assert "Do not repeat these diagnoses or fixes" in user


def test_failed_cases_are_shown_even_when_no_working_case_is_close():
    user = build_messages("pump grinds", [], failed_examples=[_case("failed_fix", "BAD-CAUSE", "BAD-FIX")])[1]["content"]

    assert "No similar past case with a confirmed working fix was found" in user
    assert FAILED_HEADER in user and "BAD-CAUSE" in user


def test_without_failed_cases_there_is_no_failed_section():
    assert FAILED_HEADER not in build_messages("pump grinds", [_case()])[1]["content"]


def test_the_prompt_actually_sent_to_the_model_carries_the_did_not_work_context(app, client, seeded_collection, fake_embedder):
    """Not just function arguments: a real Groq adapter on a faked network; we read the HTTP request body."""
    prompts: list[str] = []
    answers = iter([SOLUTION_A, SOLUTION_B])

    def handler(request: httpx.Request) -> httpx.Response:
        prompts.append(json.loads(request.content)["messages"][1]["content"])
        answer = next(answers)
        return completion({"root_cause": answer.root_cause, "recommended_fix": answer.recommended_fix,
                           "severity": "medium", "is_valid_issue": True, "confidence": 70})

    service = DiagnosisService(fake_embedder, seeded_collection, make_service(handler), top_k=3, low_confidence_threshold=0.2)
    app.dependency_overrides[get_diagnosis_service] = lambda: service

    first = diagnose(client)
    thumbs(client, first["ticket_id"], up=False)
    diagnose(client, SIMILAR)

    assert FAILED_HEADER not in prompts[0]  # before the feedback: no failed context
    later = prompts[1]
    assert WORKING_HEADER in later and FAILED_HEADER in later
    assert f"Diagnosis that did NOT work: {CAUSE_A}" in later and f"Fix that did NOT work: {FIX_A}" in later
    assert f"Problem: {FIRST}" in later
    assert later.index(WORKING_HEADER) < later.index(FAILED_HEADER) < later.index(CAUSE_A)  # filed under "did NOT work"


# =============================================================================================================
# 6. The key behaviour: a later similar request does not get the same failed suggestion again
# =============================================================================================================
class InstructionFollowingLLM(LLMService):
    """Stands in for a model that reads its prompt: it builds the REAL prompt and suggests the usual fix A,
    unless the prompt says that fix did NOT work, in which case it suggests B. So the only way to get B is
    for the feedback to travel all the way into the prompt."""

    def __init__(self):
        self.prompts: list[str] = []

    def generate_diagnosis(self, user_input, context_examples, previous_attempts=(), failed_examples=()):
        prompt = build_messages(user_input, context_examples, previous_attempts, failed_examples)[1]["content"]
        self.prompts.append(prompt)
        return SOLUTION_B if f"Fix that did NOT work: {FIX_A}" in prompt else SOLUTION_A

    def is_ready(self):
        return True


@pytest.fixture
def instruction_following(app, seeded_collection, fake_embedder):
    llm = InstructionFollowingLLM()
    service = DiagnosisService(fake_embedder, seeded_collection, llm, top_k=3, low_confidence_threshold=0.2)
    app.dependency_overrides[get_diagnosis_service] = lambda: service
    return llm


def test_control_without_negative_feedback_the_same_fix_is_suggested_again(client, instruction_following):
    first = diagnose(client)
    second = diagnose(client, SIMILAR)  # no thumbs-down in between

    assert first["diagnosis"] == second["diagnosis"] == CAUSE_A


def test_after_a_thumbs_down_a_later_similar_request_gets_a_different_suggestion(client, instruction_following):
    first = diagnose(client)
    assert first["recommended_action"] == FIX_A
    thumbs(client, first["ticket_id"], up=False)

    second = diagnose(client, SIMILAR)

    assert second["recommended_action"] == FIX_B and second["diagnosis"] == CAUSE_B  # not the failed suggestion
    assert f"Fix that did NOT work: {FIX_A}" in instruction_following.prompts[-1]


def test_a_model_that_ignores_the_warning_is_asked_once_more(client, fake_llm):
    fake_llm.results = [SOLUTION_A, SOLUTION_A, SOLUTION_B]  # the 2nd call repeats the failed fix anyway
    first = diagnose(client)
    thumbs(client, first["ticket_id"], up=False)

    second = diagnose(client, SIMILAR)

    assert second["diagnosis"] == CAUSE_B  # the user never sees the repeat
    assert len(fake_llm.calls) == 3
    assert [a.root_cause for a in fake_llm.previous_attempts_per_call[2]] == [CAUSE_A]  # the repeat was listed as ruled out
    assert second["note"] is None or REPEAT_NOTE not in second["note"]


def test_a_model_that_keeps_repeating_is_retried_only_once_and_the_answer_is_flagged(client, fake_llm):
    fake_llm.results = [SOLUTION_A]  # every call answers the failed fix
    first = diagnose(client)
    thumbs(client, first["ticket_id"], up=False)

    second = diagnose(client, SIMILAR)

    assert len(fake_llm.calls) == 3  # first request + this request + exactly one retry: bounded
    assert REPEAT_NOTE in second["note"]


# =============================================================================================================
# 7. Stats
# =============================================================================================================
def test_stats_count_verified_provisional_and_failed_fix_records(client):
    a, b, c, d = (diagnose(client)["ticket_id"] for _ in range(4))
    thumbs(client, a, up=True)  # an end user's click: provisional
    client.post(f"/api/v1/tickets/{d}/confirm")  # a technician's review: verified
    thumbs(client, b, up=False)
    thumbs(client, c, up=False)

    stats = client.get("/api/v1/stats").json()

    assert (stats["verified_fix_count"], stats["provisional_fix_count"], stats["failed_fix_count"]) == (1, 1, 2)
    assert (stats["knowledge_base_size"], stats["original_seed_count"], stats["technician_verified_count"]) == (32, 28, 1)
    kb = client.get("/api/v1/knowledge-base/stats").json()
    assert (kb["verified"], kb["provisional"], kb["failed"]) == (1, 1, 2)


def test_stats_on_a_fresh_system_have_no_feedback_records(client):
    stats = client.get("/api/v1/stats").json()

    assert (stats["verified_fix_count"], stats["failed_fix_count"]) == (0, 0)


# =============================================================================================================
# 8. Failed records are as durable as verified ones
# =============================================================================================================
def test_reseeding_never_deletes_failed_fix_records(client, seeded_collection, fake_embedder):
    failed_id = thumbs(client, diagnose(client)["ticket_id"], up=False).json()["kb_record_id"]

    report = seed_knowledge_base(seeded_collection, fake_embedder, load_records(KNOWLEDGE_BASE_PATH)[:-3])

    assert report.deleted == 3  # only seed records removed from the file
    assert seeded_collection.get(ids=[failed_id])["ids"] == [failed_id]


def test_failed_records_are_restored_if_the_vector_store_lost_them(client, seeded_collection, knowledge_base, db_session_factory):
    failed_id = thumbs(client, diagnose(client)["ticket_id"], up=False).json()["kb_record_id"]
    seeded_collection.delete(ids=[failed_id])  # the vector store loses it

    with db_session_factory() as db:
        restored = knowledge_base.restore_missing(db.query(Ticket).all())

    assert restored == 1
    assert record(seeded_collection, failed_id)["outcome"] == "failed_fix"
