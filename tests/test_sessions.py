"""Iterative diagnosis sessions: try a solution, give feedback, get a different one, until resolved.

Mostly through FastAPI's TestClient with the fake LLM from conftest, which records the "already tried"
list it receives on every call, so we can check the failed attempts really reach the model.
"""

import json

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from app.api.deps import get_diagnosis_service
from app.core.exceptions import LLMUnavailableError
from app.core.rate_limit import RateLimiter
from app.db.session import add_missing_columns, init_db
from app.models.ticket import DiagnosisSession, SolutionAttempt, Ticket
from app.schemas.enums import SessionStatus, Severity
from app.services.diagnosis_service import REPEAT_NOTE, DiagnosisService, cosine_similarity
from app.services.llm_service import LLMDiagnosis, PreviousAttempt, build_messages
from app.services.session_service import TRUSTED_LLM_CONFIDENCE, is_trusted_solution
from app.services.stats_service import build_stats
from tests.test_groq_service import completion, make_service

RELATED = "laptop battery drains quickly and the laptop shuts down suddenly"  # close KB match -> similar_cases
UNRELATED = "zqxv wplk jrmt"  # made-up words: no KB match -> general_reasoning

# Five clearly different solutions (different words, so even the fake bag-of-words embedder tells them apart).
SOLUTIONS = [
    ("The battery cell has degraded and cannot hold a charge.", "Replace the battery pack with a genuine part."),
    ("Corroded charger contacts and a dirty port block charging.", "Clean the port with isopropyl alcohol and try another cable."),
    ("Corrupted power management firmware misreports the level.", "Reflash the firmware, then reset the embedded controller."),
    ("A failed voltage regulator on the mainboard cuts power.", "Send the unit for board level repair."),
    ("A faulty thermal sensor triggers protective shutdowns.", "Replace the thermal sensor assembly."),
]


def solution(i: int, confidence: int = 80) -> LLMDiagnosis:
    cause, fix = SOLUTIONS[i]
    return LLMDiagnosis(root_cause=cause, recommended_fix=fix, severity=Severity.MEDIUM, confidence=confidence)


@pytest.fixture
def five_solutions(fake_llm):
    """Call 1 returns solution 0, call 2 solution 1, and so on."""
    fake_llm.results = [solution(i) for i in range(5)]
    return fake_llm


def start(client, text=RELATED, **extra):
    response = client.post("/api/v1/diagnose", json={"description": text, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def answer(client, session_id, helpful, **extra):
    return client.post(f"/api/v1/sessions/{session_id}/feedback", json={"was_helpful": helpful, **extra})


def history_item(client, ticket_id):
    return next(i for i in client.get("/api/v1/history?page_size=100").json()["items"] if i["id"] == ticket_id)


# --- 1. a diagnosis starts a session ---------------------------------------------------------------------------------
def test_diagnose_starts_a_session_with_its_first_attempt(client, five_solutions):
    body = start(client)

    assert len(body["session_id"]) == 32 and body["attempt_number"] == 1 and body["max_attempts"] == 4
    assert body["diagnosis"] == SOLUTIONS[0][0] and body["ticket_id"] is not None  # the same response as before, plus the session
    session = history_item(client, body["ticket_id"])["session"]
    assert session["session_id"] == body["session_id"]
    assert session["status"] == "in_progress" and session["attempt_count"] == 1 and session["resolved_at"] is None
    assert session["attempts"][0]["diagnosis"] == SOLUTIONS[0][0] and session["attempts"][0]["was_helpful"] is None


def test_each_diagnosis_gets_its_own_session(client):
    assert start(client)["session_id"] != start(client)["session_id"]


def test_an_input_that_is_not_an_equipment_issue_creates_no_session(client, fake_llm):
    fake_llm.result = LLMDiagnosis(root_cause="Not equipment.", recommended_fix="Describe the device.", severity=Severity.LOW, is_valid_issue=False)

    body = start(client, "what is the capital of France")

    assert body["is_valid_issue"] is False and body["session_id"] is None and body["attempt_number"] is None
    assert client.get("/api/v1/history").json()["total"] == 0


def test_equipment_that_is_not_in_the_knowledge_base_is_accepted(client):
    """Regression for "my mobile phone won't turn on" being rejected: no category gate exists in the pipeline."""
    body = start(client, "my mobile phone won't turn on even when it is plugged in to the charger")

    assert body["is_valid_issue"] is True and body["session_id"] and body["ticket_id"]


def test_the_optional_equipment_type_is_accepted_and_blank_means_none(client):
    assert client.post("/api/v1/diagnose", json={"description": RELATED, "equipment_type": "  "}).status_code == 200
    assert client.post("/api/v1/diagnose", json={"description": RELATED, "equipment_type": "x" * 65}).status_code == 422


# --- 2. "yes" resolves the session ---------------------------------------------------------------------------------------
def test_yes_resolves_the_session_and_stamps_resolved_at(client):
    first = start(client)

    response = answer(client, first["session_id"], True)

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["resolved"], body["escalate"], body["next_attempt"]) == ("resolved", True, False, None)
    assert body["attempt_number"] == 1 and "Resolved after 1 attempt" in body["message"]
    session = history_item(client, first["ticket_id"])["session"]
    assert session["status"] == "resolved" and session["resolved_at"] is not None
    assert session["attempts_to_resolve"] == 1 and session["attempts"][0]["was_helpful"] is True


def test_yes_on_a_trusted_first_solution_confirms_the_ticket_and_adds_it_to_the_knowledge_base_as_provisional(client):
    first = start(client)  # similar_cases basis = trusted
    before = client.get("/api/v1/knowledge-base/stats").json()

    body = answer(client, first["session_id"], True).json()

    assert body["added_to_knowledge_base"] is True
    assert body["knowledge_base_verification"] == "provisional"  # one end-user "yes" is not enough to verify it
    after = client.get("/api/v1/knowledge-base/stats").json()
    assert (after["provisional"], after["verified"], after["total"]) == (1, 0, before["total"] + 1)
    assert history_item(client, first["ticket_id"])["review_status"] == "confirmed"  # the existing review logic ran


def test_yes_on_an_untrusted_guess_resolves_but_does_not_teach_the_knowledge_base(client, fake_llm):
    fake_llm.result = solution(0, confidence=30)  # no similar case + the model itself is unsure
    first = start(client, UNRELATED)
    assert first["diagnosis_basis"] == "general_reasoning"

    body = answer(client, first["session_id"], True).json()

    assert body["resolved"] is True and body["added_to_knowledge_base"] is False
    assert client.get("/api/v1/knowledge-base/stats").json()["verified"] == 0
    assert history_item(client, first["ticket_id"])["review_status"] == "pending"


def test_a_confident_general_reasoning_answer_is_trusted_too(client, fake_llm):
    fake_llm.result = solution(0, confidence=80)
    first = start(client, UNRELATED)

    assert answer(client, first["session_id"], True).json()["added_to_knowledge_base"] is True


def test_a_solution_that_a_technician_already_reviewed_is_not_overwritten(client):
    first = start(client)
    client.post(f"/api/v1/tickets/{first['ticket_id']}/correct", json={"root_cause": "Technician cause.", "recommended_fix": "Technician fix."})

    body = answer(client, first["session_id"], True).json()

    assert body["resolved"] is True and body["added_to_knowledge_base"] is False
    assert history_item(client, first["ticket_id"])["corrected_root_cause"] == "Technician cause."


@pytest.mark.parametrize(
    "confidence, basis_is_similar, trusted",
    [(59, False, False), (60, False, True), (30, True, True), (None, False, False)],
)
def test_the_trust_rule(confidence, basis_is_similar, trusted):
    attempt = SolutionAttempt(
        diagnosis_basis="similar_cases" if basis_is_similar else "general_reasoning",
        llm_confidence=None if confidence is None else confidence / 100,
    )
    assert is_trusted_solution(attempt) is trusted
    assert TRUSTED_LLM_CONFIDENCE == 0.6


# --- 3. "no" produces a NEW, DIFFERENT solution ----------------------------------------------------------------------------------
def test_no_generates_a_different_numbered_solution_in_the_same_shape(client, five_solutions):
    first = start(client)

    response = answer(client, first["session_id"], False, attempt_number=1)

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["resolved"], body["escalate"], body["attempt_number"]) == ("in_progress", False, False, 1)
    nxt = body["next_attempt"]
    assert nxt["attempt_number"] == 2 and nxt["session_id"] == first["session_id"] and nxt["ticket_id"] == first["ticket_id"]
    assert nxt["diagnosis"] != first["diagnosis"] and nxt["recommended_action"] != first["recommended_action"]
    for key in ("severity", "retrieval_confidence", "llm_confidence", "diagnosis_basis", "similar_cases", "max_attempts"):
        assert key in nxt  # the same shape as the original diagnosis response


def test_a_no_is_stored_and_the_attempts_are_listed_in_order(client, five_solutions):
    first = start(client)
    answer(client, first["session_id"], False)
    answer(client, first["session_id"], False)

    session = history_item(client, first["ticket_id"])["session"]

    assert [a["attempt_number"] for a in session["attempts"]] == [1, 2, 3]
    assert [a["was_helpful"] for a in session["attempts"]] == [False, False, None]  # the open question is the last one
    assert [a["diagnosis"] for a in session["attempts"]] == [SOLUTIONS[0][0], SOLUTIONS[1][0], SOLUTIONS[2][0]]
    assert session["status"] == "in_progress" and session["attempts_to_resolve"] is None


def test_the_failed_attempts_are_really_passed_to_the_llm_on_every_new_attempt(client, five_solutions):
    first = start(client)
    answer(client, first["session_id"], False)
    answer(client, first["session_id"], False)

    tried = five_solutions.previous_attempts_per_call
    assert tried[0] == []  # the first diagnosis has nothing to avoid
    assert [(a.attempt_number, a.root_cause, a.recommended_fix) for a in tried[1]] == [(1, *SOLUTIONS[0])]
    assert [(a.attempt_number, a.root_cause) for a in tried[2]] == [(1, SOLUTIONS[0][0]), (2, SOLUTIONS[1][0])]
    assert all(user == RELATED for user, _ in five_solutions.calls)  # always the ORIGINAL description


def test_the_failed_attempts_reach_the_actual_http_request_sent_to_the_model(app, client, seeded_collection, fake_embedder):
    """Not cosmetic: a real Groq adapter on a faked network, and we read the prompt that would be sent."""
    prompts: list[str] = []
    answers = iter(json.dumps({"root_cause": c, "recommended_fix": f, "severity": "medium", "is_valid_issue": True, "confidence": 70}) for c, f in SOLUTIONS)

    def handler(request: httpx.Request) -> httpx.Response:
        prompts.append(json.loads(request.content)["messages"][1]["content"])
        return completion(next(answers))

    service = DiagnosisService(fake_embedder, seeded_collection, make_service(handler), top_k=3, low_confidence_threshold=0.2)
    app.dependency_overrides[get_diagnosis_service] = lambda: service

    first = start(client)
    answer(client, first["session_id"], False)
    answer(client, first["session_id"], False)

    assert "already tried" not in prompts[0] and "did NOT work" not in prompts[0]
    assert "did NOT work" in prompts[1] and SOLUTIONS[0][0] in prompts[1] and SOLUTIONS[0][1] in prompts[1]
    assert SOLUTIONS[1][0] not in prompts[1]  # attempt 2 does not exist yet
    assert SOLUTIONS[0][0] in prompts[2] and SOLUTIONS[1][0] in prompts[2]  # both failures are listed
    assert "DIFFERENT possible cause" in prompts[2] and f"<issue>\n{RELATED}\n</issue>" in prompts[2]


def test_build_messages_lists_what_was_tried_and_demands_something_different():
    tried = [PreviousAttempt(1, "Worn bearings.", "Replace bearings."), PreviousAttempt(2, "Clogged filter.", "Clean the filter.")]

    without = build_messages("pump is noisy", [])[1]["content"]
    with_tried = build_messages("pump is noisy", [], tried)[1]["content"]

    assert "did NOT work" not in without
    for text in ("Worn bearings.", "Replace bearings.", "Clogged filter.", "Clean the filter.", "Attempt 1", "Attempt 2"):
        assert text in with_tried
    assert "DIFFERENT possible cause and a DIFFERENT fix" in with_tried and "not a rework" in with_tried


def test_a_follow_up_is_never_rejected_as_not_an_equipment_issue(client, fake_llm):
    first = start(client)
    fake_llm.result = LLMDiagnosis(root_cause="x", recommended_fix="y", severity=Severity.LOW, is_valid_issue=False)  # a confused model

    body = answer(client, first["session_id"], False).json()

    assert body["next_attempt"]["is_valid_issue"] is True  # the report was already accepted


# --- 4. the cap ---------------------------------------------------------------------------------------------------------------------
def test_after_the_maximum_attempts_the_user_is_told_to_escalate_instead_of_looping(client, five_solutions):
    first = start(client)
    sid = first["session_id"]
    for expected_attempt in (2, 3, 4):
        assert answer(client, sid, False).json()["next_attempt"]["attempt_number"] == expected_attempt

    response = answer(client, sid, False)  # "no" to attempt 4 of 4

    assert response.status_code == 200  # an outcome, not an error
    body = response.json()
    assert (body["status"], body["escalate"], body["resolved"], body["next_attempt"]) == ("abandoned", True, False, None)
    assert body["attempt_number"] == 4 and "escalate" in body["message"].lower() and "human technician" in body["message"]
    assert len(five_solutions.calls) == 4  # no fifth LLM call
    session = history_item(client, first["ticket_id"])["session"]
    assert session["status"] == "abandoned" and session["attempt_count"] == 4
    assert [a["was_helpful"] for a in session["attempts"]] == [False] * 4


def test_the_cap_comes_from_settings(app, client, five_solutions):
    app.state.settings = app.state.settings.model_copy(update={"max_solution_attempts": 2})
    first = start(client)
    assert first["max_attempts"] == 2

    assert answer(client, first["session_id"], False).json()["next_attempt"]["attempt_number"] == 2
    assert answer(client, first["session_id"], False).json()["escalate"] is True
    assert len(five_solutions.calls) == 2


def test_a_session_that_hit_the_cap_stays_closed(client, five_solutions):
    sid = start(client)["session_id"]
    for _ in range(4):
        answer(client, sid, False)

    again = answer(client, sid, False)
    assert again.status_code == 200 and again.json()["escalate"] is True  # repeating the same answer is harmless
    assert answer(client, sid, True).status_code == 409  # but it cannot be flipped to "resolved" afterwards
    assert len(five_solutions.calls) == 4


# --- 5. resolved after several attempts ---------------------------------------------------------------------------------------
def test_yes_after_two_failures_resolves_in_three_attempts_and_teaches_the_third_solution(client, five_solutions):
    first = start(client)
    sid = first["session_id"]
    answer(client, sid, False)
    answer(client, sid, False)

    body = answer(client, sid, True).json()

    assert body["resolved"] is True and body["attempt_number"] == 3 and "Resolved after 3 attempts" in body["message"]
    assert body["added_to_knowledge_base"] is True
    item = history_item(client, first["ticket_id"])
    assert item["session"]["attempts_to_resolve"] == 3
    # The ticket's own text is attempt 1; what actually worked (attempt 3) is stored as the correction.
    assert item["diagnosis"] == SOLUTIONS[0][0]
    assert (item["review_status"], item["corrected_root_cause"], item["corrected_fix"]) == ("corrected", *SOLUTIONS[2])


def test_the_solution_that_worked_is_what_future_reports_retrieve(client, five_solutions, seeded_collection):
    sid = start(client)["session_id"]
    answer(client, sid, False)
    answer(client, sid, True)  # attempt 2 worked

    record = seeded_collection.get(where={"source": "verified"}, include=["metadatas"])["metadatas"][0]

    assert record["root_cause"] == SOLUTIONS[1][0] and record["recommended_fix"] == SOLUTIONS[1][1]
    assert record["issue_description"] == RELATED


def test_the_equipment_type_given_at_the_start_is_used_for_the_knowledge_base_record(client, seeded_collection):
    sid = start(client, equipment_type="laptop")["session_id"]

    answer(client, sid, True)

    record = seeded_collection.get(where={"source": "verified"}, include=["metadatas"])["metadatas"][0]
    assert record["equipment_type"] == "laptop"


# --- 6. conflicts and retries --------------------------------------------------------------------------------------------------------
def test_an_unknown_session_is_a_404(client):
    response = answer(client, "0" * 32, True)

    assert response.status_code == 404 and response.json()["error"]["code"] == "session_not_found"


def test_a_resolved_session_cannot_be_reopened_by_a_no(client, five_solutions):
    sid = start(client)["session_id"]
    answer(client, sid, True)

    response = answer(client, sid, False)

    assert response.status_code == 409 and response.json()["error"]["code"] == "session_conflict"
    assert len(five_solutions.calls) == 1  # and no LLM call was spent on it


def test_repeating_a_yes_is_harmless_and_adds_nothing_twice(client):
    sid = start(client)["session_id"]
    first = answer(client, sid, True).json()
    second = answer(client, sid, True)

    assert second.status_code == 200 and second.json()["resolved"] is True and second.json()["message"] == first["message"]
    stats = client.get("/api/v1/knowledge-base/stats").json()
    assert (stats["provisional"], stats["verified"]) == (1, 0)  # one record, and the repeated "yes" did not count twice


def test_an_answer_about_an_old_attempt_is_refused_instead_of_skipping_a_solution(client, five_solutions):
    sid = start(client)["session_id"]
    answer(client, sid, False, attempt_number=1)  # now on attempt 2

    stale = answer(client, sid, False, attempt_number=1)  # a double click / an old tab

    assert stale.status_code == 409 and "attempt 2" in stale.json()["error"]["message"]
    assert len(five_solutions.calls) == 2  # attempt 3 was NOT generated
    assert answer(client, sid, False, attempt_number=2).json()["next_attempt"]["attempt_number"] == 3


def test_when_the_llm_fails_a_no_saves_nothing_and_can_simply_be_repeated(client, five_solutions):
    first = start(client)
    five_solutions.error = LLMUnavailableError("down")

    failed = answer(client, first["session_id"], False)

    assert failed.status_code == 503
    session = history_item(client, first["ticket_id"])["session"]
    assert session["attempt_count"] == 1 and session["attempts"][0]["was_helpful"] is None  # exactly as before
    five_solutions.error = None
    assert answer(client, first["session_id"], False).json()["next_attempt"]["attempt_number"] == 2


def test_the_database_refuses_two_attempts_with_the_same_number(db_session_factory):
    with db_session_factory() as db:
        ticket = Ticket(source="text", description="d", severity=Severity.LOW, diagnosis="x", recommended_action="y", confidence_score=0.5)
        db.add(ticket)
        db.flush()
        session = DiagnosisSession(ticket_id=ticket.id, original_description="d")
        common = dict(diagnosis="x", recommended_action="y", severity=Severity.LOW, diagnosis_basis="similar_cases", retrieval_confidence=0.5)
        session.attempts.extend([SolutionAttempt(attempt_number=1, **common), SolutionAttempt(attempt_number=1, **common)])
        db.add(session)

        with pytest.raises(IntegrityError):  # this is what turns a racing double "No" into a clean 409
            db.commit()


# --- 7. rate limiting still applies where it costs quota --------------------------------------------------------------------------------
def test_a_no_counts_against_the_rate_limit_but_a_yes_never_does(app, client, five_solutions):
    app.state.rate_limiter = RateLimiter(2, 60, clock=lambda: 0.0)  # the diagnosis + one more LLM call
    first = start(client)  # 1 of 2
    assert answer(client, first["session_id"], False).status_code == 200  # 2 of 2: attempt 2

    limited = answer(client, first["session_id"], False)  # would be a third LLM call

    assert limited.status_code == 429 and limited.json()["error"]["code"] == "rate_limited" and "Retry-After" in limited.headers
    assert len(five_solutions.calls) == 2  # refused BEFORE spending quota
    assert answer(client, first["session_id"], True).status_code == 200  # saying "it worked" is free
    assert history_item(client, first["ticket_id"])["session"]["status"] == "resolved"


def test_the_escalation_message_is_not_rate_limited_because_it_calls_no_llm(app, client, five_solutions):
    app.state.settings = app.state.settings.model_copy(update={"max_solution_attempts": 1})
    app.state.rate_limiter = RateLimiter(1, 60, clock=lambda: 0.0)
    sid = start(client)["session_id"]  # uses the whole allowance

    assert answer(client, sid, False).json()["escalate"] is True


# --- 8. the repeat guard: a "different" answer that is really the same one -----------------------------------------------------------------
def test_a_repeated_solution_is_caught_and_the_model_is_asked_again_with_its_repeat_ruled_out(client, fake_llm):
    fake_llm.results = [solution(0), solution(0), solution(1)]  # call 2 just repeats call 1
    first = start(client)

    body = answer(client, first["session_id"], False).json()["next_attempt"]

    assert body["diagnosis"] == SOLUTIONS[1][0]  # the user never sees the repeat
    assert len(fake_llm.calls) == 3
    assert [a.attempt_number for a in fake_llm.previous_attempts_per_call[2]] == [1, 2]  # the repeat was listed as ruled out
    assert body["note"] is None or REPEAT_NOTE not in body["note"]


def test_if_the_model_keeps_repeating_we_stop_after_one_retry_and_say_so(client, fake_llm):
    fake_llm.results = [solution(0)]  # every call gives the same answer
    first = start(client)

    body = answer(client, first["session_id"], False).json()["next_attempt"]

    assert len(fake_llm.calls) == 3  # first diagnosis + the new attempt + exactly one retry: bounded
    assert REPEAT_NOTE in body["note"]


def test_cosine_similarity():
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine_similarity([0, 0], [1, 1]) == 0.0


# --- 9. history and stats ----------------------------------------------------------------------------------------------------------
def test_photo_tickets_have_no_session_and_old_tickets_still_list(client, db_session_factory):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    photo_id = client.post("/api/v1/diagnose-image", files={"file": ("p.png", png, "image/png")}).json()["ticket_id"]
    with db_session_factory() as db:  # a text ticket created before sessions existed
        db.add(Ticket(source="text", description="old report", severity=Severity.LOW, diagnosis="d", recommended_action="a", confidence_score=0.4))
        db.commit()

    items = client.get("/api/v1/history").json()["items"]

    assert len(items) == 2 and all(i["session"] is None for i in items)
    assert photo_id in {i["id"] for i in items}


def test_stats_report_how_sessions_ended(client, five_solutions):
    a = start(client)["session_id"]
    answer(client, a, True)  # resolved in 1
    b = start(client)["session_id"]
    answer(client, b, False)
    answer(client, b, False)
    answer(client, b, True)  # resolved in 3
    start(client)  # still in progress
    c = start(client)["session_id"]
    for _ in range(4):
        answer(client, c, False)  # abandoned

    sessions = client.get("/api/v1/stats").json()["sessions"]

    assert sessions == {"total": 4, "in_progress": 1, "resolved": 2, "abandoned": 1, "average_attempts_to_resolve": 2.0}


def test_stats_without_any_sessions_say_so_rather_than_inventing_numbers(client):
    assert client.get("/api/v1/stats").json()["sessions"] == {
        "total": 0, "in_progress": 0, "resolved": 0, "abandoned": 0, "average_attempts_to_resolve": None
    }


def test_build_stats_tolerates_a_summary_without_session_data():
    summary = {"total": 0, "by_source": {}, "by_basis": {}, "by_review_status": {},
               "avg_retrieval_confidence": None, "avg_llm_confidence": None, "avg_image_confidence": None}

    assert build_stats(summary, None).sessions.total == 0


# --- 10. an existing database gets the new tables -------------------------------------------------------------------------------
def test_an_older_database_gets_the_session_tables_on_startup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Ticket.__table__.create(engine)  # the schema before sessions existed: tickets only

    init_db(engine)

    from sqlalchemy import inspect

    tables = set(inspect(engine).get_table_names())
    assert {"diagnosis_sessions", "solution_attempts"} <= tables
    assert add_missing_columns(engine) == []  # and nothing else needs adding


def test_session_status_values():
    assert [s.value for s in SessionStatus] == ["in_progress", "resolved", "abandoned"]
