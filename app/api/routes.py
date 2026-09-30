"""HTTP API routes."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse

from app.deps import get_settings
from app.models import (
    DLQEntry,
    Job,
    JobResponse,
    JobStatus,
    JobSubmitRequest,
    JobSubmitResponse,
    MetricsResponse,
    ReplayResponse,
)
from app.worker.tasks import enqueue_job, purge_expired_jobs, reap_stuck_jobs, replay_job

router = APIRouter()


def _store(request: Request):
    return getattr(request.state, "store", None) or request.app.state.store


@router.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Send browsers to the clickable demo UI."""
    return RedirectResponse(url="/demo", status_code=307)


@router.get("/demo", include_in_schema=False)
def browser_demo() -> FileResponse:
    """Clickable browser UI for happy path, DLQ, replay, idempotency."""
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "static" / "demo.html"
    return FileResponse(path, media_type="text/html")


@router.post("/jobs", response_model=JobSubmitResponse, status_code=202)
def submit_job(
    body: JobSubmitRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JobSubmitResponse:
    store = _store(request)
    settings = get_settings()

    if idempotency_key:
        existing_id = store.get_idempotent_job_id(idempotency_key)
        if existing_id:
            existing = store.get(existing_id)
            if existing is not None:
                return JobSubmitResponse(id=existing.id, status=existing.status)

    job = Job(
        payload=body.data,
        should_fail=body.should_fail,
        work_seconds=body.work_seconds,
        ttl_seconds=settings.job_ttl_seconds,
    )

    if idempotency_key and not store.try_claim_idempotency(idempotency_key, job.id):
        existing_id = store.get_idempotent_job_id(idempotency_key)
        if existing_id:
            existing = store.get(existing_id)
            if existing is not None:
                return JobSubmitResponse(id=existing.id, status=existing.status)

    store.create(job)
    enqueue_job(job.id)
    return JobSubmitResponse(id=job.id, status=job.status)


@router.get("/jobs", response_model=list[JobResponse])
def list_jobs(
    request: Request,
    status: JobStatus | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[JobResponse]:
    """List jobs newest-first. Optional status filter: queued|running|completed|failed."""
    store = _store(request)
    return [j.to_response() for j in store.list_jobs(status=status, limit=limit)]


@router.get("/metrics", response_model=MetricsResponse)
def metrics(request: Request) -> MetricsResponse:
    """Queue / status counters including stuck-running and DLQ depth."""
    store = _store(request)
    return MetricsResponse(**store.metrics())


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, request: Request) -> JobResponse:
    store = _store(request)
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_response()


@router.post("/jobs/{job_id}/replay", response_model=ReplayResponse, status_code=202)
def replay_failed_job(job_id: str, request: Request) -> ReplayResponse:
    """Remove job from DLQ (if present), reset state, and re-enqueue via Celery."""
    store = _store(request)
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    replayed = replay_job(job_id)
    if replayed is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return ReplayResponse(id=replayed.id, status=replayed.status, replayed=True)


@router.get("/dlq", response_model=list[DLQEntry])
def list_dead_letters(
    request: Request,
    limit: int | None = Query(default=None, ge=1, le=1000),
) -> list[DLQEntry]:
    store = _store(request)
    settings = get_settings()
    resolved_limit = limit if limit is not None else settings.dlq_list_default_limit
    return store.list_dlq(limit=resolved_limit)

@router.post("/admin/reap-stuck")
def trigger_reaper() -> dict:
    """Manually run the stuck-job reaper (also scheduled via Celery Beat)."""
    reaped = reap_stuck_jobs.run()
    return {"reaped": reaped, "count": len(reaped)}


@router.post("/admin/purge-expired")
def trigger_purge() -> dict:
    """Manually purge TTL-expired job index/DLQ leftovers."""
    purged = purge_expired_jobs.run()
    return {"purged": purged}


@router.get("/health")
def health(request: Request) -> dict[str, str]:
    redis = getattr(request.state, "redis", None) or getattr(
        request.app.state, "redis", None
    )
    redis_status = "ok"
    if redis is not None:
        try:
            redis.ping()
        except Exception:  # noqa: BLE001
            redis_status = "error"
    else:
        redis_status = "unavailable"
    return {"status": "ok", "redis": redis_status, "queue": "celery"}
