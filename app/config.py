"""Runtime configuration — all values come from environment / .env files."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load nearest .env (local). Docker Compose injects env via env_file instead.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_FILE, override=False)


class ConfigError(RuntimeError):
    """Raised when a required environment variable is missing or invalid."""


def _require(name: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise ConfigError(
            f"Missing required environment variable {name}. "
            f"Copy .env.example to .env and set all values."
        )
    return value.strip()


def _require_int(name: str) -> int:
    raw = _require(name)
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _require_float(name: str) -> float:
    raw = _require(name)
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a float, got {raw!r}") from exc


def _require_bool(name: str) -> bool:
    raw = _require(name).lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean, got {raw!r}")


@dataclass(frozen=True)
class Settings:
    max_retries: int
    base_backoff_seconds: float
    retry_jitter_ratio: float
    mock_work_seconds: float
    redis_url: str
    celery_broker_url: str
    redis_key_prefix: str
    idempotency_ttl_seconds: int
    celery_concurrency: int
    celery_queue: str
    celery_prefetch_multiplier: int
    celery_task_always_eager: bool
    job_ttl_seconds: int
    stuck_running_seconds: int
    reaper_interval_seconds: int
    purge_interval_seconds: int
    job_lock_timeout_seconds: int
    job_lock_blocking_timeout_seconds: int
    dlq_list_default_limit: int
    api_host: str
    api_port: int
    log_level: str

    def job_key(self, job_id: str) -> str:
        return f"{self.redis_key_prefix}:job:{job_id}"

    def job_ids_key(self) -> str:
        return f"{self.redis_key_prefix}:ids"

    def idempotency_key(self, client_key: str) -> str:
        return f"{self.redis_key_prefix}:idempotency:{client_key}"

    def dlq_key(self) -> str:
        return f"{self.redis_key_prefix}:dlq"


def load_settings() -> Settings:
    """Build Settings exclusively from environment variables."""
    return Settings(
        max_retries=_require_int("MAX_RETRIES"),
        base_backoff_seconds=_require_float("BASE_BACKOFF_SECONDS"),
        retry_jitter_ratio=_require_float("RETRY_JITTER_RATIO"),
        mock_work_seconds=_require_float("MOCK_WORK_SECONDS"),
        redis_url=_require("REDIS_URL"),
        celery_broker_url=_require("CELERY_BROKER_URL"),
        redis_key_prefix=_require("REDIS_KEY_PREFIX"),
        idempotency_ttl_seconds=_require_int("IDEMPOTENCY_TTL_SECONDS"),
        celery_concurrency=_require_int("CELERY_CONCURRENCY"),
        celery_queue=_require("CELERY_QUEUE"),
        celery_prefetch_multiplier=_require_int("CELERY_PREFETCH_MULTIPLIER"),
        celery_task_always_eager=_require_bool("CELERY_TASK_ALWAYS_EAGER"),
        job_ttl_seconds=_require_int("JOB_TTL_SECONDS"),
        stuck_running_seconds=_require_int("STUCK_RUNNING_SECONDS"),
        reaper_interval_seconds=_require_int("REAPER_INTERVAL_SECONDS"),
        purge_interval_seconds=_require_int("PURGE_INTERVAL_SECONDS"),
        job_lock_timeout_seconds=_require_int("JOB_LOCK_TIMEOUT_SECONDS"),
        job_lock_blocking_timeout_seconds=_require_int(
            "JOB_LOCK_BLOCKING_TIMEOUT_SECONDS"
        ),
        dlq_list_default_limit=_require_int("DLQ_LIST_DEFAULT_LIMIT"),
        api_host=_require("API_HOST"),
        api_port=_require_int("API_PORT"),
        log_level=_require("LOG_LEVEL"),
    )


settings = load_settings()
