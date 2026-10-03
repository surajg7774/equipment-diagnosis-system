"""Answers in the user's language: English, Hindi (Devanagari), Hinglish (Hindi in Roman letters), or any other.

How it works: ONE paragraph in the LLM's system prompt (plus a reminder where the JSON is requested). There is no
translation step in our code, so these tests check two things:

  1. the prompt really carries the instruction, in every kind of call, and does not branch on the language;
  2. nothing else changes: the JSON structure, the English severity values, the heuristic+LLM severity
     combination, and the text itself (stored and returned unchanged).

Whether the real model really answers in Hindi/Hinglish is checked in test_integration_language.py (opt-in).
The guard that keeps non-Latin-script text out of similarity matching is tested in test_script_matching_guard.py.
"""

import pytest

from app.schemas.diagnosis import ImageFindings
from app.schemas.enums import Severity
from app.schemas.knowledge_base import SimilarCase
from app.services.llm_service import SYSTEM_PROMPT, LLMDiagnosis, PreviousAttempt, build_messages
from app.services.severity import classify_severity

ENGLISH = "pump is leaking oil"
HINDI = "पंप से तेल लीक हो रहा है"
HINGLISH = "pump se oil leak ho raha hai"


def llm_result(severity=Severity.MEDIUM, root_cause="Worn mechanical seal.", fix="Replace the seal.") -> LLMDiagnosis:
    return LLMDiagnosis(root_cause=root_cause, recommended_fix=fix, severity=severity, confidence=70)


def diagnose(client, text) -> dict:
    response = client.post("/api/v1/diagnose", json={"description": text})
    assert response.status_code == 200, response.text
    return response.json()


def _case() -> SimilarCase:
    return SimilarCase(
        id="KB-001", equipment_type="pump", issue_description="problem", root_cause="cause", recommended_fix="fix",
        severity=Severity.HIGH, similarity_score=0.7,
    )


FINDINGS = ImageFindings(
    description="Rust on the casing.", damage_detected=True, severity=Severity.MEDIUM, confidence=0.8,
    model_name="vision-model", provider="fake",
)


# =============================================================================================================
# 1. The prompt
# =============================================================================================================
def test_the_system_prompt_tells_the_model_to_answer_in_the_users_language_and_style():
    assert "Detect the language/style the user wrote their query in (English, Hindi, Hinglish, or any other language)" in SYSTEM_PROMPT
    assert "write your diagnosis response in that same language/style" in SYSTEM_PROMPT
    assert "Keep technical terms like part names in their common form if needed" in SYSTEM_PROMPT


def test_the_system_prompt_matches_the_script_so_hinglish_does_not_turn_into_devanagari():
    assert "Hindi written in Devanagari gets Hindi in Devanagari" in SYSTEM_PROMPT
    assert "Hindi written in Roman letters" in SYSTEM_PROMPT and "never Devanagari" in SYSTEM_PROMPT


def test_the_system_prompt_keeps_json_names_and_values_in_english_and_ignores_the_language_of_the_context():
    assert 'every JSON field name, and the values of "severity", "is_valid_issue" and "confidence", stay exactly as specified' in SYSTEM_PROMPT
    assert "never by the language of any reference cases, photo findings or earlier attempts" in SYSTEM_PROMPT


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"context_examples": [_case()]},
        {"previous_attempts": [PreviousAttempt(1, "Old cause.", "Old fix.")]},
        {"failed_examples": [_case()]},
        {"image_findings": FINDINGS},
    ],
    ids=["no cases", "with cases", "after a No", "with failed cases", "with a photo"],
)
@pytest.mark.parametrize("text", [ENGLISH, HINDI, HINGLISH])
def test_every_kind_of_diagnosis_call_carries_the_language_instruction(text, kwargs):
    kwargs = {"context_examples": [], **kwargs}
    messages = build_messages(text, **kwargs)

    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert "LANGUAGE:" in messages[0]["content"]
    # ...and the reminder sits right where the JSON is requested, next to the fenced report it refers to.
    user = messages[1]["content"]
    assert "same language and script as the report inside <issue>" in user
    assert user.index("<issue>") < user.index("same language and script")


def test_the_prompt_does_not_branch_on_the_language_so_there_is_no_separate_pipeline():
    def without_the_report(text):
        messages = build_messages(text, [])
        return messages[0]["content"], messages[1]["content"].replace(text, "<REPORT>")

    assert without_the_report(ENGLISH)[0] == without_the_report(HINDI)[0] == without_the_report(HINGLISH)[0]
    assert without_the_report(ENGLISH)[1] == without_the_report(HINDI)[1] == without_the_report(HINGLISH)[1]


def test_the_report_reaches_the_model_untranslated_and_the_json_fields_are_still_requested_exactly():
    user = build_messages(HINDI, [])[1]["content"]

    assert f"<issue>\n{HINDI}\n</issue>" in user
    for field in ('"root_cause"', '"recommended_fix"', '"severity"', '"is_valid_issue"', '"confidence"'):
        assert field in user
    assert "Respond with a JSON object with exactly these fields" in user


# =============================================================================================================
# 2. Nothing else changes
# =============================================================================================================
def test_the_response_has_the_same_json_structure_whatever_the_language(client, fake_llm):
    fake_llm.result = llm_result(root_cause="पंप की सील घिस गई है।", fix="सील बदलें और तेल का स्तर जाँचें।")
    english, hindi, hinglish = (diagnose(client, t) for t in (ENGLISH, HINDI, HINGLISH))

    assert set(hindi) == set(english) == set(hinglish)
    for body in (english, hindi, hinglish):
        assert body["severity"] in {"low", "medium", "high"}  # the value stays an English word
        assert isinstance(body["confidence_score"], float) and 0 <= body["confidence_score"] <= 1
        assert body["is_valid_issue"] is True
        assert all(set(case) == set(english["similar_cases"][0]) for case in body["similar_cases"])


def test_the_diagnosis_text_comes_back_exactly_as_the_model_wrote_it_and_is_stored_unchanged(client, fake_llm):
    fake_llm.result = llm_result(root_cause="पंप की सील घिस गई है।", fix="सील बदलें और तेल का स्तर जाँचें।")

    body = diagnose(client, HINDI)

    assert body["diagnosis"] == "पंप की सील घिस गई है।"
    assert body["recommended_action"] == "सील बदलें और तेल का स्तर जाँचें।"
    item = client.get("/api/v1/history").json()["items"][0]
    assert (item["description"], item["diagnosis"]) == (HINDI, "पंप की सील घिस गई है।")  # UTF-8 survives the database
    assert fake_llm.calls[-1][0] == HINDI  # the model was handed the original words, not a translation


@pytest.mark.parametrize(
    "query, llm_severity, expected",
    [
        (ENGLISH, Severity.LOW, Severity.MEDIUM),  # the keyword "leak" is a floor under a lazy LLM
        (HINGLISH, Severity.LOW, Severity.MEDIUM),  # ...and it still fires on the English word inside Hinglish
        (HINDI, Severity.LOW, Severity.LOW),  # Devanagari has no English keywords: the LLM's rating decides alone
        (ENGLISH, Severity.HIGH, Severity.HIGH),
        (HINGLISH, Severity.HIGH, Severity.HIGH),
        (HINDI, Severity.HIGH, Severity.HIGH),
    ],
)
def test_final_severity_is_still_the_more_severe_of_the_keyword_heuristic_and_the_llm(client, fake_llm, query, llm_severity, expected):
    fake_llm.result = llm_result(severity=llm_severity)

    assert diagnose(client, query)["severity"] == expected.value


def test_the_english_keyword_heuristic_is_untouched():
    assert classify_severity(ENGLISH).level == Severity.MEDIUM
    assert classify_severity(HINGLISH).matched_terms == ("leak",)
    assert classify_severity(HINDI).score == 0  # known limitation, documented in severity.py: English keywords only
    assert classify_severity("pump is smoking and sparking").level == Severity.HIGH
