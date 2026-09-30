"""Shared runtime dependencies (API process + Celery workers)."""

from __future__ import annotations

from app.config import Settings, load_settings
from app.redis_client import create_redis
from app.store import JobStore

_settings: Settings | None = None
_store: JobStore | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def get_store() -> JobStore:
    global _store
    if _store is None:
        cfg = get_settings()
        _store = JobStore(create_redis(cfg), config=cfg)
    return _store


def set_store(store: JobStore | None) -> None:
    """Override store (tests)."""
    global _store
    _store = store


def set_settings(settings: Settings | None) -> None:
    """Override settings (tests)."""
    global _settings
    _settings = settings


def reset() -> None:
    set_store(None)
    set_settings(None)
