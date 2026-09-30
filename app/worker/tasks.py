"""Celery tasks for background job processing, DLQ, and maintenance."""

from __future__ import annotations

import logging

from app.celery_app import celery
from app.deps import get_settings, get_store
from app.models import JobStatus
from app.worker.processor import compute_backoff_seconds, process_job

logger = logging.getLogger(__name__)


@celery.task(
    bind=True,
    name="app.worker.tasks.process_job",
    max_retries=None,
    acks_late=True,
    reject_on_worker_lost=True,
)
def process_job_task(self, job_id: str) -> dict | None:
    """Pull job state from Redis, run mock work, retry with backoff+jitter."""
    store = get_store()
    settings = get_settings()
    max_retries = settings.max_retries

    job = store.get(job_id)
    if job is None:
        logger.warning("Celery task for unknown/expired job %s — skipping", job_id)
        return None

    store.update_status(job_id, JobStatus.RUNNING, increment_attempts=True)
    job = store.get(job_id)
    if job is None:
        return None

    work_seconds = (
        job.work_seconds
        if job.work_seconds is not None
        else settings.mock_work_seconds
    )

    try:
        result = process_job(
            job.payload,
            should_fail=job.should_fail,
            work_seconds=work_seconds,
        )
    except Exception as exc:
        attempt = self.request.retries + 1
        if self.request.retries >= max_retries:
            store.mark_failed_to_dlq(
                job_id,
                error=str(exc),
                reason="max_retries",
            )
            logger.info(
                "Job %s failed permanently after %s attempts — sent to DLQ",
                job_id,
                job.attempts,
            )
            raise

        delay = compute_backoff_seconds(
            attempt,
            base_seconds=settings.base_backoff_seconds,
            jitter_ratio=settings.retry_jitter_ratio,
        )
        store.update_status(job_id, JobStatus.QUEUED, error=str(exc))
        logger.info(
            "Job %s attempt %s failed; Celery retry in %.3fs: %s",
            job_id,
            job.attempts,
            delay,
            exc,
        )
        raise self.retry(exc=exc, countdown=delay, max_retries=max_retries)

    store.update_status(
        job_id,
        JobStatus.COMPLETED,
        result=result,
        clear_error=True,
    )
    logger.info("Job %s completed on attempt %s", job_id, job.attempts)
    return result


@celery.task(name="app.worker.tasks.reap_stuck_jobs")
def reap_stuck_jobs() -> list[str]:
    """Fail jobs stuck in running and push them to the DLQ."""
    store = get_store()
    settings = get_settings()
    stuck = store.find_stuck_running(settings.stuck_running_seconds)
    reaped: list[str] = []
    for job in stuck:
        error = (
            f"stuck in running for >{settings.stuck_running_seconds}s — reaped"
        )
        store.mark_failed_to_dlq(job.id, error=error, reason="stuck_running")
        reaped.append(job.id)
        logger.warning("Reaped stuck job %s", job.id)
    return reaped


@celery.task(name="app.worker.tasks.purge_expired_jobs")
def purge_expired_jobs() -> int:
    """Clean index/DLQ entries for Redis-TTL-expired jobs."""
    store = get_store()
    purged = store.purge_expired_index()
    if purged:
        logger.info("Purged %s expired job index entries", purged)
    return purged


def enqueue_job(job_id: str):
    """Send job to Celery. Returns AsyncResult (or EagerResult in tests)."""
    return process_job_task.delay(job_id)


def replay_job(job_id: str):
    """Reset job state, drop DLQ entries, and re-enqueue."""
    store = get_store()
    job = store.prepare_replay(job_id)
    if job is None:
        return None
    enqueue_job(job.id)
    return job
