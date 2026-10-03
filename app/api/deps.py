"""FastAPI dependencies (dependency injection).

Route handlers declare what they need (a DB session, a service...) and
FastAPI supplies it.  Heavy, long-lived objects (the embedding model, the
Chroma collection, the DB engine) are built once at startup and kept on
``app.state``; these functions simply hand them out per request.  In tests we
replace them with ``app.dependency_overrides``.
"""

import logging
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import RateLimitedError
from app.core.rate_limit import client_key
from app.services.diagnosis_service import DiagnosisService
from app.services.feedback_service import FeedbackService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.review_service import ReviewService
from app.services.session_service import SessionService
from app.services.ticket_service import TicketService
from app.services.vision_service import VisionService


logger = logging.getLogger(__name__)


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    """Yield a DB session for one request and always close it afterwards."""
    session = request.app.state.session_factory()
    try:
        yield session
    except Exception:
        session.rollback()  # leave no half-finished transaction behind
        raise
    finally:
        session.close()


def get_diagnosis_service(request: Request) -> DiagnosisService:
    return request.app.state.diagnosis_service


def get_vision_service(request: Request) -> VisionService:
    return request.app.state.vision_service


def check_rate_limit(request: Request) -> None:
    """Count this request against the client's allowance. Raises 429 when over the limit."""
    decision = request.app.state.rate_limiter.check(
        client_key(request, request.app.state.settings.rate_limit_proxy_hops)
    )
    if not decision.allowed:
        logger.warning(
            "rate_limited",
            extra={"path": request.url.path, "retry_after": decision.retry_after_seconds},
        )
        raise RateLimitedError(decision.retry_after_seconds)


def enforce_rate_limit(request: Request) -> None:
    """Dependency for the endpoints that spend LLM/vision quota on every call."""
    check_rate_limit(request)


def get_ticket_service(db: Annotated[Session, Depends(get_db)]) -> TicketService:
    return TicketService(db)


def get_knowledge_base_service(request: Request) -> KnowledgeBaseService:
    return request.app.state.knowledge_base


def get_review_service(
    db: Annotated[Session, Depends(get_db)],
    knowledge_base: Annotated[KnowledgeBaseService, Depends(get_knowledge_base_service)],
) -> ReviewService:
    return ReviewService(db, knowledge_base)


def get_feedback_service(
    db: Annotated[Session, Depends(get_db)],
    tickets: Annotated[TicketService, Depends(get_ticket_service)],
    reviews: Annotated[ReviewService, Depends(get_review_service)],
    knowledge_base: Annotated[KnowledgeBaseService, Depends(get_knowledge_base_service)],
) -> FeedbackService:
    return FeedbackService(db, tickets, reviews, knowledge_base)


def get_session_service(
    db: Annotated[Session, Depends(get_db)],
    diagnosis_service: Annotated[DiagnosisService, Depends(get_diagnosis_service)],
    tickets: Annotated[TicketService, Depends(get_ticket_service)],
    reviews: Annotated[ReviewService, Depends(get_review_service)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> SessionService:
    return SessionService(db, diagnosis_service, tickets, reviews, settings.max_solution_attempts)


# Annotated aliases keep route signatures short and readable.
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
DbDep = Annotated[Session, Depends(get_db)]
DiagnosisServiceDep = Annotated[DiagnosisService, Depends(get_diagnosis_service)]
VisionServiceDep = Annotated[VisionService, Depends(get_vision_service)]
TicketServiceDep = Annotated[TicketService, Depends(get_ticket_service)]
KnowledgeBaseDep = Annotated[KnowledgeBaseService, Depends(get_knowledge_base_service)]
ReviewServiceDep = Annotated[ReviewService, Depends(get_review_service)]
SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]
FeedbackServiceDep = Annotated[FeedbackService, Depends(get_feedback_service)]
