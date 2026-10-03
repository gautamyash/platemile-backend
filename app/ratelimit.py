"""Small fixed-window rate limiter on Redis. Fails open if Redis is down (logged), so an outage never locks users out."""

import logging

import redis.asyncio as redis
from fastapi import Depends, HTTPException, Request, status

from app.config import settings

log = logging.getLogger("ratelimit")
_client: redis.Redis | None = None


def _redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.redis_url, socket_timeout=1, socket_connect_timeout=1)
    return _client


def limit(name: str, count: int, seconds: int):
    async def dep(request: Request) -> None:
        if not settings.rate_limit_enabled:
            return
        who = request.client.host if request.client else "unknown"
        auth = request.headers.get("authorization", "")
        if auth:  # per-account when signed in, so shared Wi-Fi/NAT does not trip it
            who = auth[-24:]
        key = f"rl:{name}:{who}"
        try:
            n = await _redis().incr(key)
            if n == 1:
                await _redis().expire(key, seconds)
        except Exception as exc:  # noqa: BLE001
            log.warning("rate limiter unavailable: %s", type(exc).__name__)
            return
        if n > count:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests. Please wait a moment.")

    return Depends(dep)
