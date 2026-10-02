"""Combines all v1 routes under the /api/v1 prefix."""

from fastapi import APIRouter

from app.api.v1 import diagnose, history

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(diagnose.router)
api_v1_router.include_router(history.router)
