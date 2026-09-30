"""Unit tests for processor helpers and Celery job tasks."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.models import Job, JobStatus
from app.store import JobStore
from app.worker.processor import compute_backoff_seconds, process_job
from app.worker.tasks import enqueue_job


def test_compute_backoff_grows_exponentially(monkeypatch):
    monkeypatch.setattr(
        "app.worker.processor.random.uniform",
        lambda _a, _b: 0.0,
    )
    assert compute_backoff_seconds(
        1, base_seconds=0.2, jitter_ratio=0.25
    ) == pytest.approx(0.2)
    assert compute_backoff_seconds(
        2, base_seconds=0.2, jitter_ratio=0.25
    ) == pytest.approx(0.4)
    assert compute_backoff_seconds(
        3, base_seconds=0.2, jitter_ratio=0.25
    ) == pytest.approx(0.8)


def test_compute_backoff_applies_jitter(monkeypatch):
    monkeypatch.setattr(
        "app.worker.processor.random.uniform",
        lambda _a, _b: 1.0,
    )
    assert compute_backoff_seconds(
        1, base_seconds=1.0, jitter_ratio=0.25
    ) == pytest.approx(1.25)


def test_process_job_success():
    result = process_job({"a": 1}, should_fail=False, work_seconds=0)
    assert result["processed"] is True
    assert result["echo"] == {"a": 1}


def test_process_job_failure():
    with pytest.raises(RuntimeError, match="mock processing failure"):
        process_job({}, should_fail=True, work_seconds=0)


def test_celery_task_completes_job(store: JobStore):
    job = Job({"x": 1}, work_seconds=0)
    store.create(job)
    enqueue_job(job.id)

    done = store.get(job.id)
    assert done is not None
    assert done.status == JobStatus.COMPLETED
    assert done.result["processed"] is True
    assert done.attempts == 1


def test_celery_task_retries_then_fails(store: JobStore, settings: Settings, monkeypatch):
    monkeypatch.setattr(
        "app.worker.tasks.compute_backoff_seconds",
        lambda *args, **kwargs: 0,
    )

    job = Job({}, should_fail=True, work_seconds=0)
    store.create(job)
    enqueue_job(job.id)  # eager mode runs retries in-process

    failed = store.get(job.id)
    assert failed is not None
    assert failed.status == JobStatus.FAILED
    assert failed.attempts == settings.max_retries + 1
    assert failed.error


def test_celery_task_retries_then_succeeds(store: JobStore, monkeypatch):
    monkeypatch.setattr(
        "app.worker.tasks.compute_backoff_seconds",
        lambda *args, **kwargs: 0,
    )
    calls = {"n": 0}
    original = process_job

    def flaky(payload, should_fail=False, work_seconds=0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return original(payload, should_fail=False, work_seconds=0)

    monkeypatch.setattr("app.worker.tasks.process_job", flaky)

    job = Job({"n": 1}, work_seconds=0)
    store.create(job)
    enqueue_job(job.id)

    done = store.get(job.id)
    assert done is not None
    assert done.status == JobStatus.COMPLETED
    assert done.attempts == 2
    assert done.error is None
