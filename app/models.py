"""Job domain models and API schemas."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobSubmitRequest(BaseModel):
    """Payload accepted when submitting a new job."""

    data: dict[str, Any] = Field(default_factory=dict)
    should_fail: bool = False
    work_seconds: float | None = None


class JobResponse(BaseModel):
    id: str
    status: JobStatus
    payload: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None
    attempts: int = 0
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None


class JobSubmitResponse(BaseModel):
    id: str
    status: JobStatus


class DLQEntry(BaseModel):
    job_id: str
    error: str
    attempts: int
    reason: str
    failed_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class ReplayResponse(BaseModel):
    id: str
    status: JobStatus
    replayed: bool = True


class Job:
    """Job record persisted as JSON in Redis."""

    __slots__ = (
        "id",
        "status",
        "payload",
        "should_fail",
        "work_seconds",
        "result",
        "error",
        "attempts",
        "created_at",
        "updated_at",
        "expires_at",
    )

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        should_fail: bool = False,
        work_seconds: float | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        self.id = str(uuid4())
        self.status = JobStatus.QUEUED
        self.payload = payload
        self.should_fail = should_fail
        self.work_seconds = work_seconds
        self.result: dict[str, Any] | None = None
        self.error: str | None = None
        self.attempts = 0
        self.created_at = now
        self.updated_at = now
        self.expires_at: datetime | None = (
            now + timedelta(seconds=ttl_seconds) if ttl_seconds else None
        )

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        return (now or datetime.now(timezone.utc)) >= self.expires_at

    def remaining_ttl_seconds(self, now: datetime | None = None) -> int | None:
        if self.expires_at is None:
            return None
        now = now or datetime.now(timezone.utc)
        return max(0, int((self.expires_at - now).total_seconds()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status.value,
            "payload": self.payload,
            "should_fail": self.should_fail,
            "work_seconds": self.work_seconds,
            "result": self.result,
            "error": self.error,
            "attempts": self.attempts,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Job:
        job = cls.__new__(cls)
        job.id = data["id"]
        job.status = JobStatus(data["status"])
        job.payload = data.get("payload") or {}
        job.should_fail = bool(data.get("should_fail", False))
        job.work_seconds = data.get("work_seconds")
        job.result = data.get("result")
        job.error = data.get("error")
        job.attempts = int(data.get("attempts", 0))
        job.created_at = datetime.fromisoformat(data["created_at"])
        job.updated_at = datetime.fromisoformat(data["updated_at"])
        expires = data.get("expires_at")
        job.expires_at = datetime.fromisoformat(expires) if expires else None
        return job

    def to_response(self) -> JobResponse:
        return JobResponse(
            id=self.id,
            status=self.status,
            payload=self.payload,
            result=self.result,
            error=self.error,
            attempts=self.attempts,
            created_at=self.created_at,
            updated_at=self.updated_at,
            expires_at=self.expires_at,
        )
