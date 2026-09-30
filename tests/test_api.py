"""Integration tests for the HTTP API layer (fakeredis + Celery eager)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.store import JobStore


@pytest.fixture
def client(redis_client, store: JobStore, settings: Settings):
    app = create_app(redis=redis_client, job_store=store, config=settings)
    with TestClient(app) as test_client:
        yield test_client


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["redis"] == "ok"
    assert body["queue"] == "celery"


def test_submit_returns_id_immediately(client: TestClient):
    response = client.post(
        "/jobs",
        json={"data": {"task": "demo"}, "work_seconds": 0},
    )
    assert response.status_code == 202
    body = response.json()
    assert "id" in body
    assert body["status"] in {"queued", "completed", "running"}


def test_status_lifecycle_completes(client: TestClient):
    submit = client.post(
        "/jobs",
        json={"data": {"task": "demo"}, "work_seconds": 0},
    )
    assert submit.status_code == 202
    job_id = submit.json()["id"]
    final = client.get(f"/jobs/{job_id}").json()
    assert final["status"] == "completed"
    assert final["result"]["processed"] is True
    assert final["result"]["echo"] == {"task": "demo"}
    assert final["attempts"] >= 1


def test_failed_job_after_retries(client: TestClient, monkeypatch, settings: Settings):
    monkeypatch.setattr(
        "app.worker.tasks.compute_backoff_seconds",
        lambda *args, **kwargs: 0,
    )
    submit = client.post(
        "/jobs",
        json={"data": {}, "should_fail": True, "work_seconds": 0},
    )
    assert submit.status_code == 202
    job_id = submit.json()["id"]
    final = client.get(f"/jobs/{job_id}").json()
    assert final["status"] == "failed"
    assert final["error"]
    assert final["attempts"] == settings.max_retries + 1


def test_unknown_job_returns_404(client: TestClient):
    response = client.get("/jobs/does-not-exist")
    assert response.status_code == 404


def test_idempotency_key_returns_same_job(client: TestClient):
    headers = {"Idempotency-Key": "client-req-123"}
    payload = {"data": {"task": "once"}, "work_seconds": 0}

    first = client.post("/jobs", json=payload, headers=headers)
    second = client.post("/jobs", json=payload, headers=headers)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]


def test_different_idempotency_keys_create_distinct_jobs(client: TestClient):
    payload = {"data": {"task": "dup-payload"}, "work_seconds": 0}

    a = client.post("/jobs", json=payload, headers={"Idempotency-Key": "key-a"})
    b = client.post("/jobs", json=payload, headers={"Idempotency-Key": "key-b"})

    assert a.json()["id"] != b.json()["id"]


def test_list_jobs_and_filter(client: TestClient):
    client.post("/jobs", json={"data": {"task": "ok"}, "work_seconds": 0})
    client.post(
        "/jobs",
        json={"data": {"task": "bad"}, "should_fail": True, "work_seconds": 0},
    )

    all_jobs = client.get("/jobs")
    assert all_jobs.status_code == 200
    body = all_jobs.json()
    assert len(body) >= 2
    assert all(set(j.keys()) >= {"id", "status", "attempts"} for j in body)

    completed = client.get("/jobs", params={"status": "completed"})
    assert completed.status_code == 200
    assert all(j["status"] == "completed" for j in completed.json())

    failed = client.get("/jobs", params={"status": "failed"})
    assert failed.status_code == 200
    assert all(j["status"] == "failed" for j in failed.json())
    assert len(failed.json()) >= 1


def test_metrics_counts(client: TestClient, monkeypatch, settings: Settings):
    monkeypatch.setattr(
        "app.worker.tasks.compute_backoff_seconds",
        lambda *args, **kwargs: 0,
    )
    client.post("/jobs", json={"data": {"task": "ok"}, "work_seconds": 0})
    client.post(
        "/jobs",
        json={"data": {"task": "bad"}, "should_fail": True, "work_seconds": 0},
    )

    response = client.get("/metrics")
    assert response.status_code == 200
    m = response.json()
    assert m["total_jobs"] >= 2
    assert m["completed"] >= 1
    assert m["failed"] >= 1
    assert m["dlq_depth"] >= 1
    assert "stuck_running" in m
    assert "celery_queue_depth" in m
    assert m["stuck_threshold_seconds"] == settings.stuck_running_seconds
