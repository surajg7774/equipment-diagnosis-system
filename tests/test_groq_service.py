"""Groq adapter tests. HTTP is faked with ``httpx.MockTransport``: no network, no real key."""

import json

import httpx
import pytest

from app.core.exceptions import LLMResponseError, LLMUnavailableError
from app.schemas.enums import Severity
from app.services.llm_service import GroqLLMService, build_messages
from tests.test_llm_service import VALID_OUTPUT, _case

KEY = "gsk_fake_key_for_tests_0123456789"


def make_service(handler, **overrides) -> GroqLLMService:
    params = dict(
        api_key=KEY,
        base_url="https://groq.test/openai/v1",
        model="openai/gpt-oss-120b",
        timeout_seconds=30,
        temperature=0.2,
        max_tokens=1024,
        reasoning_effort="low",
    )
    params.update(overrides)
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url=params["base_url"])
    return GroqLLMService(client=client, **params)


def completion(content, finish="stop") -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content)
    return httpx.Response(
        200,
        json={
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 508, "completion_tokens": 147},
        },
    )


def error(status, code=None, message="boom", headers=None) -> httpx.Response:
    return httpx.Response(status, json={"error": {"message": message, "code": code}}, headers=headers)


# --- request / response -------------------------------------------------------------------------------
def test_sends_an_openai_style_json_mode_request_and_parses_the_reply():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"], seen["path"], seen["body"] = request.method, request.url.path, json.loads(request.content)
        return completion(VALID_OUTPUT)

    result = make_service(handler).generate_diagnosis("pump is loud", [_case(1)])

    assert (seen["method"], seen["path"]) == ("POST", "/openai/v1/chat/completions")
    body = seen["body"]
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["messages"] == build_messages("pump is loud", [_case(1)])  # same prompt as for Ollama
    assert body["response_format"] == {"type": "json_object"}
    assert body["reasoning_effort"] == "low"
    assert (body["temperature"], body["max_tokens"]) == (0.2, 1024)
    assert result.severity is Severity.HIGH and result.root_cause == "Worn bearings."


def test_reasoning_effort_is_omitted_when_empty_for_non_reasoning_models():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return completion(VALID_OUTPUT)

    make_service(handler, reasoning_effort="").generate_diagnosis("pump is loud", [])
    assert "reasoning_effort" not in seen["body"]


def test_tolerates_fenced_json_and_logs_provider_latency_and_tokens(caplog):
    fenced = "```json\n" + json.dumps(VALID_OUTPUT) + "\n```"
    with caplog.at_level("INFO", logger="app.services.llm_service"):
        result = make_service(lambda r: completion(fenced)).generate_diagnosis("pump is loud", [])

    assert result.severity is Severity.HIGH
    record = next(r for r in caplog.records if r.getMessage() == "llm_generation_completed")
    assert record.provider == "groq" and record.llm_latency_ms >= 0
    assert (record.prompt_tokens, record.completion_tokens) == (508, 147)


# --- failures ----------------------------------------------------------------------------------------------
def test_connection_failure_and_timeout_become_llm_unavailable():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    for handler in (refuse, slow):
        with pytest.raises(LLMUnavailableError):
            make_service(handler).generate_diagnosis("pump is loud", [])


@pytest.mark.parametrize(
    "status, hint_fragment",
    [(401, "Invalid GROQ_API_KEY"), (403, "not allowed"), (404, "check GROQ_MODEL"), (429, "retry after 7"), (500, "status page")],
)
def test_http_errors_become_llm_unavailable_with_an_operator_hint(status, hint_fragment, caplog):
    handler = lambda r: error(status, headers={"retry-after": "7"})  # noqa: E731
    with caplog.at_level("ERROR", logger="app.services.llm_service"):
        with pytest.raises(LLMUnavailableError) as excinfo:
            make_service(handler).generate_diagnosis("pump is loud", [])

    assert "groq" not in excinfo.value.message.lower()  # nothing provider-specific for API clients
    record = next(r for r in caplog.records if r.getMessage() == "llm_http_error")
    assert hint_fragment in record.hint and record.status == status


def test_model_that_ran_out_of_tokens_is_a_bad_answer_not_an_outage():
    # Observed live: a reasoning model with too small a token budget -> 400 json_validate_failed.
    with pytest.raises(LLMResponseError):
        make_service(lambda r: error(400, "json_validate_failed")).generate_diagnosis("pump is loud", [])


def test_other_400s_such_as_a_retired_model_are_llm_unavailable():
    with pytest.raises(LLMUnavailableError):
        make_service(lambda r: error(400, "model_decommissioned")).generate_diagnosis("pump is loud", [])


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>nope</html>"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": None}, "finish_reason": "length"}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": "   "}, "finish_reason": "length"}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": "Sorry, no."}, "finish_reason": "stop"}]}),
    ],
)
def test_unusable_replies_become_llm_response_error(response):
    with pytest.raises(LLMResponseError):
        make_service(lambda r: response).generate_diagnosis("pump is loud", [])


def test_api_key_is_redacted_from_logs_even_if_the_provider_echoes_it(caplog):
    echo = lambda r: error(401, message=f"Invalid API Key: {KEY}")  # noqa: E731
    with caplog.at_level("DEBUG", logger="app.services.llm_service"):
        with pytest.raises(LLMUnavailableError) as excinfo:
            make_service(echo).generate_diagnosis("pump is loud", [])

    assert KEY not in caplog.text and KEY not in str(excinfo.value)


# --- readiness ---------------------------------------------------------------------------------------------------
def _models(*ids) -> httpx.Response:
    return httpx.Response(200, json={"object": "list", "data": [{"id": i} for i in ids]})


def test_is_ready_only_when_the_configured_model_is_available():
    assert make_service(lambda r: _models("openai/gpt-oss-120b", "x")).is_ready() is True
    assert make_service(lambda r: _models("openai/gpt-oss-20b")).is_ready() is False


def test_is_ready_false_for_bad_key_or_outage():
    assert make_service(lambda r: error(401)).is_ready() is False

    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    assert make_service(refuse).is_ready() is False


def test_is_ready_is_cached_so_platform_health_checks_do_not_hammer_the_api():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return _models("openai/gpt-oss-120b")

    service = make_service(handler)
    for _ in range(5):
        assert service.is_ready() is True
    assert calls == ["/openai/v1/models"]  # one upstream call for five checks

    service._READY_CACHE_SECONDS = 0  # cache expired
    service.is_ready()
    assert len(calls) == 2


def test_warm_up_is_a_harmless_no_op_for_a_hosted_api():
    called = []
    service = make_service(lambda r: called.append(r) or completion(VALID_OUTPUT))
    assert service.warm_up() is None
    assert called == []  # nothing is sent
