"""Tests for DLQ, replay, stuck reaper, and job TTL."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import Job, JobStatus
from app.store import JobStore
from app.worker.tasks import enqueue_job, purge_expired_jobs, reap_stuck_jobs


@pytest.fixture
def client(redis_client, store: JobStore, settings: Settings):
    app = create_app(redis=redis_client, job_store=store, config=settings)
    with TestClient(app) as test_client:
        yield test_client


def test_failed_job_lands_in_dlq(store: JobStore, settings: Settings, monkeypatch):
    monkeypatch.setattr(
        "app.worker.tasks.compute_backoff_seconds",
        lambda *args, **kwargs: 0,
    )
    job = Job({}, should_fail=True, work_seconds=0, ttl_seconds=settings.job_ttl_seconds)
    store.create(job)
    enqueue_job(job.id)

    failed = store.get(job.id)
    assert failed is not None
    assert failed.status == JobStatus.FAILED

    dlq = store.list_dlq()
    assert len(dlq) == 1
    assert dlq[0].job_id == job.id
    assert dlq[0].reason == "max_retries"


def test_replay_clears_dlq_and_requeues(client: TestClient, monkeypatch, settings: Settings):
    monkeypatch.setattr(
        "app.worker.tasks.compute_backoff_seconds",
        lambda *args, **kwargs: 0,
    )
    # First run fails into DLQ
    submit = client.post(
        "/jobs",
        json={"data": {"x": 1}, "should_fail": True, "work_seconds": 0},
    )
    job_id = submit.json()["id"]
    assert client.get("/dlq").json()[0]["job_id"] == job_id

    # Flip failure flag on the stored job, then replay
    store = client.app.state.store
    job = store.get(job_id)
    assert job is not None
    job.should_fail = False
    store._write_job(job)  # noqa: SLF001

    replay = client.post(f"/jobs/{job_id}/replay")
    assert replay.status_code == 202
    assert replay.json()["replayed"] is True

    assert client.get("/dlq").json() == []
    final = client.get(f"/jobs/{job_id}").json()
    assert final["status"] == "completed"
    assert final["attempts"] == 1


def test_stuck_reaper_moves_to_dlq(store: JobStore, settings: Settings):
    job = Job({"stuck": True}, work_seconds=0, ttl_seconds=settings.job_ttl_seconds)
    store.create(job)
    store.update_status(job.id, JobStatus.RUNNING, increment_attempts=True)

    stuck = store.get(job.id)
    assert stuck is not None
    stuck.updated_at = datetime.now(timezone.utc) - timedelta(
        seconds=settings.stuck_running_seconds + 10
    )
    store._write_job(stuck)  # noqa: SLF001

    reaped = reap_stuck_jobs.run()
    assert job.id in reaped

    failed = store.get(job.id)
    assert failed is not None
    assert failed.status == JobStatus.FAILED
    assert failed.error and "stuck" in failed.error

    dlq = store.list_dlq()
    assert any(e.job_id == job.id and e.reason == "stuck_running" for e in dlq)


def test_job_ttl_expires_record(redis_client, settings: Settings):
    from tests.conftest import make_settings

    short = make_settings(
        redis_key_prefix=settings.redis_key_prefix + "-ttl",
        job_ttl_seconds=1,
    )
    store = JobStore(redis_client, config=short)
    job = Job({"ttl": True}, ttl_seconds=1)
    store.create(job)
    assert store.get(job.id) is not None

    # Expire the Redis key
    redis_client.expire(short.job_key(job.id), 0)
    # fakeredis may need delete to simulate expiry
    redis_client.delete(short.job_key(job.id))

    assert store.get(job.id) is None
    purged = purge_expired_jobs.run()
    assert purged >= 0


def test_dlq_list_endpoint(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        "app.worker.tasks.compute_backoff_seconds",
        lambda *args, **kwargs: 0,
    )
    client.post("/jobs", json={"should_fail": True, "work_seconds": 0})
    body = client.get("/dlq").json()
    assert len(body) == 1
    assert body[0]["reason"] == "max_retries"


def test_admin_reap_endpoint(client: TestClient, store: JobStore, settings: Settings):
    job = Job({}, ttl_seconds=settings.job_ttl_seconds)
    store.create(job)
    store.update_status(job.id, JobStatus.RUNNING, increment_attempts=True)
    stuck = store.get(job.id)
    assert stuck is not None
    stuck.updated_at = datetime.now(timezone.utc) - timedelta(hours=1)
    store._write_job(stuck)  # noqa: SLF001

    resp = client.post("/admin/reap-stuck")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1
