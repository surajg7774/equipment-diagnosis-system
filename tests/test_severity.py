"""Unit tests for the severity heuristic (pure functions, no I/O)."""

import pytest

from app.schemas.enums import Severity
from app.services.severity import (
    HIGH_THRESHOLD,
    MEDIUM_THRESHOLD,
    classify_severity,
    combine_severity,
    level_for_score,
    score_severity,
)


@pytest.mark.parametrize(
    "text, expected",
    [
        # The headline example: grinding(2) + leak(2) + noise(1) = 5
        ("pump making loud grinding noise and leaking oil", Severity.HIGH),
        # A single critical word is enough on its own.
        ("printer is smoking", Severity.HIGH),
        ("motor is overheating", Severity.HIGH),
        ("I can see sparks coming from the panel", Severity.HIGH),
        # Serious but not dangerous.
        ("generator won't start", Severity.MEDIUM),
        ("motor is squealing", Severity.MEDIUM),
        # Annoyance level.
        ("paper jam in tray 2", Severity.LOW),
        ("printer shows offline", Severity.LOW),
        # No known risk words at all.
        ("the display looks different today", Severity.LOW),
    ],
)
def test_classify_severity_levels(text, expected):
    assert classify_severity(text).level == expected


def test_score_is_sum_of_distinct_term_weights():
    score, matched = score_severity("pump making loud grinding noise and leaking oil")
    assert score == 5
    assert set(matched) == {"grinding", "leak", "noise"}


def test_repeated_word_counts_once():
    once, _ = score_severity("leak")
    many, _ = score_severity("leak leak leaking leaks")
    assert once == many == 2


@pytest.mark.parametrize(
    "text",
    ["there is no smoke", "pump is not leaking", "no sparks, no fire", "it doesn't leak"],
)
def test_negated_symptoms_are_ignored(text):
    assert classify_severity(text).level == Severity.LOW
    assert classify_severity(text).score == 0


def test_mitigating_words_lower_the_score():
    plain, _ = score_severity("pump is leaking")
    softened, _ = score_severity("pump is slightly leaking")
    assert softened == plain - 1


def test_score_never_negative():
    assert score_severity("slight minor occasional")[0] == 0


def test_matching_is_case_insensitive_and_handles_curly_apostrophe():
    assert classify_severity("MOTOR OVERHEATING").level == Severity.HIGH
    assert classify_severity("generator won’t start").level == Severity.MEDIUM


@pytest.mark.parametrize(
    "score, expected",
    [
        (0, Severity.LOW),
        (MEDIUM_THRESHOLD - 1, Severity.LOW),
        (MEDIUM_THRESHOLD, Severity.MEDIUM),
        (HIGH_THRESHOLD - 1, Severity.MEDIUM),
        (HIGH_THRESHOLD, Severity.HIGH),
        (99, Severity.HIGH),
    ],
)
def test_level_for_score_boundaries(score, expected):
    assert level_for_score(score) == expected


def test_assessment_exposes_matched_terms_for_explainability():
    assessment = classify_severity("smoke and a leak")
    assert assessment.level == Severity.HIGH
    assert "smoke" in assessment.matched_terms and "leak" in assessment.matched_terms


@pytest.mark.parametrize(
    "heuristic, llm, expected",
    [
        (Severity.LOW, Severity.LOW, Severity.LOW),
        (Severity.LOW, Severity.HIGH, Severity.HIGH),  # LLM escalates what keywords missed
        (Severity.HIGH, Severity.LOW, Severity.HIGH),  # LLM cannot downplay a safety keyword
        (Severity.MEDIUM, Severity.HIGH, Severity.HIGH),
        (Severity.MEDIUM, Severity.LOW, Severity.MEDIUM),
        (Severity.HIGH, Severity.HIGH, Severity.HIGH),
    ],
)
def test_combine_severity_takes_the_more_severe_level(heuristic, llm, expected):
    assert combine_severity(heuristic, llm) is expected
    assert combine_severity(llm, heuristic) is expected  # order does not matter
