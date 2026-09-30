"""Unit tests for Redis-backed JobStore."""

from __future__ import annotations

import threading

from app.models import Job, JobStatus
from app.store import JobStore


def test_create_and_get(store: JobStore):
    job = Job({"x": 1})
    store.create(job)
    fetched = store.get(job.id)
    assert fetched is not None
    assert fetched.payload == {"x": 1}
    assert fetched.status == JobStatus.QUEUED


def test_update_status_increments_attempts(store: JobStore):
    job = Job({})
    store.create(job)
    store.update_status(job.id, JobStatus.RUNNING, increment_attempts=True)
    updated = store.get(job.id)
    assert updated is not None
    assert updated.status == JobStatus.RUNNING
    assert updated.attempts == 1


def test_clear_error_on_success(store: JobStore):
    job = Job({})
    store.create(job)
    store.update_status(job.id, JobStatus.QUEUED, error="boom")
    store.update_status(
        job.id,
        JobStatus.COMPLETED,
        result={"ok": True},
        clear_error=True,
    )
    updated = store.get(job.id)
    assert updated is not None
    assert updated.error is None
    assert updated.result == {"ok": True}


def test_job_survives_store_rebind(redis_client, settings):
    """Simulates another process reading the same Redis keys."""
    writer = JobStore(redis_client, config=settings)
    job = Job({"persist": True})
    writer.create(job)

    reader = JobStore(redis_client, config=settings)
    fetched = reader.get(job.id)
    assert fetched is not None
    assert fetched.payload == {"persist": True}
    assert fetched.id == job.id


def test_concurrent_creates_and_updates(store: JobStore):
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            for i in range(25):
                job = Job({"n": n, "i": i})
                store.create(job)
                store.update_status(job.id, JobStatus.RUNNING, increment_attempts=True)
                store.update_status(
                    job.id,
                    JobStatus.COMPLETED,
                    result={"done": True},
                    clear_error=True,
                )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(store) == 4 * 25
    for job in store.values():
        assert job.status == JobStatus.COMPLETED
        assert job.attempts == 1
