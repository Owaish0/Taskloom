from __future__ import annotations

import asyncio
import random
from typing import Any, Awaitable, Callable

from redis.asyncio import Redis

from taskloom.circuitbreaker import CircuitOpenError, check_allowed, record_failure, record_success
from taskloom.config import settings
from taskloom.ratelimit import RateLimitedError, try_acquire

HandlerFn = Callable[[Redis, dict[str, Any]], Awaitable[dict[str, Any]]]


async def sleep_handler(redis: Redis, payload: dict[str, Any]) -> dict[str, Any]:
    duration = float(payload["duration"])
    await asyncio.sleep(duration)
    return {"slept_for": duration}


async def fail_handler(redis: Redis, payload: dict[str, Any]) -> dict[str, Any]:
    """Always raises. Exists to exercise (and demo) the retry / dead-letter
    queue path without needing a real flaky dependency."""
    raise RuntimeError(payload.get("message", "task configured to always fail"))


async def flaky_handler(redis: Redis, payload: dict[str, Any]) -> dict[str, Any]:
    """Simulates calling an unreliable, rate-limited external service —
    stands in for Phase 5's real LLM call so the rate limiter and circuit
    breaker (Phase 4) have something to actually protect and demo against.

    Order matters: check the breaker before spending a rate-limit token —
    there's no point drawing down the shared token bucket for a call we're
    about to short-circuit anyway.
    """
    allowed, state = await check_allowed(redis)
    if not allowed:
        raise CircuitOpenError(f"circuit breaker is {state.value}, short-circuiting call")

    acquired, remaining = await try_acquire(redis)
    if not acquired:
        raise RateLimitedError("rate limit exceeded, no tokens available")

    fail_rate = float(payload.get("fail_rate", settings.flaky_default_fail_rate))
    if random.random() < fail_rate:
        new_state = await record_failure(redis)
        raise RuntimeError(f"simulated external service error (breaker now {new_state.value})")

    await record_success(redis)
    return {"tokens_remaining": remaining}


HANDLERS: dict[str, HandlerFn] = {
    "sleep": sleep_handler,
    "fail": fail_handler,
    "flaky": flaky_handler,
}
