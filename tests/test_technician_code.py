"""The technician access code: a small gate on exactly two actions (Verify/Confirm and Correct).

    TECHNICIAN_ACCESS_CODE unset/blank -> gate OFF, those two endpoints behave as they always did
    set                                -> header X-Technician-Code must match, else 401

Everything else (diagnosing, thumbs up/down, session answers, history, stats, health) must keep working with NO code.
"""

import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import app.main as main_module
from app.core.config import Settings
from app.core.technician import (
    MIN_RECOMMENDED_LENGTH,
    CodeCheck,
    check_technician_code,
    code_problems,
    log_technician_code_status,
)

CODE = "krt7-mw3p-xq9n-hd2f"  # a throwaway used only by these tests (never the production code)
HEADER = "X-Technician-Code"
REPORT = "pump grinding noise loud leak oil seal worn"
CORRECTION = {"root_cause": "Worn mechanical seal.", "recommended_fix": "Replace the seal and flush the housing."}
FRONTEND = "https://my-app.vercel.app"


def secret(value: str | None) -> SecretStr | None:
    return None if value is None else SecretStr(value)


@pytest.fixture
def gated_client(app, client):
    """The test app with the gate switched ON (settings are swapped on the already-built app)."""
    app.state.settings = app.state.settings.model_copy(update={"technician_access_code": SecretStr(CODE)})
    return client


def diagnose(client) -> dict:
    response = client.post("/api/v1/diagnose", json={"description": REPORT})
    assert response.status_code == 200, response.text
    return response.json()


def history_item(client, ticket_id: int) -> dict:
    return next(i for i in client.get("/api/v1/history?page_size=100").json()["items"] if i["id"] == ticket_id)


def kb(client) -> dict:
    return client.get("/api/v1/knowledge-base/stats").json()


def review(client, ticket_id: int, action: str, code: str | None = None):
    headers = {} if code is None else {HEADER: code}
    body = CORRECTION if action == "correct" else None
    return client.post(f"/api/v1/tickets/{ticket_id}/{action}", json=body, headers=headers)


# =============================================================================================================
# 1. The comparison itself
# =============================================================================================================
def test_no_configured_code_means_nothing_is_required():
    for provided in (None, "", "anything"):
        assert check_technician_code(provided, None) == CodeCheck.NOT_REQUIRED


def test_the_right_code_is_accepted_and_surrounding_spaces_are_ignored():
    assert check_technician_code(CODE, secret(CODE)) == CodeCheck.OK
    assert check_technician_code(f"  {CODE}\n", secret(CODE)) == CodeCheck.OK


@pytest.mark.parametrize("provided", [None, "", "   ", "\t\n"])
def test_a_missing_or_blank_code_is_reported_as_missing(provided):
    assert check_technician_code(provided, secret(CODE)) == CodeCheck.MISSING


@pytest.mark.parametrize("provided", ["wrong", CODE[:-1], CODE + "x", CODE.upper(), "x" + CODE, CODE.replace("-", "")])
def test_close_but_wrong_codes_are_wrong(provided):
    assert check_technician_code(provided, secret(CODE)) == CodeCheck.WRONG


def test_non_ascii_input_is_simply_wrong_not_a_crash():
    # hmac.compare_digest raises TypeError on non-ASCII *str*; the check compares bytes so that cannot happen.
    assert check_technician_code("kod-é-ünïcode", secret(CODE)) == CodeCheck.WRONG
    assert check_technician_code("kod-é-ünïcode", secret("kod-é-ünïcode")) == CodeCheck.OK


def test_weak_codes_are_flagged_and_the_code_itself_is_never_in_the_message():
    assert code_problems(None) == []
    assert code_problems(secret(CODE)) == []
    short = code_problems(secret("abc123"))
    assert len(short) == 1 and str(MIN_RECOMMENDED_LENGTH) in short[0] and "abc123" not in short[0]
    odd = code_problems(secret("kod-é-ünïcode-long"))
    assert len(odd) == 1 and "header" in odd[0] and "kod-é" not in odd[0]


def test_startup_logging_says_whether_the_gate_is_on_and_never_prints_the_code(caplog):
    with caplog.at_level(logging.INFO, logger="app.core.technician"):
        log_technician_code_status(None)
        log_technician_code_status(secret(CODE))
        log_technician_code_status(secret("abc123"))
    messages = [r.getMessage() for r in caplog.records]
    assert messages == [
        "technician_code_not_configured",
        "technician_code_configured",
        "technician_code_configured",
        "technician_code_weak",
    ]
    assert "Verify" in str(caplog.records[0].hint)  # the unprotected state is spelled out, not silent
    dump = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert CODE not in dump and "abc123" not in dump


# =============================================================================================================
# 2. Configuration
# =============================================================================================================
def test_the_gate_is_off_by_default():
    assert Settings(_env_file=None).technician_access_code is None


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_blank_variable_means_off_not_an_empty_password(monkeypatch, blank):
    monkeypatch.setenv("TECHNICIAN_ACCESS_CODE", blank)
    assert Settings(_env_file=None).technician_access_code is None


def test_the_code_is_read_from_the_environment_and_stripped(monkeypatch):
    monkeypatch.setenv("TECHNICIAN_ACCESS_CODE", f"  {CODE} ")
    code = Settings(_env_file=None).technician_access_code
    assert code is not None and code.get_secret_value() == CODE


def test_the_code_never_appears_in_reprs_or_dumps():
    settings = Settings(_env_file=None, technician_access_code=CODE)
    assert CODE not in repr(settings) and CODE not in str(settings) and CODE not in settings.model_dump_json()


# =============================================================================================================
# 3. Gate ON: Verify/Confirm and Correct
# =============================================================================================================
def test_confirm_with_the_right_code_verifies_the_ticket(gated_client):
    ticket_id = diagnose(gated_client)["ticket_id"]

    response = review(gated_client, ticket_id, "confirm", CODE)

    assert response.status_code == 200
    body = response.json()
    assert (body["ticket_id"], body["review_status"], body["added_to_knowledge_base"]) == (ticket_id, "confirmed", True)
    assert history_item(gated_client, ticket_id)["review_status"] == "confirmed"


def test_correct_with_the_right_code_stores_the_technicians_version(gated_client):
    ticket_id = diagnose(gated_client)["ticket_id"]

    response = review(gated_client, ticket_id, "correct", CODE)

    assert response.status_code == 200 and response.json()["review_status"] == "corrected"
    item = history_item(gated_client, ticket_id)
    assert (item["corrected_root_cause"], item["corrected_fix"]) == (CORRECTION["root_cause"], CORRECTION["recommended_fix"])


def test_verify_upgrades_a_users_provisional_fix_only_with_the_code(gated_client):
    """The History "Verify" button: thumbs-up (open) makes a provisional record; only the code makes it verified."""
    ticket_id = diagnose(gated_client)["ticket_id"]
    assert gated_client.post("/api/v1/feedback", json={"ticket_id": ticket_id, "was_correct": True}).status_code == 201
    assert (kb(gated_client)["provisional"], kb(gated_client)["verified"]) == (1, 0)

    refused = review(gated_client, ticket_id, "confirm")
    assert refused.status_code == 401
    assert (kb(gated_client)["provisional"], kb(gated_client)["verified"]) == (1, 0)  # nothing changed

    accepted = review(gated_client, ticket_id, "confirm", CODE)
    assert accepted.status_code == 200
    assert (kb(gated_client)["provisional"], kb(gated_client)["verified"]) == (0, 1)


@pytest.mark.parametrize("action", ["confirm", "correct"])
def test_no_code_is_a_401_that_says_what_to_do_and_changes_nothing(gated_client, action):
    ticket_id = diagnose(gated_client)["ticket_id"]
    before = kb(gated_client)

    response = review(gated_client, ticket_id, action)

    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "technician_code_required"
    assert "technician access code is required" in error["message"] and HEADER in error["message"]
    assert history_item(gated_client, ticket_id)["review_status"] == "pending"
    assert kb(gated_client) == before


@pytest.mark.parametrize("action", ["confirm", "correct"])
@pytest.mark.parametrize("blank", ["", "   "])
def test_an_empty_code_is_a_401_too(gated_client, action, blank):
    ticket_id = diagnose(gated_client)["ticket_id"]

    response = review(gated_client, ticket_id, action, blank)

    assert response.status_code == 401 and response.json()["error"]["code"] == "technician_code_required"
    assert history_item(gated_client, ticket_id)["review_status"] == "pending"


@pytest.mark.parametrize("action", ["confirm", "correct"])
@pytest.mark.parametrize("wrong", ["nope", CODE[:-1], CODE + "x", CODE.upper(), "x" * 500])
def test_a_wrong_code_is_a_401_invalid_technician_code(gated_client, action, wrong):
    ticket_id = diagnose(gated_client)["ticket_id"]
    before = kb(gated_client)

    response = review(gated_client, ticket_id, action, wrong)

    assert response.status_code == 401
    assert response.json()["error"] == {"code": "invalid_technician_code", "message": "Invalid technician code."}
    assert history_item(gated_client, ticket_id)["review_status"] == "pending"
    assert kb(gated_client) == before


def test_a_non_ascii_code_is_a_clean_401_not_a_500(gated_client):
    ticket_id = diagnose(gated_client)["ticket_id"]

    response = gated_client.post(
        f"/api/v1/tickets/{ticket_id}/confirm", headers={HEADER: "kod-é-ünï".encode("utf-8")}
    )

    assert response.status_code == 401 and response.json()["error"]["code"] == "invalid_technician_code"


def test_a_wrong_attempt_does_not_lock_the_right_code_out(gated_client):
    ticket_id = diagnose(gated_client)["ticket_id"]
    for _ in range(20):
        assert review(gated_client, ticket_id, "confirm", "guess").status_code == 401

    assert review(gated_client, ticket_id, "confirm", CODE).status_code == 200


def test_the_code_check_comes_before_everything_else(gated_client):
    """401 wins over 404 and 422, so the endpoints cannot be probed (ticket ids, body shape) without the code."""
    unknown = gated_client.post("/api/v1/tickets/9999/confirm")
    assert unknown.status_code == 401 and unknown.json()["error"]["code"] == "technician_code_required"

    ticket_id = diagnose(gated_client)["ticket_id"]
    bad_body = gated_client.post(f"/api/v1/tickets/{ticket_id}/correct", json={}, headers={HEADER: "wrong"})
    assert bad_body.status_code == 401 and bad_body.json()["error"]["code"] == "invalid_technician_code"

    # ...and once the code is right the normal errors come back exactly as before.
    assert review(gated_client, 9999, "confirm", CODE).status_code == 404
    assert gated_client.post(f"/api/v1/tickets/{ticket_id}/correct", json={}, headers={HEADER: CODE}).status_code == 422


def test_the_code_is_never_echoed_or_logged(gated_client, caplog):
    ticket_id = diagnose(gated_client)["ticket_id"]
    attempt = "attempt-9x2k-zzzz-1111"
    with caplog.at_level(logging.DEBUG):
        responses = [
            review(gated_client, ticket_id, "confirm", attempt),
            review(gated_client, ticket_id, "confirm"),
            review(gated_client, ticket_id, "confirm", CODE),
        ]
    everything = " ".join(r.text for r in responses) + " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert CODE not in everything and attempt not in everything
    rejected = [r for r in caplog.records if r.getMessage() == "technician_code_rejected"]
    assert [r.reason for r in rejected] == ["wrong", "missing"]  # the WHY is logged, never the value


# =============================================================================================================
# 4. Gate ON: everything else stays open, with no code
# =============================================================================================================
def test_diagnosing_needs_no_code(gated_client):
    assert gated_client.post("/api/v1/diagnose", json={"description": REPORT}).status_code == 200


def test_photo_diagnosis_needs_no_code(gated_client):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    response = gated_client.post("/api/v1/diagnose-image", files={"file": ("pump.png", png, "image/png")})
    assert response.status_code == 200, response.text


def test_thumbs_up_and_down_need_no_code_and_still_teach_the_knowledge_base(gated_client):
    up = diagnose(gated_client)["ticket_id"]
    down = diagnose(gated_client)["ticket_id"]

    assert gated_client.post("/api/v1/feedback", json={"ticket_id": up, "was_correct": True}).status_code == 201
    assert gated_client.post("/api/v1/feedback", json={"ticket_id": down, "was_correct": False}).status_code == 201

    stats = kb(gated_client)
    assert (stats["provisional"], stats["failed"], stats["verified"]) == (1, 1, 0)  # the internal review call is not gated


def test_answering_a_session_needs_no_code(gated_client):
    first = diagnose(gated_client)

    yes = gated_client.post(f"/api/v1/sessions/{first['session_id']}/feedback", json={"was_helpful": True})

    assert yes.status_code == 200 and yes.json()["resolved"] is True
    assert kb(gated_client)["provisional"] == 1


def test_a_session_no_needs_no_code(gated_client):
    first = diagnose(gated_client)
    assert gated_client.post(f"/api/v1/sessions/{first['session_id']}/feedback", json={"was_helpful": False}).status_code == 200


@pytest.mark.parametrize("path", ["/api/v1/history", "/api/v1/history?review_status=pending", "/api/v1/stats", "/api/v1/knowledge-base/stats", "/health", "/health/live"])
def test_reading_endpoints_need_no_code(gated_client, path):
    assert gated_client.get(path).status_code == 200


def test_exactly_the_two_technician_routes_answer_401_without_a_code(gated_client):
    """A sweep of EVERY route in the API (read from its OpenAPI schema): with the gate on and no code sent, only
    Verify/Confirm and Correct answer 401, so nobody can quietly gate (or ungate) another endpoint.

    The requests carry no body, so the open routes answer 200 or 422 and nothing is created or sent to the LLM.
    """
    ticket_id = diagnose(gated_client)["ticket_id"]
    swept, refused = [], set()
    for path, methods in gated_client.get("/openapi.json").json()["paths"].items():
        for method in methods:
            url = path.replace("{ticket_id}", str(ticket_id)).replace("{session_id}", "1")
            response = gated_client.request(method.upper(), url)
            swept.append((method.upper(), path))
            if response.status_code == 401:
                refused.add((method.upper(), path))
    assert refused == {("POST", "/api/v1/tickets/{ticket_id}/confirm"), ("POST", "/api/v1/tickets/{ticket_id}/correct")}
    assert len(swept) >= 10  # the sweep really covered the API, not an empty schema


# =============================================================================================================
# 5. Gate OFF (the default, and the kill switch): exactly the old behaviour
# =============================================================================================================
@pytest.mark.parametrize("action", ["confirm", "correct"])
def test_without_a_configured_code_review_needs_none(client, action):
    ticket_id = diagnose(client)["ticket_id"]
    assert review(client, ticket_id, action).status_code == 200


def test_without_a_configured_code_a_stray_header_is_harmless(client):
    ticket_id = diagnose(client)["ticket_id"]
    assert review(client, ticket_id, "confirm", "whatever").status_code == 200


def test_removing_the_code_switches_the_gate_off_again(app, gated_client):
    ticket_id = diagnose(gated_client)["ticket_id"]
    assert review(gated_client, ticket_id, "confirm").status_code == 401

    app.state.settings = app.state.settings.model_copy(update={"technician_access_code": None})  # the kill switch

    assert review(gated_client, ticket_id, "confirm").status_code == 200


# =============================================================================================================
# 6. /health tells the frontend whether to ask for a code (a boolean; never the code)
# =============================================================================================================
def test_health_says_the_gate_is_off_by_default(client):
    assert client.get("/health").json()["technician_code_required"] is False


def test_health_says_the_gate_is_on_without_revealing_the_code(gated_client):
    response = gated_client.get("/health")
    assert response.json()["technician_code_required"] is True
    assert CODE not in response.text


def test_health_keeps_all_its_old_fields(client):
    assert {"status", "version", "database", "vector_store", "llm", "knowledge_base_size"} <= set(client.get("/health").json())


# =============================================================================================================
# 7. CORS: the production frontend (Vercel) and API (Render) are different origins, so the browser sends a
#    preflight for the custom header and blocks the real request unless the API allows it.
# =============================================================================================================
@pytest.fixture
def prod_client():
    app = main_module.create_app(
        Settings(_env_file=None, allowed_origins=FRONTEND, technician_access_code=CODE, log_level="WARNING")
    )
    return TestClient(app)


@pytest.mark.parametrize("path", ["/api/v1/tickets/1/confirm", "/api/v1/tickets/1/correct"])
def test_the_browsers_preflight_for_the_technician_header_is_approved(prod_client, path):
    response = prod_client.options(
        path,
        headers={
            "Origin": FRONTEND,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-technician-code",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND
    assert "x-technician-code" in response.headers["access-control-allow-headers"].lower()


def test_the_preflight_still_refuses_a_header_that_is_not_allowed(prod_client):
    response = prod_client.options(
        "/api/v1/tickets/1/confirm",
        headers={
            "Origin": FRONTEND,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-something-else",
        },
    )
    assert response.status_code == 400


def test_a_401_still_carries_cors_headers_so_the_browser_can_show_the_message(prod_client):
    response = prod_client.post("/api/v1/tickets/1/confirm", headers={"Origin": FRONTEND, HEADER: "wrong"})
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == FRONTEND  # without it the UI would see a bogus network error
    assert response.json()["error"]["message"] == "Invalid technician code."


# =============================================================================================================
# 8. API docs
# =============================================================================================================
def test_openapi_documents_the_header_and_the_401_on_exactly_the_two_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    gated = {"/api/v1/tickets/{ticket_id}/confirm", "/api/v1/tickets/{ticket_id}/correct"}
    for path, methods in paths.items():
        for method, spec in methods.items():
            header_names = {p["name"].lower() for p in spec.get("parameters", []) if p["in"] == "header"}
            documented = "x-technician-code" in header_names and "401" in spec["responses"]
            assert documented == (path in gated and method == "post"), (method, path)
