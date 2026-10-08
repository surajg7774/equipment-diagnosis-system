"""The confirmation safeguard: one end-user click must not make the knowledge base trust a fix.

    end user's click (thumbs up, "Yes, it's fixed")  = 1 confirmation   -> provisional
    technician's review (Confirm / Correct)          = 2 confirmations  -> verified
    MIN_CONFIRMATIONS_TO_VERIFY=2 (default); 1 restores the old "anything verifies at once" behaviour.

A provisional fix is still retrieved (so the learning loop works) but is labelled, ranked below a verified
one that is nearly as similar, and counted separately. A technician can verify what a user confirmed: that
upgrades the SAME record rather than adding a duplicate.
"""

import json

import httpx
import pytest
from pydantic import ValidationError

from app.api.deps import get_diagnosis_service
from app.core.config import Settings
from app.core.confirmation import confirmation_count, effective_sources, verification_for
from app.models.ticket import Ticket
from app.schemas.enums import FixVerification, KnowledgeOutcome, Severity
from app.schemas.knowledge_base import SimilarCase
from app.services.diagnosis_service import PROVISIONAL_RANK_PENALTY, DiagnosisService, has_close_match, prefer_verified
from app.services.llm_service import LLMDiagnosis, build_messages
from tests.conftest import SEED_COUNT
from tests.test_groq_service import completion as llm_completion
from tests.test_groq_service import make_service as make_groq_llm

REPORT = "pump grinding noise loud leak oil seal worn"
VERIFIED = "verified"
PROVISIONAL = "provisional"


def diagnose(client, text=REPORT) -> dict:
    response = client.post("/api/v1/diagnose", json={"description": text})
    assert response.status_code == 200, response.text
    return response.json()


def thumbs(client, ticket_id: int, up: bool = True) -> dict:
    return client.post("/api/v1/feedback", json={"ticket_id": ticket_id, "was_correct": up}).json()


def technician_confirm(client, ticket_id: int):
    return client.post(f"/api/v1/tickets/{ticket_id}/confirm")


def record(collection, record_id: str) -> dict:
    return collection.get(ids=[record_id], include=["metadatas"])["metadatas"][0]


def kb(client) -> dict:
    return client.get("/api/v1/knowledge-base/stats").json()


def history_item(client, ticket_id: int) -> dict:
    return next(i for i in client.get("/api/v1/history?page_size=100").json()["items"] if i["id"] == ticket_id)


# =============================================================================================================
# 1. The policy itself (pure)
# =============================================================================================================
@pytest.mark.parametrize(
    "sources, minimum, count, expected",
    [
        ({"user"}, 2, 1, PROVISIONAL),  # a lone click: provisional
        ({"technician"}, 2, 2, VERIFIED),  # a technician's review is worth two: verified, as before
        ({"user", "technician"}, 2, 3, VERIFIED),
        ({"user"}, 1, 1, VERIFIED),  # the kill switch: everything verifies at once
        ({"technician"}, 3, 2, PROVISIONAL),  # a stricter setting wants BOTH a user and a technician
        ({"user", "technician"}, 3, 3, VERIFIED),
    ],
)
def test_the_weight_and_threshold_table(sources, minimum, count, expected):
    assert confirmation_count(sources) == count
    assert verification_for(count, minimum).value == expected


def test_each_source_counts_once_however_often_it_confirms():
    assert confirmation_count(["user", "user", "user"]) == 1  # no self-verifying by clicking again


def test_tickets_reviewed_before_the_safeguard_keep_their_verified_status():
    assert effective_sources(None, reviewed=True) == {"technician"}  # grandfathered, not quietly demoted
    assert effective_sources(None, reviewed=False) == set()
    assert effective_sources(["user", "robot"], reviewed=True) == {"user"}  # unknown sources are ignored


def test_the_setting_defaults_to_two_and_rejects_nonsense(monkeypatch):
    monkeypatch.delenv("MIN_CONFIRMATIONS_TO_VERIFY", raising=False)
    assert Settings(_env_file=None).min_confirmations_to_verify == 2
    for bad in (0, 4):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, min_confirmations_to_verify=bad)


# =============================================================================================================
# 2. What each way of confirming produces
# =============================================================================================================
def test_an_end_users_thumbs_up_is_provisional_not_verified(client, seeded_collection):
    t = diagnose(client)["ticket_id"]

    body = thumbs(client, t)

    assert (body["knowledge_base_outcome"], body["verification"], body["confirmation_count"]) == ("provisional_fix", PROVISIONAL, 1)
    stored = record(seeded_collection, body["kb_record_id"])
    assert (stored["outcome"], stored["verification"], stored["confirmation_count"], stored["confirmed_by"]) == (
        "provisional_fix", PROVISIONAL, 1, "user",
    )
    assert (kb(client)["provisional"], kb(client)["verified"]) == (1, 0)


def test_a_technician_confirm_alone_is_verified_exactly_as_before(client, seeded_collection):
    t = diagnose(client)["ticket_id"]

    body = technician_confirm(client, t).json()

    assert (body["verification"], body["confirmation_count"], body["added_to_knowledge_base"]) == (VERIFIED, 2, True)
    stored = record(seeded_collection, body["kb_record_id"])
    assert (stored["outcome"], stored["verification"], stored["confirmed_by"]) == ("verified_fix", VERIFIED, "technician")
    assert (kb(client)["verified"], kb(client)["provisional"]) == (1, 0)


def test_a_technician_correction_is_verified_and_carries_the_technicians_text(client, seeded_collection):
    t = diagnose(client)["ticket_id"]

    body = client.post(f"/api/v1/tickets/{t}/correct", json={"root_cause": "Cavitation at the inlet.", "recommended_fix": "Clear the strainer."}).json()

    assert body["verification"] == VERIFIED
    stored = record(seeded_collection, body["kb_record_id"])
    assert (stored["outcome"], stored["root_cause"]) == ("verified_fix", "Cavitation at the inlet.")


def test_a_session_yes_on_the_first_attempt_is_provisional(client):
    first = diagnose(client)

    body = client.post(f"/api/v1/sessions/{first['session_id']}/feedback", json={"was_helpful": True}).json()

    assert (body["added_to_knowledge_base"], body["knowledge_base_verification"]) == (True, PROVISIONAL)
    assert history_item(client, first["ticket_id"])["kb_verification"] == PROVISIONAL


def test_a_session_yes_on_a_later_attempt_is_a_provisional_correction_not_a_technicians(client, fake_llm, seeded_collection):
    fake_llm.results = [
        LLMDiagnosis(root_cause="Worn bearings.", recommended_fix="Replace the bearings.", severity=Severity.MEDIUM, confidence=80),
        LLMDiagnosis(root_cause="Cavitation from a clogged strainer.", recommended_fix="Clean the strainer.", severity=Severity.MEDIUM, confidence=80),
    ]
    first = diagnose(client)
    client.post(f"/api/v1/sessions/{first['session_id']}/feedback", json={"was_helpful": False})

    body = client.post(f"/api/v1/sessions/{first['session_id']}/feedback", json={"was_helpful": True}).json()

    assert body["knowledge_base_verification"] == PROVISIONAL  # an end user said yes: it is NOT a technician's correction
    item = history_item(client, first["ticket_id"])
    assert (item["review_status"], item["corrected_root_cause"], item["kb_verification"]) == ("corrected", "Cavitation from a clogged strainer.", PROVISIONAL)
    assert record(seeded_collection, item["kb_record_id"])["outcome"] == "provisional_fix"


# =============================================================================================================
# 3. A second, different source upgrades the SAME record
# =============================================================================================================
def test_a_technician_can_verify_what_a_user_confirmed_and_it_is_the_same_record(client, seeded_collection):
    t = diagnose(client)["ticket_id"]
    record_id = thumbs(client, t)["kb_record_id"]
    size = seeded_collection.count()

    response = technician_confirm(client, t)  # the ticket is already "confirmed": this must still be allowed

    assert response.status_code == 200
    body = response.json()
    assert (body["verification"], body["confirmation_count"], body["kb_record_id"]) == (VERIFIED, 3, record_id)
    stored = record(seeded_collection, record_id)
    assert (stored["outcome"], stored["verification"], stored["confirmed_by"]) == ("verified_fix", VERIFIED, "technician,user")
    assert seeded_collection.count() == size  # upgraded in place: no duplicate record
    assert (kb(client)["verified"], kb(client)["provisional"]) == (1, 0)


def test_a_users_thumbs_up_after_a_technician_confirm_changes_nothing_and_never_downgrades(client, seeded_collection):
    t = diagnose(client)["ticket_id"]
    record_id = technician_confirm(client, t).json()["kb_record_id"]

    body = thumbs(client, t)

    assert (body["knowledge_base_outcome"], body["knowledge_base_updated"], body["verification"]) == ("verified_fix", False, VERIFIED)
    assert record(seeded_collection, record_id)["verification"] == VERIFIED


def test_confirming_again_from_the_same_source_does_not_count_twice(client):
    t = diagnose(client)["ticket_id"]
    thumbs(client, t)

    again = thumbs(client, t)
    assert (again["verification"], again["confirmation_count"], again["knowledge_base_updated"]) == (PROVISIONAL, 1, False)

    a = technician_confirm(client, t).json()["confirmation_count"]
    b = technician_confirm(client, t).json()["confirmation_count"]
    assert a == b == 3  # the second technician click is a no-op


def test_the_same_person_cannot_self_verify_through_two_channels(client):
    first = diagnose(client)
    thumbs(client, first["ticket_id"])  # the thumbs...

    client.post(f"/api/v1/sessions/{first['session_id']}/feedback", json={"was_helpful": True})  # ...and the session "Yes"

    assert history_item(client, first["ticket_id"])["kb_verification"] == PROVISIONAL  # still one end user: not verified


def test_a_technician_correction_replaces_the_content_so_earlier_confirmations_no_longer_count(client, seeded_collection):
    t = diagnose(client)["ticket_id"]
    thumbs(client, t)  # a user confirmed the AI's ORIGINAL text...

    body = client.post(f"/api/v1/tickets/{t}/correct", json={"root_cause": "Real cause here.", "recommended_fix": "Real fix here."}).json()

    stored = record(seeded_collection, body["kb_record_id"])
    assert (stored["root_cause"], stored["confirmed_by"], stored["verification"]) == ("Real cause here.", "technician", VERIFIED)
    assert body["confirmation_count"] == 2  # only the author counts for the new text


def test_a_corrected_ticket_still_cannot_be_confirmed(client):
    t = diagnose(client)["ticket_id"]
    client.post(f"/api/v1/tickets/{t}/correct", json={"root_cause": "Real cause here.", "recommended_fix": "Real fix here."})

    assert technician_confirm(client, t).status_code == 409  # unchanged rule


# =============================================================================================================
# 4. The kill switch and the stricter setting
# =============================================================================================================
def test_setting_the_threshold_to_one_restores_the_old_behaviour_exactly(app, client, seeded_collection):
    app.state.settings = app.state.settings.model_copy(update={"min_confirmations_to_verify": 1})
    t = diagnose(client)["ticket_id"]

    body = thumbs(client, t)

    assert (body["knowledge_base_outcome"], body["verification"]) == ("verified_fix", VERIFIED)  # one click verifies at once
    assert record(seeded_collection, body["kb_record_id"])["outcome"] == "verified_fix"
    assert (kb(client)["verified"], kb(client)["provisional"]) == (1, 0)


def test_a_threshold_of_three_needs_both_a_user_and_a_technician(app, client):
    app.state.settings = app.state.settings.model_copy(update={"min_confirmations_to_verify": 3})
    a, b = diagnose(client)["ticket_id"], diagnose(client)["ticket_id"]

    assert technician_confirm(client, a).json()["verification"] == PROVISIONAL  # a technician alone is not enough now
    thumbs(client, b)
    assert technician_confirm(client, b).json()["verification"] == VERIFIED  # user + technician is


# =============================================================================================================
# 5. Records written before the safeguard keep working, and everything is restorable
# =============================================================================================================
def _make_legacy(client, db_session_factory, collection, ticket_id: int, record_id: str) -> None:
    """Make a reviewed ticket + record look the way they did BEFORE this safeguard existed."""
    with db_session_factory() as db:
        ticket = db.get(Ticket, ticket_id)
        ticket.confirmation_sources, ticket.kb_verification = None, None
        db.commit()
    stored = collection.get(ids=[record_id], include=["embeddings", "documents", "metadatas"])
    metadata = {k: v for k, v in stored["metadatas"][0].items() if k not in ("outcome", "verification", "confirmation_count", "confirmed_by")}
    collection.delete(ids=[record_id])
    collection.add(ids=[record_id], embeddings=[list(stored["embeddings"][0])], documents=stored["documents"], metadatas=[metadata])


def test_a_record_written_before_the_safeguard_stays_verified(client, db_session_factory, seeded_collection):
    t = diagnose(client)["ticket_id"]
    record_id = technician_confirm(client, t).json()["kb_record_id"]
    _make_legacy(client, db_session_factory, seeded_collection, t, record_id)
    assert "outcome" not in record(seeded_collection, record_id)  # exactly what an old record looks like

    item = history_item(client, t)
    stats = kb(client)

    assert (item["kb_verification"], item["confirmation_count"]) == (VERIFIED, 2)  # not demoted
    assert (stats["verified"], stats["provisional"], stats["seed"]) == (1, 0, SEED_COUNT)  # `$ne` keeps it: it has no outcome at all
    similar = diagnose(client)["similar_cases"]
    assert any(c["id"] == record_id and c["verification"] is None for c in similar)  # retrieved, and not tagged provisional


def test_a_legacy_record_that_is_lost_is_restored_as_verified(client, db_session_factory, seeded_collection, knowledge_base):
    t = diagnose(client)["ticket_id"]
    record_id = technician_confirm(client, t).json()["kb_record_id"]
    _make_legacy(client, db_session_factory, seeded_collection, t, record_id)
    seeded_collection.delete(ids=[record_id])

    with db_session_factory() as db:
        assert knowledge_base.restore_missing(db.query(Ticket).all()) == 1

    assert record(seeded_collection, record_id)["verification"] == VERIFIED


def test_a_provisional_record_that_is_lost_is_restored_as_provisional(client, db_session_factory, seeded_collection, knowledge_base):
    t = diagnose(client)["ticket_id"]
    record_id = thumbs(client, t)["kb_record_id"]
    seeded_collection.delete(ids=[record_id])

    with db_session_factory() as db:
        assert knowledge_base.restore_missing(db.query(Ticket).all()) == 1

    stored = record(seeded_collection, record_id)
    assert (stored["outcome"], stored["confirmation_count"]) == ("provisional_fix", 1)  # restored as what it was, not promoted


def test_a_reseed_never_deletes_provisional_records(client, seeded_collection, fake_embedder):
    from app.db.seed import load_records, seed_knowledge_base
    from tests.conftest import KNOWLEDGE_BASE_PATH

    record_id = thumbs(client, diagnose(client)["ticket_id"])["kb_record_id"]

    report = seed_knowledge_base(seeded_collection, fake_embedder, load_records(KNOWLEDGE_BASE_PATH)[:-3])

    assert report.deleted == 3
    assert seeded_collection.get(ids=[record_id])["ids"] == [record_id]


# =============================================================================================================
# 6. Retrieval: provisional fixes are still found, but verified ones come first
# =============================================================================================================
def _case(case_id, similarity, outcome=None) -> SimilarCase:
    return SimilarCase(
        id=case_id, equipment_type="pump", issue_description="pump is noisy", root_cause="cause", recommended_fix="fix",
        severity=Severity.MEDIUM, similarity_score=similarity, outcome=outcome,
    )


def test_a_verified_fix_outranks_a_provisional_one_that_is_only_slightly_closer():
    ordered = prefer_verified([_case("P", 0.83, "provisional_fix"), _case("V", 0.80, "verified_fix")])

    assert [c.id for c in ordered] == ["V", "P"]


def test_a_much_closer_provisional_fix_still_comes_first():
    ordered = prefer_verified([_case("P", 0.95, "provisional_fix"), _case("V", 0.80, "verified_fix")])

    assert [c.id for c in ordered] == ["P", "V"]  # the penalty is a tie-breaker, not a ban
    assert PROVISIONAL_RANK_PENALTY == 0.05


def test_seed_cases_rank_like_verified_ones_and_nothing_changes_without_provisional_cases():
    cases = [_case("S1", 0.9), _case("V1", 0.8, "verified_fix"), _case("S2", 0.7)]  # already in Chroma's order

    assert [c.id for c in prefer_verified(cases)] == ["S1", "V1", "S2"]
    assert prefer_verified([]) == []


def test_the_close_match_test_and_confidence_use_the_real_best_similarity_whatever_the_order():
    cases = [_case("V", 0.55, "verified_fix"), _case("P", 0.58, "provisional_fix")]  # best similarity is not first

    assert has_close_match(cases, 0.56) is True
    assert has_close_match(cases, 0.59) is False


def test_end_to_end_a_provisional_fix_is_retrieved_labelled_and_ranked_below_an_equally_close_verified_one(client):
    a = diagnose(client, REPORT)["ticket_id"]
    b = diagnose(client, REPORT)["ticket_id"]
    provisional_id = thumbs(client, a)["kb_record_id"]
    verified_id = technician_confirm(client, b).json()["kb_record_id"]

    later = diagnose(client, REPORT)

    ids = [c["id"] for c in later["similar_cases"]]
    assert provisional_id in ids and verified_id in ids  # the provisional fix is still found
    assert ids.index(verified_id) < ids.index(provisional_id)  # equally similar: the verified one is listed first
    by_id = {c["id"]: c for c in later["similar_cases"]}
    assert (by_id[provisional_id]["outcome"], by_id[provisional_id]["verification"], by_id[provisional_id]["confirmation_count"]) == (
        "provisional_fix", PROVISIONAL, 1,
    )
    assert (by_id[verified_id]["outcome"], by_id[verified_id]["verification"]) == ("verified_fix", VERIFIED)
    assert later["retrieval_confidence"] == max(c["similarity_score"] for c in later["similar_cases"])  # real, not rank-adjusted


def test_a_provisional_fix_still_grounds_a_diagnosis_so_the_learning_demo_keeps_working(client):
    first = diagnose(client, "laptop battery drains within an hour and shuts down at thirty percent")
    thumbs(client, first["ticket_id"])  # one click: provisional

    again = diagnose(client, "laptop battery drains within an hour and shuts down at thirty percent")

    assert again["diagnosis_basis"] == "similar_cases"  # the provisional fix was retrieved and counted as a close match
    assert again["similar_cases"][0]["verification"] == PROVISIONAL


# =============================================================================================================
# 7. The prompt labels provisional fixes and asks for them to be weighed less
# =============================================================================================================
def test_build_messages_tags_provisional_cases_and_only_then_adds_the_caution():
    verified = _case("V", 0.8, "verified_fix")
    provisional = _case("P", 0.7, "provisional_fix")

    user = build_messages("pump grinds", [verified, provisional, _case("S", 0.6)])[1]["content"]

    case_lines = [line for line in user.splitlines() if line.startswith("Case ")]
    assert len(case_lines) == 3
    assert "[PROVISIONAL" not in case_lines[0] and "[PROVISIONAL" in case_lines[1] and "[PROVISIONAL" not in case_lines[2]
    assert "Cases marked PROVISIONAL were confirmed only once and are not yet verified: give them less weight" in user


def test_without_provisional_cases_the_prompt_is_unchanged():
    user = build_messages("pump grinds", [_case("V", 0.8, "verified_fix"), _case("S", 0.6)])[1]["content"]

    assert "PROVISIONAL" not in user


def test_the_prompt_sent_over_http_marks_a_provisional_fix(app, client, seeded_collection, fake_embedder):
    prompts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        prompts.append(json.loads(request.content)["messages"][1]["content"])
        return llm_completion({"root_cause": "Worn bearings.", "recommended_fix": "Replace them.", "severity": "medium",
                               "is_valid_issue": True, "confidence": 70})

    service = DiagnosisService(fake_embedder, seeded_collection, make_groq_llm(handler), top_k=3, low_confidence_threshold=0.2)
    app.dependency_overrides[get_diagnosis_service] = lambda: service
    thumbs(client, diagnose(client)["ticket_id"])  # a provisional fix for REPORT

    diagnose(client)

    assert "[PROVISIONAL: confirmed only once so far, not yet verified]" in prompts[-1]
    assert "give them less weight than the unmarked cases" in prompts[-1]


# =============================================================================================================
# 8. Backward compatibility: every field the old clients read is still there
# =============================================================================================================
OLD_REVIEW_KEYS = {"ticket_id", "review_status", "review_priority", "reviewed_at", "corrected_root_cause", "corrected_fix",
                   "added_to_knowledge_base", "kb_record_id", "knowledge_base"}
OLD_KB_STATS_KEYS = {"total", "seed", "verified", "verified_confirmed", "verified_corrected", "failed"}
OLD_FEEDBACK_KEYS = {"id", "ticket_id", "was_correct", "created_at", "knowledge_base_outcome", "knowledge_base_updated", "kb_record_id"}
OLD_STATS_KEYS = {"total_diagnoses_performed", "text_diagnoses", "image_diagnoses", "resolution", "knowledge_base_size", "original_seed_count",
                  "technician_verified_count", "verified_fix_count", "failed_fix_count", "review", "average_confidence", "sessions"}
OLD_SESSION_KEYS = {"session_id", "status", "resolved", "escalate", "attempt_number", "max_attempts", "message", "added_to_knowledge_base", "next_attempt"}
OLD_HISTORY_KEYS = {"id", "created_at", "source", "description", "severity", "diagnosis", "recommended_action", "confidence_score",
                    "feedback_was_correct", "review_status", "review_priority", "corrected_root_cause", "corrected_fix", "reviewed_at",
                    "kb_record_id", "session"}


def test_every_response_still_has_all_of_its_old_fields_new_ones_are_only_added(client):
    first = diagnose(client)
    t = first["ticket_id"]

    feedback = thumbs(client, t)
    confirm = technician_confirm(client, t).json()
    session = client.post(f"/api/v1/sessions/{first['session_id']}/feedback", json={"was_helpful": True}).json()

    assert OLD_FEEDBACK_KEYS <= set(feedback)
    assert OLD_REVIEW_KEYS <= set(confirm) and OLD_KB_STATS_KEYS <= set(confirm["knowledge_base"])
    assert OLD_SESSION_KEYS <= set(session)
    assert OLD_KB_STATS_KEYS <= set(kb(client))
    assert OLD_STATS_KEYS <= set(client.get("/api/v1/stats").json())
    assert OLD_HISTORY_KEYS <= set(history_item(client, t))
    assert {"verification", "confirmation_count"} <= set(confirm) and "provisional" in confirm["knowledge_base"]


def test_old_clients_that_only_know_verified_fix_and_failed_fix_are_not_surprised_by_the_text_only_flow(client):
    """A diagnosis with no feedback at all is unchanged: no provisional or verified case appears out of nowhere."""
    body = diagnose(client)

    assert all(c["outcome"] is None and c["verification"] is None for c in body["similar_cases"])  # seed cases only
    assert body["similar_failed_cases"] == []


def test_the_history_row_says_provisional_then_verified(client):
    t = diagnose(client)["ticket_id"]
    assert history_item(client, t)["kb_verification"] is None  # nothing in the knowledge base yet

    thumbs(client, t)
    item = history_item(client, t)
    assert (item["kb_verification"], item["confirmation_count"]) == (PROVISIONAL, 1)

    technician_confirm(client, t)
    item = history_item(client, t)
    assert (item["kb_verification"], item["confirmation_count"]) == (VERIFIED, 3)


def test_the_api_docs_mention_the_new_values(client):
    spec = client.get("/openapi.json").json()["components"]["schemas"]

    assert "provisional_fix" in spec["KnowledgeOutcome"]["enum"]
    assert "provisional" in spec["KnowledgeBaseStats"]["properties"]
    assert "provisional_fix_count" in spec["StatsResponse"]["properties"]
