"""Health check endpoint."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import DbDep, DiagnosisServiceDep
from app.schemas.common import HealthResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Health"])


@router.get(
    "/health/live",
    summary="Liveness check (no dependencies)",
    description=(
        "Returns 200 whenever the process is up and serving, without checking the database, "
        "vector store or LLM. Use it as a hosting platform's health-check path so that a "
        "third-party outage (e.g. the LLM provider) does not make the platform restart a "
        "perfectly healthy server. Use `/health` for readiness/diagnostics."
    ),
)
def live() -> dict[str, str]:
    return {"status": "alive"}


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness/readiness check",
    description=(
        "Verifies the SQL database, the vector store and the LLM backend (Ollama, with the "
        "configured model pulled) respond. Returns 200 when healthy and 503 when a dependency "
        "is down, so load balancers/orchestrators can act on it."
    ),
    responses={503: {"model": HealthResponse, "description": "A dependency is unavailable."}},
)
def health(request: Request, db: DbDep, diagnosis_service: DiagnosisServiceDep):
    database_ok = vector_ok = llm_ok = True
    kb_size = 0

    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("health_database_check_failed")
        database_ok = False

    try:
        kb_size = diagnosis_service.knowledge_base_size()
    except Exception:
        logger.exception("health_vector_store_check_failed")
        vector_ok = False

    try:
        llm_ok = diagnosis_service.llm_is_ready()
    except Exception:
        logger.exception("health_llm_check_failed")
        llm_ok = False

    body = HealthResponse(
        status="ok" if database_ok and vector_ok and llm_ok else "degraded",
        version=request.app.state.settings.app_version,
        database="ok" if database_ok else "error",
        vector_store="ok" if vector_ok else "error",
        llm="ok" if llm_ok else "error",
        knowledge_base_size=kb_size,
    )
    status_code = 200 if body.status == "ok" else 503
    return JSONResponse(status_code=status_code, content=body.model_dump())
