"""Usage statistics: the arithmetic is a pure function so it can be tested without a database."""

from typing import Any

from app.schemas.review import KnowledgeBaseStats
from app.schemas.stats import AverageConfidence, ResolutionStats, ReviewCounts, SessionCounts, StatsResponse


def percentage(part: int, whole: int) -> float | None:
    """``part`` as a percent of ``whole`` to 1 decimal; None (not 0, not an error) if nothing to divide."""
    return round(part / whole * 100, 1) if whole else None


def _mean(value: float | None) -> float | None:
    return None if value is None else round(float(value), 3)


def build_stats(summary: dict[str, Any], knowledge_base: KnowledgeBaseStats | None) -> StatsResponse:
    """Turn raw counts/averages (from ``TicketService.usage_summary``) into the API response.

    ``knowledge_base`` is None when the vector store could not be read: the usage numbers (which come
    from the SQL database) are still returned rather than failing the whole dashboard.
    """
    by_basis = summary["by_basis"]
    similar = by_basis.get("similar_cases", 0)
    general = by_basis.get("general_reasoning", 0)
    counted = similar + general
    by_source = summary["by_source"]
    review = summary["by_review_status"]
    sessions = summary.get("sessions") or {}
    by_session_status = sessions.get("by_status", {})

    return StatsResponse(
        total_diagnoses_performed=summary["total"],
        text_diagnoses=by_source.get("text", 0),
        image_diagnoses=by_source.get("image", 0),
        resolution=ResolutionStats(
            counted=counted,
            similar_cases=similar,
            general_reasoning=general,
            similar_cases_pct=percentage(similar, counted),
            general_reasoning_pct=percentage(general, counted),
        ),
        knowledge_base_size=knowledge_base.total if knowledge_base else None,
        original_seed_count=knowledge_base.seed if knowledge_base else None,
        technician_verified_count=knowledge_base.verified if knowledge_base else None,
        verified_fix_count=knowledge_base.verified if knowledge_base else None,
        provisional_fix_count=knowledge_base.provisional if knowledge_base else None,
        failed_fix_count=knowledge_base.failed if knowledge_base else None,
        review=ReviewCounts(
            pending=review.get("pending", 0),
            confirmed=review.get("confirmed", 0),
            corrected=review.get("corrected", 0),
        ),
        average_confidence=AverageConfidence(
            retrieval=_mean(summary["avg_retrieval_confidence"]),
            llm=_mean(summary["avg_llm_confidence"]),
            image=_mean(summary["avg_image_confidence"]),
        ),
        sessions=SessionCounts(
            total=sum(by_session_status.values()),
            in_progress=by_session_status.get("in_progress", 0),
            resolved=by_session_status.get("resolved", 0),
            abandoned=by_session_status.get("abandoned", 0),
            average_attempts_to_resolve=(
                None if sessions.get("avg_attempts_to_resolve") is None else round(float(sessions["avg_attempts_to_resolve"]), 2)
            ),
        ),
    )
