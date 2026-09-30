"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from redis import Redis

from app.api import router
from app.config import Settings, load_settings
from app.deps import reset, set_settings, set_store
from app.redis_client import create_redis
from app.store import JobStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


def create_app(
    *,
    redis: Redis | None = None,
    job_store: JobStore | None = None,
    config: Settings | None = None,
) -> FastAPI:
    """Build the FastAPI app.

    Optional redis/store/config are for tests (e.g. fakeredis + Celery eager).
    Background work is handled by Celery workers, not in-process threads.
    """
    cfg = config or load_settings()
    client = redis or create_redis(cfg)
    store = job_store or JobStore(client, config=cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[dict]:
        set_settings(cfg)
        set_store(store)
        try:
            yield {"store": store, "redis": client}
        finally:
            reset()
            if redis is None:
                client.close()

    app = FastAPI(
        title="Async Job Processing API",
        description=(
            "Submit jobs for Celery workers over Redis. "
            "Job state and idempotency keys live in Redis."
        ),
        version="1.1.0",
        lifespan=lifespan,
    )
    app.state.store = store
    app.state.redis = client
    # Keep get_store() aligned even before lifespan (TestClient edge cases).
    set_settings(cfg)
    set_store(store)
    app.include_router(router)
    return app


# For `uvicorn app.main:app`
app = create_app()
