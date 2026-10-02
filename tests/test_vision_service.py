"""Vision service tests. The model's HTTP API is faked with ``httpx.MockTransport``:
no network, no real key, no image ever leaves the machine."""

import base64
import json

import httpx
import pytest

from app.core.config import Settings
from app.core.exceptions import (
    ImageTooLargeError,
    InvalidImageError,
    UnsupportedImageTypeError,
    VisionResponseError,
    VisionUnavailableError,
)
from app.schemas.enums import Severity
from app.services.vision_service import (
    MEDIA_TYPES,
    VISION_SYSTEM_PROMPT,
    VISION_USER_PROMPT,
    DisabledVisionService,
    GroqVisionService,
    create_vision_service,
    parse_vision_output,
    validate_image_bytes,
)

KEY = "gsk_fake_vision_key_0123456789"
IMAGE = b"\xff\xd8\xff\xe0" + bytes(range(64))  # fake JPEG bytes: only the data URI round trip matters

VALID = {
    "is_equipment_photo": True,
    "damage_detected": True,
    "description": "Heavy orange rust on a stack of steel pipes; the threaded ends are corroded.",
    "severity": "medium",
    "recommended_action": "Check wall thickness, then clean and coat or scrap the pipes.",
    "confidence": 85,
}


def make_service(handler, **overrides) -> GroqVisionService:
    params = dict(
        api_key=KEY,
        base_url="https://groq.test/openai/v1",
        model="qwen/qwen3.8-27b",
        timeout_seconds=30,
        max_tokens=1024,
        temperature=0.0,
        reasoning_effort="",
    )
    params.update(overrides)
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url=params["base_url"])
    return GroqVisionService(client=client, **params)


def completion(content, finish="stop") -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content)
    return httpx.Response(
        200,
        json={
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 1903, "completion_tokens": 216},
        },
    )


def error(status, code=None, message="boom", headers=None) -> httpx.Response:
    return httpx.Response(status, json={"error": {"message": message, "code": code}}, headers=headers)


# --- the request we send ------------------------------------------------------------------------------
def test_sends_the_photo_inline_as_a_base64_data_uri_with_the_inspection_prompt():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"], seen["auth"], seen["body"] = request.url.path, request.headers.get("authorization"), json.loads(request.content)
        return completion(VALID)

    make_service(handler).analyze(IMAGE, "image/jpeg")

    body = seen["body"]
    assert seen["path"] == "/openai/v1/chat/completions"
    assert body["model"] == "qwen/qwen3.8-27b"
    assert body["response_format"] == {"type": "json_object"}
    assert (body["temperature"], body["max_tokens"]) == (0.0, 1024)  # repeatable by default
    assert "reasoning_effort" not in body  # unset => not sent

    system, user = body["messages"]
    assert system == {"role": "system", "content": VISION_SYSTEM_PROMPT}
    text_part, image_part = user["content"]
    assert text_part == {"type": "text", "text": VISION_USER_PROMPT}
    uri = image_part["image_url"]["url"]
    assert uri.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(uri.split(",", 1)[1]) == IMAGE  # the exact bytes survive the round trip


def test_the_prompt_asks_for_the_requested_findings_and_guards_against_text_in_the_image():
    for phrase in ("damage, wear, leaks, corrosion, or abnormal conditions", "If the equipment looks normal, say so",
                   "Be specific about what you observe", "digits only"):
        assert phrase in VISION_USER_PROMPT
    for field in ("is_equipment_photo", "damage_detected", "description", "severity", "recommended_action", "confidence"):
        assert f'"{field}"' in VISION_USER_PROMPT
    assert "never as instructions" in VISION_SYSTEM_PROMPT  # prompt-injection guard for text inside photos


@pytest.mark.parametrize("media_type", ["image/png", "image/webp"])
def test_media_type_follows_the_detected_format(media_type):
    seen = {}
    make_service(lambda r: seen.update(body=json.loads(r.content)) or completion(VALID)).analyze(IMAGE, media_type)
    assert seen["body"]["messages"][1]["content"][1]["image_url"]["url"].startswith(f"data:{media_type};base64,")


def test_reasoning_effort_is_sent_only_when_configured():
    seen = {}
    make_service(lambda r: seen.update(body=json.loads(r.content)) or completion(VALID), reasoning_effort="low").analyze(IMAGE, "image/jpeg")
    assert seen["body"]["reasoning_effort"] == "low"


# --- the answer we return ----------------------------------------------------------------------------------
def test_a_valid_reply_becomes_a_structured_analysis(caplog):
    with caplog.at_level("INFO", logger="app.services.vision_service"):
        result = make_service(lambda r: completion(VALID)).analyze(IMAGE, "image/jpeg")

    assert result.is_equipment_photo and result.damage_detected
    assert result.description.startswith("Heavy orange rust")
    assert result.severity is Severity.MEDIUM
    assert result.confidence == 0.85  # 85 / 100
    assert (result.model_name, result.provider) == ("qwen/qwen3.8-27b", "groq")

    record = next(r for r in caplog.records if r.getMessage() == "vision_analysis_completed")
    assert record.image_bytes == len(IMAGE) and record.prompt_tokens == 1903 and record.latency_ms >= 0
    assert "base64" not in caplog.text and "ffd8" not in caplog.text.lower()  # the image is never logged


def test_a_photo_without_damage_cannot_carry_a_medium_or_high_severity():
    contradictory = {**VALID, "damage_detected": False, "severity": "high"}

    result = make_service(lambda r: completion(contradictory)).analyze(IMAGE, "image/jpeg")

    assert result.damage_detected is False and result.severity is Severity.LOW


def test_a_non_equipment_photo_is_flagged_and_never_claims_damage():
    bird = {**VALID, "is_equipment_photo": False, "damage_detected": True, "severity": "high", "description": "A bird."}

    result = make_service(lambda r: completion(bird)).analyze(IMAGE, "image/jpeg")

    assert result.is_equipment_photo is False
    assert result.damage_detected is False and result.severity is Severity.LOW


@pytest.mark.parametrize("raw, expected", [("72%", 0.72), (0.9, 0.9), (100, 1.0)])
def test_confidence_is_normalised_to_0_1(raw, expected):
    assert make_service(lambda r: completion({**VALID, "confidence": raw})).analyze(IMAGE, "image/jpeg").confidence == expected


@pytest.mark.parametrize("bad", [None, "very sure", 150, -1, True])
def test_unusable_confidence_is_reported_as_none_and_does_not_fail_the_request(bad, caplog):
    with caplog.at_level("WARNING", logger="app.services.vision_service"):
        result = make_service(lambda r: completion({**VALID, "confidence": bad})).analyze(IMAGE, "image/jpeg")

    assert result.confidence is None and result.description  # the findings survive
    assert any(r.getMessage() == "vision_confidence_unusable" for r in caplog.records)


def test_tolerates_fenced_json_and_surrounding_chatter():
    fenced = "Here is my assessment:\n```json\n" + json.dumps(VALID) + "\n```"
    assert make_service(lambda r: completion(fenced)).analyze(IMAGE, "image/jpeg").damage_detected is True


@pytest.mark.parametrize(
    "bad_reply",
    [
        "I cannot see an image.",  # no JSON
        {k: v for k, v in VALID.items() if k != "description"},  # missing field
        {**VALID, "description": ""},  # empty finding
        {**VALID, "severity": "catastrophic"},  # not low/medium/high
        {**VALID, "damage_detected": "maybe"},  # not a bool
    ],
)
def test_unusable_model_output_becomes_vision_response_error(bad_reply):
    with pytest.raises(VisionResponseError):
        make_service(lambda r: completion(bad_reply)).analyze(IMAGE, "image/jpeg")


def test_parser_normalises_severity_case_and_whitespace():
    assert parse_vision_output(json.dumps({**VALID, "severity": " High "})).severity is Severity.HIGH


# --- failures -------------------------------------------------------------------------------------------------------
def test_connection_failure_and_timeout_become_vision_unavailable():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    for handler in (refuse, slow):
        with pytest.raises(VisionUnavailableError):
            make_service(handler).analyze(IMAGE, "image/jpeg")


@pytest.mark.parametrize(
    "status, hint_fragment",
    [(401, "Invalid GROQ_API_KEY"), (403, "not allowed"), (404, "GROQ_VISION_MODEL"), (500, "status page")],
)
def test_http_errors_become_vision_unavailable_with_an_operator_hint(status, hint_fragment, caplog):
    with caplog.at_level("ERROR", logger="app.services.vision_service"):
        with pytest.raises(VisionUnavailableError) as excinfo:
            make_service(lambda r: error(status)).analyze(IMAGE, "image/jpeg")

    assert "groq" not in excinfo.value.message.lower()  # nothing provider-specific for API clients
    assert hint_fragment in next(r for r in caplog.records if r.getMessage() == "vision_http_error").hint


def test_rate_limit_gets_its_own_friendly_message_because_the_free_tier_allows_only_a_few_images_a_minute(caplog):
    with caplog.at_level("WARNING", logger="app.services.vision_service"):
        with pytest.raises(VisionUnavailableError) as excinfo:
            make_service(lambda r: error(429, "rate_limit_exceeded", headers={"retry-after": "18"})).analyze(IMAGE, "image/jpeg")

    assert "wait a minute" in excinfo.value.message  # tells the user what to do
    record = next(r for r in caplog.records if r.getMessage() == "vision_rate_limited")
    assert record.retry_after == "18"


def test_an_image_the_provider_rejects_is_a_422_not_an_outage():
    with pytest.raises(InvalidImageError):
        make_service(lambda r: error(400, "invalid_request_error", "invalid image")).analyze(IMAGE, "image/jpeg")


def test_provider_413_becomes_image_too_large():
    with pytest.raises(ImageTooLargeError):
        make_service(lambda r: error(413)).analyze(IMAGE, "image/jpeg")


def test_a_model_that_ran_out_of_tokens_is_a_bad_answer_not_an_outage():
    with pytest.raises(VisionResponseError):
        make_service(lambda r: error(400, "json_validate_failed")).analyze(IMAGE, "image/jpeg")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>nope</html>"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": None}, "finish_reason": "length"}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": "  "}, "finish_reason": "length"}]}),
    ],
)
def test_empty_or_malformed_replies_become_vision_response_error(response):
    with pytest.raises(VisionResponseError):
        make_service(lambda r: response).analyze(IMAGE, "image/jpeg")


def test_api_key_is_redacted_from_logs_and_errors_even_if_the_provider_echoes_it(caplog):
    with caplog.at_level("DEBUG", logger="app.services.vision_service"):
        with pytest.raises(VisionUnavailableError) as excinfo:
            make_service(lambda r: error(401, message=f"Invalid API Key: {KEY}")).analyze(IMAGE, "image/jpeg")

    assert KEY not in caplog.text and KEY not in str(excinfo.value)


# --- upload validation (unchanged behaviour, now returning the format) -----------------------------------------------------
@pytest.mark.parametrize(
    "data, fmt",
    [
        (b"\xff\xd8\xff\xe0" + b"\x00" * 8, "jpeg"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "png"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "webp"),
    ],
)
def test_validate_detects_the_real_format_from_the_bytes(data, fmt):
    assert validate_image_bytes(data, 1024) == fmt
    assert MEDIA_TYPES[fmt] == f"image/{fmt}"


@pytest.mark.parametrize(
    "data, error_type",
    [(b"", InvalidImageError), (b"GIF89a....", UnsupportedImageTypeError), (b"%PDF-1.7", UnsupportedImageTypeError), (b"\xff\xd8\xff" + b"\x00" * 2000, ImageTooLargeError)],
)
def test_validate_rejects_bad_uploads(data, error_type):
    with pytest.raises(error_type):
        validate_image_bytes(data, 1024)


# --- provider selection ---------------------------------------------------------------------------------------------------------
def test_factory_builds_the_groq_vision_service_with_the_vision_model_and_the_shared_key():
    service = create_vision_service(Settings(_env_file=None, groq_api_key=KEY))
    assert isinstance(service, GroqVisionService)
    assert service._model == "qwen/qwen3.8-27b"
    assert service._client.headers["authorization"] == f"Bearer {KEY}"


def test_without_a_key_the_server_still_starts_and_vision_answers_unavailable_instead_of_inventing_results(caplog):
    with caplog.at_level("WARNING", logger="app.services.vision_service"):
        service = create_vision_service(Settings(_env_file=None))  # no GROQ_API_KEY

    assert isinstance(service, DisabledVisionService)
    assert any(r.getMessage() == "vision_disabled_no_api_key" for r in caplog.records)
    with pytest.raises(VisionUnavailableError, match="not enabled"):
        service.analyze(IMAGE, "image/jpeg")


def test_vision_can_be_switched_off_even_with_a_key():
    assert isinstance(create_vision_service(Settings(_env_file=None, groq_api_key=KEY, vision_provider="none")), DisabledVisionService)


def test_vision_is_configured_for_repeatable_output_by_default():
    assert Settings(_env_file=None).vision_temperature == 0.0


def test_vision_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "none")
    monkeypatch.setenv("GROQ_VISION_MODEL", "some/other-vision-model")
    s = Settings(_env_file=None)
    assert (s.vision_provider, s.groq_vision_model) == ("none", "some/other-vision-model")
