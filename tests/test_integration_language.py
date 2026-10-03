"""The REAL model answers in the language and style of the report (English, Hindi, Hinglish).

Opt-in:  pytest -m integration tests/test_integration_language.py

Uses the real embedding model and whichever LLM provider the settings/.env select (see test_integration_real_model.py);
skipped if that provider is not ready. A Groq run makes 9 short calls, spaced out and retried on a rate limit
(Groq's free tier throttles bursts), so it takes about a minute.

LLM text varies from run to run, so each query is tried three times and at least two answers must be in the right
language and style. A broken prompt scores 0-1 of 3 (before the change, only English matched); when this was
written the real model scored 30 of 30. The JSON structure must be intact every time.
"""

import re
import time
import uuid

import chromadb
import pytest

from app.core.config import Settings
from app.db.seed import load_records, seed_knowledge_base
from app.core.exceptions import LLMUnavailableError
from app.db.vector_store import get_or_create_collection
from app.schemas.enums import Severity
from app.services.diagnosis_service import DiagnosisService
from app.services.embedding_service import create_embedder
from app.services.llm_service import create_llm_service
from tests.conftest import KNOWLEDGE_BASE_PATH

pytestmark = pytest.mark.integration

settings = Settings()

ATTEMPTS = 3
REQUIRED = 2
PAUSE_SECONDS = 5  # between calls, to stay under Groq's free-tier token-per-minute limit

QUERIES = [
    ("english", "pump is leaking oil"),
    ("hindi", "पंप से तेल लीक हो रहा है"),
    ("hinglish", "pump se oil leak ho raha hai"),
]
EXPECTED = {"english": "english", "hindi": "hindi", "hinglish": "hinglish"}

# Roman-script Hindi words that are NOT English words, so English text scores about 0 on them.
HINGLISH_WORDS = set(
    """hai hain ho hota hoti hote hoga hogi raha rahi rahe kar karo karna karein karen kare kiya kiye karke nahi nahin
    aur ya mein se ka ki ke ko ne pe bhi toh jab agar phir pehle pahle baad isliye kyunki lekin magar yeh ye woh wo
    isse usse isko jaise jaisa sakta sakti sakte chahiye zaroor wala wali wale lagta lagti gaya gayi gaye hua hui hue
    chalu saaf jaanch dekhein dekho badal badlein liye andar bahar upar neeche tel pani kharab sahi galat bilkul zyada
    bahut thoda sirf kisi koi kuch pura poora aap apne apna apni""".split()
)


def language_of(text: str) -> str:
    """Roughly which language/style ``text`` is written in: english, hindi (Devanagari), hinglish (Roman) or unclear."""
    letters = [c for c in text if c.isalpha()]
    devanagari = sum(1 for c in letters if "ऀ" <= c <= "ॿ") / max(1, len(letters))
    if devanagari >= 0.5:
        return "hindi"
    words = re.findall(r"[a-z']+", text.lower())
    hits = sum(1 for w in words if w in HINGLISH_WORDS)
    if devanagari < 0.05 and hits >= 3 and hits / max(1, len(words)) >= 0.10:
        return "hinglish"
    if devanagari < 0.05 and hits == 0:
        return "english"
    return "unclear"


def diagnose_patiently(service, query):
    """One diagnosis; if the provider rate-limits us (LLMUnavailableError), wait and try again."""
    for attempt in range(3):
        try:
            return service.diagnose(query)
        except LLMUnavailableError:
            if attempt == 2:
                raise
            time.sleep(20)


@pytest.fixture(scope="module")
def service():
    llm = create_llm_service(settings)
    if not llm.is_ready():
        pytest.skip(f"LLM provider {settings.llm_provider!r} is not ready (not running / bad key / model missing)")
    embedder = create_embedder(settings.embedding_backend, settings.embedding_model_name)
    collection = get_or_create_collection(chromadb.EphemeralClient(), f"lang_{uuid.uuid4().hex}")
    seed_knowledge_base(collection, embedder, load_records(KNOWLEDGE_BASE_PATH))
    yield DiagnosisService(embedder, collection, llm, settings.top_k, settings.low_confidence_threshold)
    llm.close()


@pytest.mark.parametrize("label, query", QUERIES, ids=[label for label, _ in QUERIES])
def test_the_answer_is_written_in_the_language_and_style_of_the_report(service, label, query):
    matched = []
    for _ in range(ATTEMPTS):
        result = diagnose_patiently(service, query)
        time.sleep(PAUSE_SECONDS)

        # The structure never changes: a valid issue, an English severity, a real confidence, both texts filled in.
        assert result.is_valid_issue is True
        assert result.severity in set(Severity)
        assert 0.0 <= result.llm_confidence <= 1.0 and result.diagnosis.strip() and result.recommended_action.strip()

        matched.append(language_of(result.diagnosis) == EXPECTED[label] and language_of(result.recommended_action) == EXPECTED[label])

    assert sum(matched) >= REQUIRED, f"{label}: only {sum(matched)} of {ATTEMPTS} answers were in the right language/style"
