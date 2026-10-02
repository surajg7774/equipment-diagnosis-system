"""Real photos through the REAL vision model. Opt-in:  pytest -m integration -k vision

Uses the provider configured by VISION_PROVIDER / GROQ_API_KEY (skipped if vision is not enabled).
Costs a few of your Groq requests. The free tier allows only ~3 images a minute, so calls are paced.

Assertions check what proves the model looked at the *content* of each photo (different photos give
different, specific findings; a non-equipment photo is recognised), not exact wording, because
LLM text varies from run to run.
"""

import time
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.exceptions import VisionUnavailableError
from app.schemas.enums import Severity
from app.services.vision_service import DisabledVisionService, create_vision_service

pytestmark = pytest.mark.integration

IMAGES = Path(__file__).resolve().parent / "fixtures" / "images"
MIN_SECONDS_BETWEEN_CALLS = 24  # ~2,000 input tokens per image vs a 7,000 tokens/minute limit


@pytest.fixture(scope="module")
def vision():
    service = create_vision_service(Settings())  # honours .env
    if isinstance(service, DisabledVisionService):
        pytest.skip("Image analysis is not enabled (set GROQ_API_KEY and VISION_PROVIDER=groq)")
    yield service
    service.close()


_last_call = [0.0]


def analyze(vision, name: str):
    """Analyze one fixture, pacing calls and retrying once if the rate limit is hit."""
    data = (IMAGES / name).read_bytes()
    for attempt in (1, 2):
        wait = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()
        try:
            return vision.analyze(data, "image/jpeg")
        except VisionUnavailableError:
            if attempt == 2:
                pytest.skip("Vision API unavailable or still rate limited")
            time.sleep(35)


def test_a_heavily_rusted_pipe_stack_is_reported_as_damaged(vision):
    result = analyze(vision, "rusted_pipes.jpg")

    assert result.is_equipment_photo is True
    assert result.damage_detected is True
    assert result.severity in (Severity.MEDIUM, Severity.HIGH)
    text = result.description.lower()
    assert "rust" in text or "corro" in text  # names the actual defect
    assert "pipe" in text  # names the actual subject
    assert result.recommended_action.strip()
    assert result.confidence is not None and 0.05 <= result.confidence <= 1.0
    assert (result.provider, result.model_name) == ("groq", Settings().groq_vision_model)


def test_a_new_undamaged_unit_is_not_flagged_as_damaged(vision):
    result = analyze(vision, "stop_arm_new.jpg")

    assert result.is_equipment_photo is True
    assert result.damage_detected is False
    assert result.severity is Severity.LOW  # the contradiction guard: no damage => low
    assert "stop" in result.description.lower()  # it read/recognised what is in the picture


def test_a_photo_of_a_bird_is_recognised_as_not_equipment(vision):
    result = analyze(vision, "bird.jpg")

    assert result.is_equipment_photo is False
    assert result.damage_detected is False  # even though the bird sits on a rusty pipe
    assert "bird" in result.description.lower() or "coucal" in result.description.lower()


def test_different_photos_get_different_findings_not_generic_output(vision):
    descriptions = [analyze(vision, n).description for n in ("rusted_pipes.jpg", "stop_arm_new.jpg", "bird.jpg")]

    assert len(set(descriptions)) == 3
    # and each one is about its own subject, not a copy of another's
    assert "pipe" in descriptions[0].lower() and "pipe" not in descriptions[1].lower()
    assert "stop" in descriptions[1].lower() and "stop" not in descriptions[0].lower()
