"""FastAPI dependencies (dependency injection).

Route handlers declare what they need (a DB session, a service...) and
FastAPI supplies it.  Heavy, long-lived objects (the embedding model, the
Chroma collection, the DB engine) are built once at startup and kept on
``app.state``; these functions simply hand them out per request.  In tests we
replace them with ``app.dependency_overrides``.
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.diagnosis_service import DiagnosisService
from app.services.ticket_service import TicketService
from app.services.vision_service import VisionService


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


def get_ticket_service(db: Annotated[Session, Depends(get_db)]) -> TicketService:
    return TicketService(db)


# Annotated aliases keep route signatures short and readable.
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
DbDep = Annotated[Session, Depends(get_db)]
DiagnosisServiceDep = Annotated[DiagnosisService, Depends(get_diagnosis_service)]
VisionServiceDep = Annotated[VisionService, Depends(get_vision_service)]
TicketServiceDep = Annotated[TicketService, Depends(get_ticket_service)]
