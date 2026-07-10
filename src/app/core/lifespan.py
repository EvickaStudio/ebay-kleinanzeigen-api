from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from loguru import logger

from ..services.http_client import create_shared_client


def request_key_builder(_func, namespace="", *, request, **_) -> str:
    """Cache HTTP routes by request instead of per-request dependencies."""
    return f"{namespace}:{request.method}:{request.url}"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle: shared HTTP client and in-memory cache."""
    app.state.http_client = create_shared_client()
    FastAPICache.init(InMemoryBackend(), key_builder=request_key_builder)
    logger.info("Application startup complete")
    yield
    await app.state.http_client.aclose()
    logger.info("Application shutdown complete")
