"""Text the English-trained embedding model cannot judge (Hindi in Devanagari, Tamil, ...) is never matched by similarity.

The model separates Latin-script text (English, and Hinglish = Hindi in Roman letters) well but not other scripts.
Measured with the real all-MiniLM-L6-v2: unrelated English problems score 0.17 on average (none above the 0.50
close-match bar), unrelated Hindi ones 0.83 (all of them above it), and two clearly different Hindi solutions 0.90.
Without the guard a learned Hindi fix would be "a close match" for EVERY other Hindi report (a pump fix matched a
printer problem at 0.85 on the real stack), and two different Hindi solutions would be called a repeat.

The embedder below mimics that behaviour in the worst case (all Devanagari texts identical), so these tests fail
if the guard is removed. Latin-script behaviour must stay exactly as it was.
"""

import pytest

from app.schemas.enums import Severity
from app.services.diagnosis_service import (
    MIN_LATIN_SHARE,
    REPEAT_NOTE,
    SEED_ONLY,
    WORKING_FIXES,
    embedder_can_judge,
    latin_script_share,
)
from app.services.llm_service import LLMDiagnosis
from tests.conftest import FakeEmbedder

ENGLISH = "pump is leaking oil"
HINDI = "पंप से तेल लीक हो रहा है"
HINGLISH = "pump se oil leak ho raha hai"
HINDI_PRINTER = "प्रिंटर खाली पन्ने छाप रहा है"


class ClumpingEmbedder(FakeEmbedder):
    """Behaves like the real English-trained model does on Devanagari: every such text looks like every other.

    Here unrelated Hindi texts score exactly 1.0 (the real model: 0.83 on average). Latin-script text embeds as usual.
    The test double decides on the script by itself, so it does not depend on the code it is meant to check.
    """

    def embed(self, texts):
        return [self._embed_one("script clump") if any("ऀ" <= ch <= "ॿ" for ch in t) else self._embed_one(t) for t in texts]


@pytest.fixture
def fake_embedder() -> ClumpingEmbedder:  # overrides the conftest fixture for every test in this module
    return ClumpingEmbedder()


def llm_result(severity=Severity.MEDIUM, root_cause="Worn mechanical seal.", fix="Replace the seal.") -> LLMDiagnosis:
    return LLMDiagnosis(root_cause=root_cause, recommended_fix=fix, severity=severity, confidence=70)


def diagnose(client, text) -> dict:
    response = client.post("/api/v1/diagnose", json={"description": text})
    assert response.status_code == 200, response.text
    return response.json()


def thumbs(client, ticket_id, up):
    return client.post("/api/v1/feedback", json={"ticket_id": ticket_id, "was_correct": up})


def kb(client) -> dict:
    return client.get("/api/v1/knowledge-base/stats").json()


# =============================================================================================================
# Which text the embedder can judge, and what the guard does with the rest
# =============================================================================================================
@pytest.mark.parametrize(
    "text, judged",
    [
        (ENGLISH, True),
        (HINGLISH, True),
        ("la bomba pierde aceite, ¿qué hago?", True),  # accented Latin letters
        ("pump 12345 ??", True),
        ("12345 !!!", True),  # no letters at all: treated as before
        ("", True),
        ("pump से तेल leak हो रहा है", False),  # mostly Devanagari: five Hindi words, two English
        (HINDI, False),
        ("பம்ப் எண்ணெய் கசிகிறது", False),  # Tamil
        ("পাম্প থেকে তেল লিক হচ্ছে", False),  # Bengali
        ("पंप seal से तेल रिस रहा है", False),
        ("pump se oil leak ho raha hai, पंप", True),  # one stray Devanagari word does not matter
        ("café pump leak", True),  # an accent written as a combining mark is still Latin
    ],
)
def test_which_text_the_embedder_can_judge(text, judged):
    assert embedder_can_judge(text) is judged
    assert (latin_script_share(text) >= MIN_LATIN_SHARE) is judged


def test_a_learned_hindi_fix_is_not_matched_to_an_unrelated_hindi_report(client, fake_llm):
    first = diagnose(client, HINDI)
    assert thumbs(client, first["ticket_id"], up=True).status_code == 201
    assert kb(client)["provisional"] == 1  # a Hindi record really was learned

    printer = diagnose(client, HINDI_PRINTER)  # a different problem, also in Devanagari

    assert printer["diagnosis_basis"] == "general_reasoning" and printer["retrieval_confidence"] < 0.2
    assert all(case["outcome"] is None for case in printer["similar_cases"])  # seed records only, never the pump fix
    assert fake_llm.calls[-1][1] == []  # the model was not shown the unrelated pump fix as a "working" case


def test_a_hindi_thumbs_down_does_not_steer_an_unrelated_hindi_report(client, fake_llm):
    first = diagnose(client, HINDI)
    assert thumbs(client, first["ticket_id"], up=False).status_code == 201
    assert kb(client)["failed"] == 1

    printer = diagnose(client, HINDI_PRINTER)

    assert printer["similar_failed_cases"] == []
    assert fake_llm.failed_examples_per_call[-1] == []


def test_the_seed_only_filter_really_excludes_every_learned_record(client, seeded_collection):
    first = diagnose(client, HINDI)
    thumbs(client, first["ticket_id"], up=True)
    second = diagnose(client, ENGLISH)
    thumbs(client, second["ticket_id"], up=False)  # a failed_fix record too
    seeds = kb(client)["seed"]

    only_seed = seeded_collection.get(where=SEED_ONLY, include=[])["ids"]
    working = seeded_collection.get(where=WORKING_FIXES, include=[])["ids"]

    assert len(only_seed) == seeds and not any(i.startswith(("VC-", "FC-")) for i in only_seed)
    assert len(working) == seeds + 1  # seed + the provisional Hindi record, but not the failed one


def test_hinglish_and_english_still_learn_and_match_exactly_as_before(client):
    """The guard is only for other scripts: a Latin-script (Hinglish) fix is still found by a similar report."""
    first = diagnose(client, "pump se oil leak ho raha hai aur seal ghis gayi hai")
    thumbs(client, first["ticket_id"], up=True)

    similar = diagnose(client, "pump se oil leak ho raha hai seal ghis gayi")

    assert similar["similar_cases"][0]["outcome"] == "provisional_fix"
    assert similar["similar_cases"][0]["id"].startswith("VC-")

    english = diagnose(client, "my laptop battery drains quickly and shuts down suddenly")
    assert english["diagnosis_basis"] == "similar_cases" and english["similar_cases"][0]["id"].startswith("KB-")


def test_two_different_hindi_solutions_are_not_flagged_as_a_repeat_after_a_no(client, fake_llm):
    fake_llm.results = [
        llm_result(root_cause="सील घिस गई है।", fix="सील बदलें।"),
        llm_result(root_cause="डिस्चार्ज लाइन ब्लॉक है।", fix="लाइन साफ करें और रिलीफ वाल्व जाँचें।"),
    ]
    first = diagnose(client, HINDI)

    response = client.post(f"/api/v1/sessions/{first['session_id']}/feedback", json={"was_helpful": False, "attempt_number": 1})

    assert response.status_code == 200
    assert len(fake_llm.calls) == 2  # no extra "you repeated yourself" call
    next_attempt = response.json()["next_attempt"]
    assert next_attempt["diagnosis"] == "डिस्चार्ज लाइन ब्लॉक है।"
    assert REPEAT_NOTE not in (next_attempt.get("note") or "")


def test_a_hinglish_repeat_is_still_caught(client, fake_llm):
    """Latin-script solutions keep the near-verbatim-repeat backstop exactly as before."""
    same = llm_result(root_cause="Seal ghis gaya hai.", fix="Seal replace karein aur oil level check karein.")
    different = llm_result(root_cause="Discharge line block hai.", fix="Line saaf karein aur relief valve check karein.")
    fake_llm.results = [same, same, different]
    first = diagnose(client, HINGLISH)

    response = client.post(f"/api/v1/sessions/{first['session_id']}/feedback", json={"was_helpful": False, "attempt_number": 1})

    assert len(fake_llm.calls) == 3  # the repeat was detected and the model was asked again
    assert response.json()["next_attempt"]["diagnosis"] == "Discharge line block hai."
