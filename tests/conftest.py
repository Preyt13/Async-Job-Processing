"""Shared pytest fixtures — fakeredis + Celery eager mode."""

from __future__ import annotations

import uuid

import fakeredis
import pytest

from app import deps
from app.celery_app import celery
from app.config import Settings
from app.store import JobStore


def make_settings(**overrides) -> Settings:
    base = dict(
        max_retries=2,
        base_backoff_seconds=0.01,
        retry_jitter_ratio=0.25,
        mock_work_seconds=0,
        redis_url="redis://localhost:6379/0",
        celery_broker_url="redis://localhost:6379/1",
        redis_key_prefix=f"test-{uuid.uuid4().hex[:8]}",
        idempotency_ttl_seconds=3600,
        celery_concurrency=2,
        celery_queue="jobs",
        celery_prefetch_multiplier=1,
        celery_task_always_eager=True,
        job_ttl_seconds=3600,
        stuck_running_seconds=60,
        reaper_interval_seconds=30,
        purge_interval_seconds=60,
        job_lock_timeout_seconds=5,
        job_lock_blocking_timeout_seconds=5,
        dlq_list_default_limit=100,
        api_host="127.0.0.1",
        api_port=8000,
        log_level="INFO",
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def redis_client():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def store(redis_client, settings) -> JobStore:
    return JobStore(redis_client, config=settings)


@pytest.fixture(autouse=True)
def celery_eager(store, settings):
    """Run Celery tasks in-process; point workers at the test JobStore."""
    deps.set_store(store)
    deps.set_settings(settings)
    celery.conf.task_always_eager = True
    celery.conf.task_eager_propagates = False
    yield
    deps.reset()
    celery.conf.task_always_eager = False
    celery.conf.task_eager_propagates = False
