from __future__ import annotations

import time

from redis.asyncio import Redis

from taskloom.config import settings

RATE_LIMIT_KEY = "ratelimit:external_api"

# Runs entirely inside Redis, atomically, in one round trip — this is what
# makes the bucket safe to share across every worker replica without any
# app-level locking. Lua numbers get truncated to integers when a script
# returns them directly (Redis's Lua-to-RESP conversion), so the token
# count is returned as a string via tostring() to preserve fractional
# tokens between refills.
_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_sec = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local bucket = redis.call('HMGET', key, 'tokens', 'updated_at')
local tokens = tonumber(bucket[1])
local updated_at = tonumber(bucket[2])

if tokens == nil then
    tokens = capacity
    updated_at = now
end

local elapsed = now - updated_at
if elapsed < 0 then elapsed = 0 end
tokens = math.min(capacity, tokens + elapsed * refill_per_sec)

local allowed = 0
if tokens >= requested then
    tokens = tokens - requested
    allowed = 1
end

redis.call('HSET', key, 'tokens', tokens, 'updated_at', now)
redis.call('EXPIRE', key, 3600)

return {allowed, tostring(tokens)}
"""

class RateLimitedError(Exception):
    """Raised by a task handler when the shared token bucket is empty.
    Not a distinct failure mode as far as the worker is concerned — it
    flows through the normal retry/backoff path like any other exception."""


async def try_acquire(redis: Redis, tokens: int = 1) -> tuple[bool, float]:
    """Attempt to take `tokens` from the shared bucket. Returns
    (allowed, tokens_remaining_after_the_attempt).

    register_script() does no I/O (it's just a callable object bound to
    this redis client), so there's no benefit to caching it — and caching
    across different client instances would be an actual bug."""
    script = redis.register_script(_TOKEN_BUCKET_LUA)
    allowed, remaining = await script(
        keys=[RATE_LIMIT_KEY],
        args=[
            settings.rate_limit_capacity,
            settings.rate_limit_refill_per_sec,
            time.time(),
            tokens,
        ],
    )
    return bool(int(allowed)), float(remaining)


async def current_tokens(redis: Redis) -> float:
    """Read-only view of the bucket's current token count, for the status
    endpoint. Computed the same way the Lua script would but without
    mutating state — a status check shouldn't itself consume a token."""
    tokens_raw, updated_at_raw = await redis.hmget(RATE_LIMIT_KEY, "tokens", "updated_at")
    if tokens_raw is None:
        return float(settings.rate_limit_capacity)
    tokens = float(tokens_raw)
    updated_at = float(updated_at_raw)
    elapsed = max(0.0, time.time() - updated_at)
    return min(
        float(settings.rate_limit_capacity), tokens + elapsed * settings.rate_limit_refill_per_sec
    )
