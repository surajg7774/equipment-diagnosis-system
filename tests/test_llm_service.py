"""Tests for the LLM layer: prompt building, output parsing and the Ollama adapter.

The Ollama adapter is exercised through ``httpx.MockTransport``, a fake HTTP
layer, so these tests check the exact request we send and how every kind of
response/failure is handled, without Ollama running.
"""

import json

import httpx
import pytest

from app.core.exceptions import LLMResponseError, LLMUnavailableError
from app.schemas.enums import Severity
from app.schemas.knowledge_base import SimilarCase
from app.services.llm_service import (
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    LLMDiagnosis,
    OllamaLLMService,
    build_messages,
    normalize_confidence,
    parse_llm_output,
)

VALID_OUTPUT = {
    "root_cause": "Worn bearings.",
    "recommended_fix": "Replace the bearings.",
    "severity": "high",
}


def _case(i: int) -> SimilarCase:
    return SimilarCase(
        id=f"KB-00{i}",
        equipment_type="pump",
        issue_description=f"problem text {i}",
        root_cause=f"cause text {i}",
        recommended_fix=f"fix text {i}",
        severity=Severity.HIGH,
        similarity_score=0.7,
    )


# --- prompt construction -----------------------------------------------------------
def test_prompt_with_context_contains_every_case_and_the_issue():
    messages = build_messages("pump is loud", [_case(1), _case(2), _case(3)])

    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == SYSTEM_PROMPT
    assert "equipment diagnostics assistant" in SYSTEM_PROMPT

    user = messages[1]["content"]
    for i in (1, 2, 3):
        assert f"Case {i} - pump" in user
        assert f"problem text {i}" in user and f"cause text {i}" in user and f"fix text {i}" in user
    assert user.index("Case 1") < user.index("Case 2") < user.index("Case 3")  # ranking preserved
    assert "<issue>\npump is loud\n</issue>" in user  # the technician's text, fenced off as data
    assert "NOT as the answer" in user and "do not copy" in user  # RAG instruction
    for field in ("root_cause", "recommended_fix", "severity"):
        assert field in user


def test_prompt_without_context_asks_for_general_reasoning_and_omits_cases():
    messages = build_messages("forklift mast jerks", [])

    user = messages[1]["content"]
    assert "No similar past case was found" in user
    assert "general engineering knowledge" in user
    assert "Case 1" not in user
    assert "<issue>\nforklift mast jerks\n</issue>" in user
    assert "root_cause" in user  # still asks for the same output format


# --- output parsing ---------------------------------------------------------------
def test_parse_clean_json():
    parsed = parse_llm_output(json.dumps(VALID_OUTPUT))

    assert parsed == LLMDiagnosis(
        root_cause="Worn bearings.", recommended_fix="Replace the bearings.", severity=Severity.HIGH
    )


@pytest.mark.parametrize(
    "raw",
    [
        "```json\n" + json.dumps(VALID_OUTPUT) + "\n```",  # markdown fence
        "Here is the diagnosis: " + json.dumps(VALID_OUTPUT) + " Hope that helps!",  # chatter around it
        "\n\n  " + json.dumps(VALID_OUTPUT, indent=2) + "  \n",  # pretty-printed / padded
    ],
)
def test_parse_tolerates_fences_and_surrounding_text(raw):
    assert parse_llm_output(raw).severity is Severity.HIGH


@pytest.mark.parametrize("written, expected", [("High", Severity.HIGH), (" MEDIUM ", Severity.MEDIUM), ("low", Severity.LOW)])
def test_parse_normalises_severity_case_and_whitespace(written, expected):
    assert parse_llm_output(json.dumps({**VALID_OUTPUT, "severity": written})).severity is expected


def test_parse_strips_whitespace_in_text_fields():
    parsed = parse_llm_output(json.dumps({**VALID_OUTPUT, "root_cause": "  padded  "}))
    assert parsed.root_cause == "padded"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "I'm sorry, I can't help with that.",  # no JSON at all
        "{not valid json}",
        '{"root_cause": "x", "recommended_fix": "y"}',  # severity missing
        '{"root_cause": "x", "recommended_fix": "y", "severity": "critical"}',  # not low/medium/high
        '{"root_cause": "", "recommended_fix": "y", "severity": "low"}',  # empty field
        '{"root_cause": "x", "recommended_fix": ["step 1", "step 2"], "severity": "low"}',  # wrong type
        '["not", "an", "object"]',
    ],
)
def test_parse_rejects_unusable_output(raw):
    with pytest.raises(LLMResponseError):
        parse_llm_output(raw)


def test_json_schema_sent_to_ollama_matches_the_pydantic_model():
    # Guards against adding a field to one and forgetting the other.
    assert set(RESPONSE_SCHEMA["required"]) == set(LLMDiagnosis.model_fields)
    assert set(RESPONSE_SCHEMA["properties"]) == set(LLMDiagnosis.model_fields)
    assert RESPONSE_SCHEMA["properties"]["severity"]["enum"] == [s.value for s in Severity]


# --- Ollama adapter (HTTP faked with MockTransport) -------------------------------------
def make_service(handler, **overrides) -> OllamaLLMService:
    params = dict(
        base_url="http://ollama.test",
        model="llama3.2:3b",
        timeout_seconds=30,
        temperature=0.2,
        max_tokens=512,
        keep_alive="30m",
    )
    params.update(overrides)
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url=params["base_url"])
    return OllamaLLMService(client=client, **params)


def chat_response(content: str | dict) -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content)
    return httpx.Response(
        200,
        json={"model": "llama3.2:3b", "message": {"role": "assistant", "content": text}, "done": True,
              "prompt_eval_count": 321, "eval_count": 87},
    )


def test_generate_diagnosis_sends_the_expected_request_and_parses_the_reply():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        seen["body"] = json.loads(request.content)
        return chat_response(VALID_OUTPUT)

    result = make_service(handler).generate_diagnosis("pump is loud", [_case(1), _case(2)])

    assert (seen["method"], seen["path"]) == ("POST", "/api/chat")
    body = seen["body"]
    assert body["model"] == "llama3.2:3b"
    assert body["stream"] is False
    assert body["format"] == RESPONSE_SCHEMA  # structured output requested
    assert body["keep_alive"] == "30m"
    assert body["options"] == {"temperature": 0.2, "num_predict": 512}
    assert body["messages"] == build_messages("pump is loud", [_case(1), _case(2)])
    assert result.severity is Severity.HIGH and result.root_cause == "Worn bearings."


def test_generate_diagnosis_logs_latency_and_token_counts(caplog):
    with caplog.at_level("INFO", logger="app.services.llm_service"):
        make_service(lambda r: chat_response(VALID_OUTPUT)).generate_diagnosis("pump is loud", [_case(1)])

    record = next(r for r in caplog.records if r.getMessage() == "llm_generation_completed")
    assert record.context_cases == 1
    assert record.llm_latency_ms >= 0
    assert (record.prompt_tokens, record.completion_tokens) == (321, 87)


def test_connection_failure_becomes_llm_unavailable(caplog):
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    with caplog.at_level("ERROR", logger="app.services.llm_service"):
        with pytest.raises(LLMUnavailableError) as excinfo:
            make_service(handler).generate_diagnosis("pump is loud", [])

    assert "ollama" not in excinfo.value.message.lower()  # no internals in the client-facing text
    record = next(r for r in caplog.records if r.getMessage() == "llm_unreachable")
    assert "ollama serve" in record.hint  # but the log tells the operator what to do


def test_timeout_becomes_llm_unavailable():
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(LLMUnavailableError):
        make_service(handler).generate_diagnosis("pump is loud", [])


def test_model_not_pulled_becomes_llm_unavailable_with_a_pull_hint(caplog):
    def handler(request):
        return httpx.Response(404, json={"error": "model 'llama3.2:3b' not found"})

    with caplog.at_level("ERROR", logger="app.services.llm_service"):
        with pytest.raises(LLMUnavailableError):
            make_service(handler).generate_diagnosis("pump is loud", [])

    record = next(r for r in caplog.records if r.getMessage() == "llm_model_not_found")
    assert "ollama pull llama3.2:3b" in record.hint


def test_server_error_becomes_llm_unavailable():
    with pytest.raises(LLMUnavailableError):
        make_service(lambda r: httpx.Response(500, text="out of memory")).generate_diagnosis("pump is loud", [])


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>not json</html>"),  # body is not JSON
        httpx.Response(200, json={"done": True}),  # no message
        httpx.Response(200, json={"message": {"role": "assistant"}}),  # no content
        httpx.Response(200, json={"message": {"role": "assistant", "content": "Sorry, no."}}),  # content not a diagnosis
    ],
)
def test_malformed_ollama_replies_become_llm_response_error(response):
    with pytest.raises(LLMResponseError):
        make_service(lambda r: response).generate_diagnosis("pump is loud", [])


# --- readiness / warm-up ------------------------------------------------------------------
def _tags(*names: str) -> httpx.Response:
    return httpx.Response(200, json={"models": [{"name": n} for n in names]})


def test_is_ready_true_only_when_the_configured_model_is_pulled():
    assert make_service(lambda r: _tags("llama3.2:3b", "phi3:mini")).is_ready() is True
    assert make_service(lambda r: _tags("phi3:mini")).is_ready() is False
    assert make_service(lambda r: _tags()).is_ready() is False


def test_is_ready_treats_a_bare_model_name_as_latest():
    service = make_service(lambda r: _tags("llama3.2:latest"), model="llama3.2")
    assert service.is_ready() is True


def test_is_ready_false_when_ollama_is_unreachable_or_broken():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    assert make_service(refuse).is_ready() is False
    assert make_service(lambda r: httpx.Response(500)).is_ready() is False
    assert make_service(lambda r: httpx.Response(200, text="garbage")).is_ready() is False


def test_warm_up_loads_the_model_and_never_raises(caplog):
    seen = {}

    def ok(request):
        seen["path"], seen["body"] = request.url.path, json.loads(request.content)
        return httpx.Response(200, json={"done": True, "done_reason": "load"})

    make_service(ok).warm_up()
    assert seen["path"] == "/api/generate"
    assert seen["body"] == {"model": "llama3.2:3b", "keep_alive": "30m"}  # no prompt => just load

    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    with caplog.at_level("WARNING", logger="app.services.llm_service"):
        make_service(refuse).warm_up()  # must not raise
    assert any(r.getMessage() == "llm_warm_up_failed" for r in caplog.records)


# --- is_valid_issue ------------------------------------------------------------------
def test_parse_reads_is_valid_issue_flag():
    parsed = parse_llm_output(json.dumps({**VALID_OUTPUT, "is_valid_issue": False}))
    assert parsed.is_valid_issue is False


def test_missing_is_valid_issue_defaults_to_true_so_real_reports_are_never_dropped():
    assert parse_llm_output(json.dumps(VALID_OUTPUT)).is_valid_issue is True


def test_prompts_ask_the_llm_to_judge_whether_the_input_is_an_equipment_issue():
    for context in ([_case(1)], []):
        user = build_messages("what is the capital of France", context)[1]["content"]
        assert "is_valid_issue" in user and "unrelated to equipment" in user


def test_ollama_schema_requires_is_valid_issue_as_a_boolean():
    assert RESPONSE_SCHEMA["properties"]["is_valid_issue"] == {"type": "boolean"}
    assert "is_valid_issue" in RESPONSE_SCHEMA["required"]


# --- self-reported confidence ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw, expected",
    [
        (72, 72), (72.4, 72), (72.6, 73), ("72", 72), ("72%", 72), (" 85 % ", 85),  # valid, in various spellings
        (0.85, 85), ("0.85", 85),  # a fraction is read as a percentage
        (0, 0), (1, 1), (100, 100),  # the boundaries are valid (1 is 1%, not 100%)
    ],
)
def test_normalize_confidence_accepts_usable_values(raw, expected):
    assert normalize_confidence(raw) == (expected, None)


@pytest.mark.parametrize(
    "raw, reason",
    [
        (None, "missing"),
        (150, "out of range"), (100.4, "out of range"), (-5, "out of range"), (1e9, "out of range"),
        ("high", "not a number"), ("", "not a number"), ("n/a", "not a number"),
        (True, "not a number"), ([72], "not a number"), ({"v": 1}, "not a number"),
        (float("nan"), "not a number"), (float("inf"), "not a number"),
    ],
)
def test_normalize_confidence_rejects_unusable_values_instead_of_repairing_them(raw, reason):
    value, why = normalize_confidence(raw)
    assert value is None and reason in why


def test_parse_extracts_a_valid_confidence():
    parsed = parse_llm_output(json.dumps({**VALID_OUTPUT, "confidence": 72}))
    assert parsed.confidence == 72


def test_parse_normalises_a_confidence_written_as_text():
    assert parse_llm_output(json.dumps({**VALID_OUTPUT, "confidence": "64%"})).confidence == 64


def test_parse_missing_confidence_is_none_and_warns_but_does_not_fail(caplog):
    with caplog.at_level("WARNING", logger="app.services.llm_service"):
        parsed = parse_llm_output(json.dumps(VALID_OUTPUT))  # VALID_OUTPUT has no confidence

    assert parsed.confidence is None and parsed.severity is Severity.HIGH  # the diagnosis survives
    record = next(r for r in caplog.records if r.getMessage() == "llm_confidence_unusable")
    assert record.reason == "missing" and record.levelname == "WARNING"


@pytest.mark.parametrize("bad", [150, -1, "very sure", True, None])
def test_parse_out_of_range_or_garbled_confidence_is_none_and_warns(bad, caplog):
    with caplog.at_level("WARNING", logger="app.services.llm_service"):
        parsed = parse_llm_output(json.dumps({**VALID_OUTPUT, "confidence": bad}))

    assert parsed.confidence is None
    assert any(r.getMessage() == "llm_confidence_unusable" for r in caplog.records)


def test_a_valid_confidence_does_not_warn(caplog):
    with caplog.at_level("WARNING", logger="app.services.llm_service"):
        parse_llm_output(json.dumps({**VALID_OUTPUT, "confidence": 72}))
    assert not [r for r in caplog.records if r.getMessage() == "llm_confidence_unusable"]


def test_prompts_ask_for_a_self_assessed_confidence_independent_of_retrieval():
    for context in ([_case(1)], []):
        user = build_messages("pump is loud", context)[1]["content"]
        assert '"confidence"' in user and "0 to 100" in user
        assert "Do NOT base it on whether similar past cases were provided" in user
        assert "digits only" in user  # a real model once answered "thirty"


def test_ollama_schema_requires_an_integer_confidence_between_0_and_100():
    assert RESPONSE_SCHEMA["properties"]["confidence"] == {"type": "integer", "minimum": 0, "maximum": 100}
    assert "confidence" in RESPONSE_SCHEMA["required"]


def test_confidence_survives_the_ollama_adapter_end_to_end():
    reply = chat_response({**VALID_OUTPUT, "confidence": 77})
    assert make_service(lambda r: reply).generate_diagnosis("pump is loud", []).confidence == 77
