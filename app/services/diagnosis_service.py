"""The RAG diagnosis pipeline (Retrieval-Augmented Generation).

    description
        |  1. RETRIEVE   embed -> ChromaDB top-k similar past cases with WORKING fixes
        |                (seed + verified), and separately the close cases whose fix a user
        |                reported did NOT work (failed_fix)
        v
    similar cases + similarity score
        |  2. DECIDE     is the best match close enough (>= threshold)?
        |                  yes -> pass the cases to the LLM as reference examples
        |                  no  -> pass nothing; the LLM uses general knowledge
        |                close failed fixes are always passed, labelled "did NOT work"
        v
        |  3. GENERATE   LLM writes a NEW diagnosis + fix + severity for THIS issue
        v
    diagnosis, recommended_action  (from the LLM)
    retrieval_confidence           (similarity of the best retrieved case: how well the
                                    knowledge base covers this issue)
    llm_confidence                 (the LLM's own certainty in its diagnosis: independent of
                                    whether a past case matched)
    similar_cases                  (what retrieval found, for transparency)
    severity                       (more severe of keyword heuristic and LLM)

The retrieved cases are *context*, never the answer: the LLM is asked to tailor
its diagnosis to the technician's actual report, which is what lets the system
handle issues that match nothing in the knowledge base.
"""

import logging
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from chromadb.api.models.Collection import Collection

from app.core.exceptions import KnowledgeBaseEmptyError
from app.schemas.diagnosis import ImageFindings
from app.schemas.enums import DiagnosisBasis, KnowledgeOutcome, Severity
from app.schemas.knowledge_base import SimilarCase
from app.services.embedding_service import Embedder
from app.services.llm_service import DEFAULT_LLM_CONFIDENCE, LLMDiagnosis, LLMService, PreviousAttempt
from app.services.severity import classify_severity, combine_severity

logger = logging.getLogger(__name__)

# Plain ASCII on purpose (hyphen, not an em dash): the API sends UTF-8 JSON without a
# charset header, and some Windows clients (e.g. PowerShell 5.1) would show an em dash garbled.
NO_MATCH_NOTE = "No closely matching past case found - diagnosis based on general reasoning."
INVALID_INPUT_NOTE = "This does not appear to describe an equipment issue, so it was not saved to ticket history."
REPEAT_NOTE = (
    "This suggestion is similar to one that already did not work (earlier in this session or for a similar "
    "past problem); treat it with caution."
)

# Two searches over the same collection. Seed records have no "outcome" key at all: Chroma's $ne keeps
# records that lack the key (pinned by a test against real ChromaDB), so they count as working fixes.
WORKING_FIXES = {"outcome": {"$ne": KnowledgeOutcome.FAILED_FIX.value}}
FAILED_FIXES = {"outcome": KnowledgeOutcome.FAILED_FIX.value}

# A new attempt whose embedding is at least this similar to a failed one counts as a repeat.
# This is a backstop for NEAR-VERBATIM repeats only, not a classifier: measured with the real
# all-MiniLM-L6-v2, genuinely different causes for the same equipment scored up to 0.82 (e.g. toner
# cartridge vs firmware fault on a printer) while honest rewordings of one cause scored anywhere from
# 0.74 to 0.94, so no threshold separates the two. 0.90 never fired on any different-cause pair we
# measured. Telling the model what already failed (the prompt) is what makes attempts differ.
REPEAT_SIMILARITY = 0.90


@dataclass(frozen=True)
class DiagnosisResult:
    """Everything the API needs to answer and to store a ticket."""

    is_valid_issue: bool  # False => not an equipment problem; the API must not store a ticket
    severity: Severity | None  # None when the input is not a valid issue
    diagnosis: str
    recommended_action: str
    retrieval_confidence: float  # 0-1: similarity of the best retrieved case
    llm_confidence: float  # 0-1: the LLM's self-reported certainty (0.5 if it gave none)
    llm_confidence_defaulted: bool  # True if the LLM gave no usable number and we used the default
    similar_cases: list[SimilarCase]
    diagnosis_basis: DiagnosisBasis
    note: str | None
    # Close past cases whose fix a user reported did NOT work; shown to the LLM as "did NOT work".
    failed_cases: list[SimilarCase] = field(default_factory=list)
    # What a vision model saw in a photo attached to this request, if one was used (None = text only).
    image_findings: ImageFindings | None = None


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


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two vectors (0 if either is all zeros)."""
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def solution_text(root_cause: str, recommended_fix: str) -> str:
    return f"{root_cause} {recommended_fix}"


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

    def _search(self, query_vector: list[float], where: dict) -> list[SimilarCase]:
        raw = self._collection.query(
            query_embeddings=[query_vector],
            n_results=self._top_k,
            where=where,
            include=["metadatas", "distances"],
        )
        return parse_chroma_results(raw)

    def find_similar_cases(self, description: str) -> list[SimilarCase]:
        """Return the ``top_k`` most similar past cases with WORKING fixes (seed + verified), best first."""
        return self._search(self._embedder.embed([description])[0], WORKING_FIXES)

    def _repeats_a_ruled_out_solution(self, result: LLMDiagnosis, ruled_out: Sequence[tuple[str, str]]) -> bool:
        """True if the new solution is (nearly) the same as a (root cause, fix) known not to work."""
        texts = [solution_text(result.root_cause, result.recommended_fix)]
        texts += [solution_text(root_cause, fix) for root_cause, fix in ruled_out]
        vectors = self._embedder.embed(texts)
        return max(cosine_similarity(vectors[0], v) for v in vectors[1:]) >= REPEAT_SIMILARITY

    def diagnose(
        self,
        description: str,
        previous_attempts: Sequence[PreviousAttempt] = (),
        image_findings: ImageFindings | None = None,
    ) -> DiagnosisResult:
        """Diagnose ``description``; with ``previous_attempts`` propose something DIFFERENT from them.

        With ``image_findings`` (what a vision model saw in an attached photo) the SAME LLM call weighs the
        description and the photo together, so the answer is one diagnosis, not two. Retrieval still searches
        on the description alone: ``retrieval_confidence`` keeps meaning "how well past cases cover the
        reported symptoms".
        """
        started = time.perf_counter()

        # 1. RETRIEVE (one embedding, two searches: fixes that worked, and fixes that did not)
        query_vector = self._embedder.embed([description])[0]
        cases = self._search(query_vector, WORKING_FIXES)
        if not cases:
            raise KnowledgeBaseEmptyError(
                "The knowledge base is empty. Run `python -m app.db.seed` to load it."
            )
        # Only CLOSE failures count (the same bar as a close match): a failed fix for an unrelated
        # problem must never steer the model. They do not count as coverage either, so
        # retrieval_confidence and the basis below are about working fixes only.
        failed_cases = [
            c for c in self._search(query_vector, FAILED_FIXES) if c.similarity_score >= self._low_confidence_threshold
        ]
        retrieval_done = time.perf_counter()
        retrieval_confidence = cases[0].similarity_score

        # 2. DECIDE: only hand the cases to the LLM if they are actually close.
        grounded = has_close_match(cases, self._low_confidence_threshold)
        basis = DiagnosisBasis.SIMILAR_CASES if grounded else DiagnosisBasis.GENERAL_REASONING

        # 3. GENERATE. Errors (LLMUnavailableError / LLMResponseError) propagate
        # on purpose: we never fall back to presenting a raw lookup as a diagnosis.
        context = cases if grounded else []
        # Only passed when there IS a photo, so a text-only call is exactly what it was before photos
        # existed (and an LLMService written back then keeps working).
        photo = {} if image_findings is None else {"image_findings": image_findings}
        llm_result = self._llm.generate_diagnosis(description, context, previous_attempts, failed_cases, **photo)
        # Everything known NOT to work for this problem: earlier attempts in this session, and close
        # failed fixes from the knowledge base.
        ruled_out = [(a.root_cause, a.recommended_fix) for a in previous_attempts]
        ruled_out += [(c.root_cause, c.recommended_fix) for c in failed_cases]
        repeated = False
        if ruled_out and self._repeats_a_ruled_out_solution(llm_result, ruled_out):
            # Asking nicely was not enough: show the model its own repeat, listed as ruled out, and ask once more.
            logger.warning(
                "diagnosis_repeated_ruled_out_solution",
                extra={"attempts_so_far": len(previous_attempts), "failed_cases": len(failed_cases)},
            )
            repeat = PreviousAttempt(
                attempt_number=max((a.attempt_number for a in previous_attempts), default=0) + 1,
                root_cause=llm_result.root_cause,
                recommended_fix=llm_result.recommended_fix,
            )
            llm_result = self._llm.generate_diagnosis(
                description, context, [*previous_attempts, repeat], failed_cases, **photo
            )
            repeated = self._repeats_a_ruled_out_solution(llm_result, ruled_out)
        llm_done = time.perf_counter()

        # The LLM reports 0-100; the API uses 0-1 for both confidences. A missing/garbled value
        # (already warned about in parse_llm_output) must not fail the request: use the default.
        llm_confidence_defaulted = llm_result.confidence is None
        reported = DEFAULT_LLM_CONFIDENCE if llm_confidence_defaulted else llm_result.confidence
        llm_confidence = round(reported / 100, 2)

        heuristic = classify_severity(description)
        # Trust the LLM's "not an equipment issue" verdict only if the keyword heuristic
        # also saw no trouble words. A small model wrongly discarding a real report
        # ("caught fire") is far worse than keeping a junk one, so the heuristic is a floor.
        # (A follow-up attempt is for a report that was already accepted, so it is always valid.)
        is_valid = bool(previous_attempts) or llm_result.is_valid_issue or heuristic.score > 0
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
                "retrieval_confidence": retrieval_confidence,
                "llm_confidence": llm_confidence,
                "llm_confidence_defaulted": llm_confidence_defaulted,
                "top_match_id": cases[0].id,
                "diagnosis_basis": basis.value,
                "previous_attempts": len(previous_attempts),
                "failed_cases": len(failed_cases),
                "photo_findings": image_findings is not None,
                "repeated_ruled_out_solution": repeated,
                "retrieval_ms": round((retrieval_done - started) * 1000, 1),
                "llm_ms": round((llm_done - retrieval_done) * 1000, 1),
                "latency_ms": round((llm_done - started) * 1000, 1),
            },
        )

        note = None if grounded else NO_MATCH_NOTE
        if repeated:
            note = REPEAT_NOTE if note is None else f"{note} {REPEAT_NOTE}"
        if not is_valid:
            note = INVALID_INPUT_NOTE

        return DiagnosisResult(
            is_valid_issue=is_valid,
            severity=severity,
            diagnosis=llm_result.root_cause,
            recommended_action=llm_result.recommended_fix,
            retrieval_confidence=retrieval_confidence,
            llm_confidence=llm_confidence,
            llm_confidence_defaulted=llm_confidence_defaulted,
            similar_cases=cases if is_valid else [],  # irrelevant noise for a non-issue
            diagnosis_basis=basis,
            note=note,
            failed_cases=failed_cases if is_valid else [],
            image_findings=image_findings,
        )
