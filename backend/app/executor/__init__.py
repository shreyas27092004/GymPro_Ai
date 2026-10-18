# app/executor/__init__.py
from fastapi import APIRouter
from .bundles import router as bundles_router
from .single import router as single_router

executor_router = APIRouter()
executor_router.include_router(single_router)
executor_router.include_router(bundles_router)

__all__ = ["executor_router"]
