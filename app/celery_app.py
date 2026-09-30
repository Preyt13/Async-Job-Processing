"""Celery application — broker and queues configured from environment."""

from __future__ import annotations

import ssl

from celery import Celery
from celery.schedules import schedule

from app.config import load_settings

_settings = load_settings()

_broker_ssl = None
if _settings.celery_broker_url.startswith("rediss://"):
    # Required for DigitalOcean managed Valkey/Redis TLS endpoints.
    _broker_ssl = {"ssl_cert_reqs": ssl.CERT_REQUIRED}

celery = Celery(
    "async_jobs",
    broker=_settings.celery_broker_url,
    include=["app.worker.tasks"],
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=_settings.celery_prefetch_multiplier,
    broker_connection_retry_on_startup=True,
    task_default_queue=_settings.celery_queue,
    task_track_started=True,
    broker_use_ssl=_broker_ssl,
    beat_schedule={
        "reap-stuck-jobs": {
            "task": "app.worker.tasks.reap_stuck_jobs",
            "schedule": schedule(run_every=_settings.reaper_interval_seconds),
        },
        "purge-expired-jobs": {
            "task": "app.worker.tasks.purge_expired_jobs",
            "schedule": schedule(run_every=_settings.purge_interval_seconds),
        },
    },
    task_always_eager=_settings.celery_task_always_eager,
    task_eager_propagates=_settings.celery_task_always_eager,
)
