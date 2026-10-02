"""Transparency endpoint: usage and knowledge-base growth at a glance."""

import logging

from fastapi import APIRouter

from app.api.deps import KnowledgeBaseDep, TicketServiceDep
from app.core.exceptions import KnowledgeBaseUpdateError
from app.schemas.common import ErrorResponse
from app.schemas.stats import StatsResponse
from app.services.stats_service import build_stats

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Stats"])


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Usage and knowledge-base statistics",
    description=(
        "Total diagnoses, the share resolved from similar past cases vs the LLM's general reasoning, "
        "how many knowledge-base records are original seed vs technician-verified, review progress, "
        "and average confidence scores. If the vector store is unreachable the knowledge-base fields "
        "are null but the usage numbers are still returned."
    ),
    responses={500: {"model": ErrorResponse, "description": "Unexpected server error."}},
)
def get_stats(tickets: TicketServiceDep, knowledge_base: KnowledgeBaseDep) -> StatsResponse:
    try:
        kb_stats = knowledge_base.stats()
    except KnowledgeBaseUpdateError:  # keep the dashboard up; the usage numbers do not need the vector store
        logger.warning("stats_without_knowledge_base")
        kb_stats = None
    return build_stats(tickets.usage_summary(), kb_stats)
