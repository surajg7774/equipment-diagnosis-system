"""Application factory and wiring.

Run with:  uvicorn app.main:app --reload
Docs at:   http://localhost:8000/docs
"""

import logging
import threading
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import health
from app.api.v1.router import api_v1_router
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.core.logging import request_id_ctx, setup_logging
from app.db.seed import seed_if_empty
from app.db.session import create_db_engine, create_session_factory, init_db
from app.db.vector_store import create_chroma_client, get_or_create_collection
from app.schemas.common import ErrorBody, ErrorResponse, FieldError
from app.services.diagnosis_service import DiagnosisService
from app.services.embedding_service import create_embedder
from app.services.llm_service import create_llm_service
from app.services.vision_service import create_vision_service

logger = logging.getLogger(__name__)

API_DESCRIPTION = """
AI-assisted equipment fault diagnosis for field technicians.

Describe a problem in plain English; the service finds the most similar past
issues in a vector database (**RAG retrieval**), and returns a likely root
cause, recommended action, severity and confidence score.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build long-lived resources once at startup; release them at shutdown."""
    settings: Settings = app.state.settings

    engine = create_db_engine(settings.database_url)
    init_db(engine)

    embedder = create_embedder(settings.embedding_backend, settings.embedding_model_name)
    embedder.load()  # load now so the first request is not slow

    collection = get_or_create_collection(
        create_chroma_client(settings.chroma_persist_dir), settings.chroma_collection_name
    )
    if collection.count() == 0:
        # Empty store: first run, or a host with an ephemeral filesystem (e.g. Render's free
        # tier) wiped chroma_db on restart. Rebuild it from the JSON file.
        if settings.auto_seed_on_startup:
            try:
                report = seed_if_empty(collection, embedder, settings.knowledge_base_path)
                logger.info("knowledge_base_auto_seeded", extra={"records": report.total_in_store if report else 0})
            except Exception:  # keep the API up (health will show 0 records) rather than crash-loop
                logger.exception("knowledge_base_auto_seed_failed")
        else:
            logger.warning("knowledge_base_empty", extra={"hint": "run `python -m app.db.seed` to load it"})

    # The LLM adapter (Ollama or Groq) is chosen by LLM_PROVIDER; see llm_service.py.
    llm_service = create_llm_service(settings)
    logger.info(
        "llm_configured",
        extra={
            "provider": settings.llm_provider,
            "embedding_backend": settings.embedding_backend,
            "vision_provider": settings.vision_provider,
        },
    )
    # Ollama: loading the model into memory can take minutes on a cold start. Do it in a
    # background thread so the server starts accepting requests immediately and the first
    # real diagnosis is (usually) fast. (A no-op for Groq.) It never raises.
    threading.Thread(target=llm_service.warm_up, name="llm-warm-up", daemon=True).start()

    app.state.session_factory = create_session_factory(engine)
    app.state.diagnosis_service = DiagnosisService(
        embedder=embedder,
        collection=collection,
        llm=llm_service,
        top_k=settings.top_k,
        low_confidence_threshold=settings.low_confidence_threshold,
    )
    # Image analysis: a vision-language model chosen by VISION_PROVIDER (see vision_service.py).
    vision_service = create_vision_service(settings)
    app.state.vision_service = vision_service

    logger.info("app_started", extra={"environment": settings.environment})
    yield
    llm_service.close()
    vision_service.close()
    engine.dispose()
    logger.info("app_stopped")


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[FieldError] | None = None,
    request_id: str | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, details=details, request_id=request_id)
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(exclude_none=True))


def register_exception_handlers(app: FastAPI) -> None:
    """Make every error leave the API in the same JSON shape, with no stack traces."""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning("app_error", extra={"code": exc.code, "error_message": exc.message})
        return _error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            FieldError(
                # loc looks like ("body", "description"); drop the "body"/"query" prefix.
                field=".".join(str(part) for part in err["loc"][1:]) or str(err["loc"][0]),
                message=err["msg"],
            )
            for err in exc.errors()
        ]
        return _error_response(422, "validation_error", "Request validation failed.", details)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # 404 unknown route, 405 wrong method, etc.
        return _error_response(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Full traceback goes to the log; the client only gets a generic message
        # plus a request id that support can use to find the log entry.
        request_id = getattr(request.state, "request_id", None)
        logger.error(
            "unhandled_exception",
            exc_info=exc,
            extra={"path": request.url.path, "request_id": request_id},
        )
        return _error_response(
            500, "internal_error", "An internal error occurred.", request_id=request_id
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=API_DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.settings = settings

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        """Tag each request with an id, and log method/path/status/latency."""
        request_id = request.headers.get("X-Request-ID") or uuid4().hex
        request.state.request_id = request_id
        token = request_id_ctx.set(request_id)
        started = perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "latency_ms": round((perf_counter() - started) * 1000, 1),
                "request_id": request_id,
            },
        )
        return response

    register_exception_handlers(app)

    # CORS: in production the frontend (e.g. Vercel) and this API are on different origins, and
    # browsers block cross-origin calls unless the API says the origin is allowed.
    # Added LAST so it is the outermost middleware and also covers error responses.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )

    app.include_router(health.router)
    app.include_router(api_v1_router)
    return app


app = create_app()
