"""The RAG diagnosis pipeline (Retrieval-Augmented Generation).

    description
        |  1. RETRIEVE   embed -> ChromaDB top-k similar past cases
        v
    similar cases + similarity score
        |  2. DECIDE     is the best match close enough (>= threshold)?
        |                  yes -> pass the cases to the LLM as reference examples
        |                  no  -> pass nothing; the LLM uses general knowledge
        v
        |  3. GENERATE   LLM writes a NEW diagnosis + fix + severity for THIS issue
        v
    diagnosis, recommended_action  (from the LLM)
    confidence_score               (similarity of the best retrieved case)
    similar_cases                  (what retrieval found, for transparency)
    severity                       (more severe of keyword heuristic and LLM)

The retrieved cases are *context*, never the answer: the LLM is asked to tailor
its diagnosis to the technician's actual report, which is what lets the system
handle issues that match nothing in the knowledge base.
"""

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from chromadb.api.models.Collection import Collection

from app.core.exceptions import KnowledgeBaseEmptyError
from app.schemas.enums import DiagnosisBasis, Severity
from app.schemas.knowledge_base import SimilarCase
from app.services.embedding_service import Embedder
from app.services.llm_service import LLMService
from app.services.severity import classify_severity, combine_severity

logger = logging.getLogger(__name__)

# Plain ASCII on purpose (hyphen, not an em dash): the API sends UTF-8 JSON without a
# charset header, and some Windows clients (e.g. PowerShell 5.1) would show an em dash garbled.
NO_MATCH_NOTE = "No closely matching past case found - diagnosis based on general reasoning."
INVALID_INPUT_NOTE = "This does not appear to describe an equipment issue, so it was not saved to ticket history."


@dataclass(frozen=True)
class DiagnosisResult:
    """Everything the API needs to answer and to store a ticket."""

    is_valid_issue: bool  # False => not an equipment problem; the API must not store a ticket
    severity: Severity | None  # None when the input is not a valid issue
    diagnosis: str
    recommended_action: str
    confidence_score: float
    similar_cases: list[SimilarCase]
    diagnosis_basis: DiagnosisBasis
    note: str | None


# ---------------------------------------------------------------------------
# Pure helper functions (no I/O, so they are trivial to unit-test)
# ---------------------------------------------------------------------------
def distance_to_similarity(distance: float) -> float:
    """Convert a Chroma cosine *distance* into a 0-1 *similarity*.

    Cosine distance = 1 - cosine similarity, so similarity = 1 - distance.
    Clamped because floating-point noise can give e.g. -0.0001 or 1.0002.
    """
    return max(0.0, min(1.0, 1.0 - distance))


def parse_chroma_results(raw: Mapping[str, Any]) -> list[SimilarCase]:
    """Turn the raw dict returned by ``collection.query`` into ``SimilarCase`` objects.

    Chroma supports several queries per call, so every field is a list *of
    lists* (one inner list per query).  We only ever send one query, hence the
    ``[0]`` indexing.  Results arrive ordered nearest-first.
    """
    ids = (raw.get("ids") or [[]])[0]
    metadatas = (raw.get("metadatas") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]

    cases: list[SimilarCase] = []
    for case_id, metadata, distance in zip(ids, metadatas, distances):
        cases.append(
            SimilarCase(
                **{**metadata, "id": case_id},
                similarity_score=round(distance_to_similarity(distance), 4),
            )
        )
    return cases


def has_close_match(cases: list[SimilarCase], threshold: float) -> bool:
    """True if the best (first) case is at least ``threshold`` similar to the query."""
    return bool(cases) and cases[0].similarity_score >= threshold


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class DiagnosisService:
    """Orchestrates retrieval, the LLM call and severity scoring."""

    def __init__(
        self,
        embedder: Embedder,
        collection: Collection,
        llm: LLMService,
        top_k: int,
        low_confidence_threshold: float,
    ) -> None:
        # Dependencies are injected (not created here) so tests can pass fakes.
        self._embedder = embedder
        self._collection = collection
        self._llm = llm
        self._top_k = top_k
        self._low_confidence_threshold = low_confidence_threshold

    def knowledge_base_size(self) -> int:
        """Number of records in the vector store (used by /health)."""
        return self._collection.count()

    def llm_is_ready(self) -> bool:
        """Whether the LLM backend is reachable with its model available (used by /health)."""
        return self._llm.is_ready()

    def find_similar_cases(self, description: str) -> list[SimilarCase]:
        """Return the ``top_k`` most similar past cases, best first."""
        query_vector = self._embedder.embed([description])[0]
        raw = self._collection.query(
            query_embeddings=[query_vector],
            n_results=self._top_k,
            include=["metadatas", "distances"],
        )
        return parse_chroma_results(raw)

    def diagnose(self, description: str) -> DiagnosisResult:
        started = time.perf_counter()

        # 1. RETRIEVE
        cases = self.find_similar_cases(description)
        if not cases:
            raise KnowledgeBaseEmptyError(
                "The knowledge base is empty. Run `python -m app.db.seed` to load it."
            )
        retrieval_done = time.perf_counter()
        confidence = cases[0].similarity_score

        # 2. DECIDE: only hand the cases to the LLM if they are actually close.
        grounded = has_close_match(cases, self._low_confidence_threshold)
        basis = DiagnosisBasis.SIMILAR_CASES if grounded else DiagnosisBasis.GENERAL_REASONING

        # 3. GENERATE. Errors (LLMUnavailableError / LLMResponseError) propagate
        # on purpose: we never fall back to presenting a raw lookup as a diagnosis.
        llm_result = self._llm.generate_diagnosis(description, cases if grounded else [])
        llm_done = time.perf_counter()

        heuristic = classify_severity(description)
        # Trust the LLM's "not an equipment issue" verdict only if the keyword heuristic
        # also saw no trouble words. A small model wrongly discarding a real report
        # ("caught fire") is far worse than keeping a junk one, so the heuristic is a floor.
        is_valid = llm_result.is_valid_issue or heuristic.score > 0
        severity = combine_severity(heuristic.level, llm_result.severity) if is_valid else None

        # One structured log line per diagnosis. We log the description's
        # length, not its text, to avoid writing user content into logs.
        logger.info(
            "diagnosis_completed",
            extra={
                "description_chars": len(description),
                "is_valid_issue": is_valid,
                "llm_is_valid_issue": llm_result.is_valid_issue,
                "severity": severity.value if severity else None,
                "heuristic_severity": heuristic.level.value,
                "llm_severity": llm_result.severity.value,
                "severity_terms": list(heuristic.matched_terms),
                "confidence": confidence,
                "top_match_id": cases[0].id,
                "diagnosis_basis": basis.value,
                "retrieval_ms": round((retrieval_done - started) * 1000, 1),
                "llm_ms": round((llm_done - retrieval_done) * 1000, 1),
                "latency_ms": round((llm_done - started) * 1000, 1),
            },
        )

        note = None if grounded else NO_MATCH_NOTE
        if not is_valid:
            note = INVALID_INPUT_NOTE

        return DiagnosisResult(
            is_valid_issue=is_valid,
            severity=severity,
            diagnosis=llm_result.root_cause,
            recommended_action=llm_result.recommended_fix,
            confidence_score=confidence,  # retrieval similarity, NOT the LLM's certainty
            similar_cases=cases if is_valid else [],  # irrelevant noise for a non-issue
            diagnosis_basis=basis,
            note=note,
        )
