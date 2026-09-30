"""Redis connection helpers (supports redis:// and rediss:// for DO managed DB)."""

from __future__ import annotations

import ssl

from redis import Redis

from app.config import Settings, settings


def create_redis(config: Settings | None = None) -> Redis:
    """Create a Redis/Valkey client. decode_responses=True keeps values as str/JSON."""
    cfg = config or settings
    kwargs: dict = {"decode_responses": True}
    # DigitalOcean managed Valkey/Redis uses TLS (rediss://).
    if cfg.redis_url.startswith("rediss://"):
        kwargs["ssl_cert_reqs"] = ssl.CERT_REQUIRED
    return Redis.from_url(cfg.redis_url, **kwargs)
