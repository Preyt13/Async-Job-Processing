"""Redis-backed job store, DLQ, and TTL helpers."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Iterable

from redis import Redis

from app.config import Settings, settings
from app.models import DLQEntry, Job, JobStatus


class JobStore:
    """Persist job records in Redis with per-job locks for safe updates."""

    def __init__(
        self,
        redis: Redis,
        *,
        config: Settings | None = None,
    ) -> None:
        self._redis = redis
        self._config = config or settings

    def create(self, job: Job) -> Job:
        if job.expires_at is None:
            # Ensure every job has an absolute expiry.
            from datetime import timedelta

            job.expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=self._config.job_ttl_seconds
            )
        key = self._config.job_key(job.id)
        ttl = job.remaining_ttl_seconds() or self._config.job_ttl_seconds
        pipe = self._redis.pipeline()
        pipe.set(key, json.dumps(job.to_dict()), ex=max(1, ttl))
        pipe.sadd(self._config.job_ids_key(), job.id)
        pipe.execute()
        return job

    def get(self, job_id: str) -> Job | None:
        raw = self._redis.get(self._config.job_key(job_id))
        if raw is None:
            # Drop stale index entries when Redis TTL has deleted the key.
            self._redis.srem(self._config.job_ids_key(), job_id)
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        job = Job.from_dict(json.loads(raw))
        if job.is_expired():
            self.delete(job_id)
            return None
        return job

    def delete(self, job_id: str) -> None:
        pipe = self._redis.pipeline()
        pipe.delete(self._config.job_key(job_id))
        pipe.delete(f"{self._config.redis_key_prefix}:lock:{job_id}")
        pipe.srem(self._config.job_ids_key(), job_id)
        pipe.execute()

    def get_idempotent_job_id(self, client_key: str) -> str | None:
        raw = self._redis.get(self._config.idempotency_key(client_key))
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else raw

    def try_claim_idempotency(self, client_key: str, job_id: str) -> bool:
        """Atomically claim an idempotency key for job_id. True if we won."""
        return bool(
            self._redis.set(
                self._config.idempotency_key(client_key),
                job_id,
                nx=True,
                ex=self._config.idempotency_ttl_seconds,
            )
        )

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        result: dict | None = None,
        error: str | None = None,
        clear_error: bool = False,
        increment_attempts: bool = False,
        reset_attempts: bool = False,
        clear_result: bool = False,
    ) -> Job | None:
        with _JobLock(
            self._redis,
            self._config.redis_key_prefix,
            job_id,
            timeout=self._config.job_lock_timeout_seconds,
            blocking_timeout=self._config.job_lock_blocking_timeout_seconds,
        ):
            job = self.get(job_id)
            if job is None:
                return None
            job.status = status
            if reset_attempts:
                job.attempts = 0
            elif increment_attempts:
                job.attempts += 1
            if result is not None:
                job.result = result
            if clear_result:
                job.result = None
            if clear_error:
                job.error = None
            elif error is not None:
                job.error = error
            job.touch()
            self._write_job(job)
            return job

    def _write_job(self, job: Job) -> None:
        key = self._config.job_key(job.id)
        ttl = job.remaining_ttl_seconds()
        payload = json.dumps(job.to_dict())
        if ttl is None:
            self._redis.set(key, payload, ex=self._config.job_ttl_seconds)
        elif ttl <= 0:
            self.delete(job.id)
        else:
            self._redis.set(key, payload, ex=ttl)

    # --- DLQ -----------------------------------------------------------------

    def push_to_dlq(
        self,
        job: Job,
        *,
        error: str,
        reason: str,
    ) -> DLQEntry:
        entry = DLQEntry(
            job_id=job.id,
            error=error,
            attempts=job.attempts,
            reason=reason,
            failed_at=datetime.now(timezone.utc),
            payload=job.payload,
        )
        self._redis.lpush(self._config.dlq_key(), entry.model_dump_json())
        return entry

    def list_dlq(self, limit: int = 100) -> list[DLQEntry]:
        raw_items = self._redis.lrange(self._config.dlq_key(), 0, max(0, limit - 1))
        entries: list[DLQEntry] = []
        for raw in raw_items:
            if isinstance(raw, bytes):
                raw = raw.decode()
            entries.append(DLQEntry.model_validate_json(raw))
        return entries

    def remove_from_dlq(self, job_id: str) -> int:
        """Remove all DLQ entries for job_id. Returns count removed."""
        key = self._config.dlq_key()
        items = self._redis.lrange(key, 0, -1)
        removed = 0
        seen: set[str] = set()
        for raw in items:
            text = raw.decode() if isinstance(raw, bytes) else raw
            if text in seen:
                continue
            entry = DLQEntry.model_validate_json(text)
            if entry.job_id == job_id:
                removed += int(self._redis.lrem(key, 0, raw) or 0)
                seen.add(text)
        return removed

    def mark_failed_to_dlq(
        self,
        job_id: str,
        *,
        error: str,
        reason: str,
    ) -> DLQEntry | None:
        job = self.update_status(job_id, JobStatus.FAILED, error=error)
        if job is None:
            return None
        return self.push_to_dlq(job, error=error, reason=reason)

    def prepare_replay(self, job_id: str) -> Job | None:
        """Reset a failed (or completed) job for re-enqueue. Removes DLQ entries."""
        job = self.update_status(
            job_id,
            JobStatus.QUEUED,
            clear_error=True,
            clear_result=True,
            reset_attempts=True,
        )
        if job is None:
            return None
        self.remove_from_dlq(job_id)
        return job

    # --- Reaper / TTL maintenance --------------------------------------------

    def list_jobs(
        self,
        *,
        status: JobStatus | None = None,
        limit: int = 100,
    ) -> list[Job]:
        jobs = list(self.values())
        if status is not None:
            jobs = [j for j in jobs if j.status == status]
        jobs.sort(key=lambda j: j.updated_at, reverse=True)
        return jobs[: max(0, limit)]

    def metrics(self) -> dict:
        settings = self._config
        counts = {
            "queued": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
        }
        for job in self.values():
            counts[job.status.value] = counts.get(job.status.value, 0) + 1

        stuck = self.find_stuck_running(settings.stuck_running_seconds)
        dlq_depth = int(self._redis.llen(self._config.dlq_key()) or 0)
        # Celery Redis broker stores the queue as a list named after CELERY_QUEUE.
        celery_depth = int(self._redis.llen(settings.celery_queue) or 0)

        return {
            "total_jobs": sum(counts.values()),
            "queued": counts["queued"],
            "running": counts["running"],
            "completed": counts["completed"],
            "failed": counts["failed"],
            "stuck_running": len(stuck),
            "dlq_depth": dlq_depth,
            "celery_queue_depth": celery_depth,
            "stuck_threshold_seconds": settings.stuck_running_seconds,
        }

    def find_stuck_running(self, older_than_seconds: int) -> list[Job]:
        now = datetime.now(timezone.utc)
        stuck: list[Job] = []
        for job in self.values():
            if job.status != JobStatus.RUNNING:
                continue
            age = (now - job.updated_at).total_seconds()
            if age >= older_than_seconds:
                stuck.append(job)
        return stuck

    def purge_expired_index(self) -> int:
        """Remove index / DLQ leftovers for TTL-expired jobs. Returns purged count."""
        purged = 0
        for job_id in self.list_ids():
            if self._redis.exists(self._config.job_key(job_id)):
                continue
            self._redis.srem(self._config.job_ids_key(), job_id)
            self.remove_from_dlq(job_id)
            purged += 1
        return purged

    def list_ids(self) -> list[str]:
        members = self._redis.smembers(self._config.job_ids_key())
        return sorted(
            m.decode() if isinstance(m, bytes) else m for m in members
        )

    def clear(self) -> None:
        ids = self.list_ids()
        pipe = self._redis.pipeline()
        for job_id in ids:
            pipe.delete(self._config.job_key(job_id))
            pipe.delete(f"{self._config.redis_key_prefix}:lock:{job_id}")
        pipe.delete(self._config.job_ids_key())
        pipe.delete(self._config.dlq_key())
        pipe.execute()

    def __len__(self) -> int:
        return int(self._redis.scard(self._config.job_ids_key()) or 0)

    def values(self) -> Iterable[Job]:
        jobs: list[Job] = []
        for job_id in self.list_ids():
            job = self.get(job_id)
            if job is not None:
                jobs.append(job)
        return jobs


class _JobLock:
    """Simple distributed lock via SET NX EX (no Lua — works with fakeredis)."""

    def __init__(
        self,
        redis: Redis,
        prefix: str,
        job_id: str,
        *,
        timeout: float,
        blocking_timeout: float,
    ) -> None:
        self._redis = redis
        self._key = f"{prefix}:lock:{job_id}"
        self._token = str(uuid.uuid4())
        self._timeout = int(timeout)
        self._blocking_timeout = blocking_timeout

    def __enter__(self) -> _JobLock:
        deadline = time.time() + self._blocking_timeout
        while time.time() < deadline:
            if self._redis.set(self._key, self._token, nx=True, ex=self._timeout):
                return self
            time.sleep(0.01)
        raise TimeoutError(f"Could not acquire lock {self._key}")

    def __exit__(self, exc_type, exc, tb) -> None:
        current = self._redis.get(self._key)
        if isinstance(current, bytes):
            current = current.decode()
        if current == self._token:
            self._redis.delete(self._key)
