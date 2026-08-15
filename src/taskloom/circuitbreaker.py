from __future__ import annotations

import time
from enum import StrEnum

from redis.asyncio import Redis

from taskloom.config import settings

CIRCUIT_KEY = "circuit:external_api"


class CircuitState(StrEnum):
    CLOSED = "closed"  # normal operation
    OPEN = "open"  # short-circuiting calls after too many recent failures
    HALF_OPEN = "half_open"  # cooldown elapsed; exactly one probe call in flight


class CircuitOpenError(Exception):
    """Raised by a task handler when the breaker is open (or the one
    HALF_OPEN probe slot is already taken) and the call was short-circuited
    without ever reaching the simulated external service. Flows through the
    normal retry/backoff path like any other handler failure."""


# check_allowed is the only place OPEN -> HALF_OPEN happens, and it grants
# that transitioning call as *the* probe in the same atomic step — so
# "state is HALF_OPEN" always means exactly one probe is currently in
# flight, with no separate lock key needed. Every other call arriving
# while HALF_OPEN is rejected until that probe's outcome (record_success/
# record_failure) resolves it.
_CHECK_ALLOWED_LUA = """
local key = KEYS[1]
local cooldown = tonumber(ARGV[1])
local now = tonumber(ARGV[2])

local data = redis.call('HMGET', key, 'state', 'opened_at')
local state = data[1]
local opened_at = tonumber(data[2])

if state == false or state == 'closed' then
    return {1, 'closed'}
end

if state == 'open' then
    if opened_at ~= nil and (now - opened_at) >= cooldown then
        redis.call('HSET', key, 'state', 'half_open')
        return {1, 'half_open'}
    end
    return {0, 'open'}
end

-- half_open: a probe is already in flight, reject everything else
return {0, 'half_open'}
"""

_RECORD_SUCCESS_LUA = """
local key = KEYS[1]
redis.call('HSET', key, 'state', 'closed', 'failure_count', 0)
redis.call('EXPIRE', key, 3600)
return 1
"""

_RECORD_FAILURE_LUA = """
local key = KEYS[1]
local threshold = tonumber(ARGV[1])
local now = tonumber(ARGV[2])

local data = redis.call('HMGET', key, 'state', 'failure_count')
local state = data[1]
local failure_count = tonumber(data[2]) or 0

if state == 'half_open' then
    -- the probe failed: back to open, cooldown restarts
    redis.call('HSET', key, 'state', 'open', 'opened_at', now, 'failure_count', threshold)
    redis.call('EXPIRE', key, 3600)
    return 'open'
end

failure_count = failure_count + 1
if failure_count >= threshold then
    redis.call('HSET', key, 'state', 'open', 'opened_at', now, 'failure_count', failure_count)
    redis.call('EXPIRE', key, 3600)
    return 'open'
end

redis.call('HSET', key, 'state', 'closed', 'failure_count', failure_count)
redis.call('EXPIRE', key, 3600)
return 'closed'
"""

async def check_allowed(redis: Redis) -> tuple[bool, CircuitState]:
    """Whether a call should be allowed through right now. May itself
    transition OPEN -> HALF_OPEN (granting this call as the probe) if the
    cooldown has elapsed — see the Lua script's docstring above.

    register_script() does no I/O (it's just a callable object bound to
    this redis client), so there's no benefit to caching it — and caching
    across different client instances would be an actual bug."""
    script = redis.register_script(_CHECK_ALLOWED_LUA)
    allowed, state = await script(
        keys=[CIRCUIT_KEY], args=[settings.circuit_cooldown_seconds, time.time()]
    )
    return bool(int(allowed)), CircuitState(state)


async def record_success(redis: Redis) -> None:
    script = redis.register_script(_RECORD_SUCCESS_LUA)
    await script(keys=[CIRCUIT_KEY])


async def record_failure(redis: Redis) -> CircuitState:
    script = redis.register_script(_RECORD_FAILURE_LUA)
    state = await script(keys=[CIRCUIT_KEY], args=[settings.circuit_failure_threshold, time.time()])
    return CircuitState(state)


async def get_status(redis: Redis) -> dict:
    """Read-only status for the /status endpoint. Doesn't mutate state —
    if OPEN and the cooldown has already elapsed, this reports that as
    `cooldown_remaining_seconds: 0` rather than actually performing the
    OPEN -> HALF_OPEN transition, since only a real call attempt should
    consume the probe slot."""
    data = await redis.hgetall(CIRCUIT_KEY)
    state = data.get("state", CircuitState.CLOSED.value)
    failure_count = int(data.get("failure_count", 0))
    opened_at = float(data["opened_at"]) if "opened_at" in data else None

    cooldown_remaining = None
    if state == CircuitState.OPEN.value and opened_at is not None:
        cooldown_remaining = max(0.0, settings.circuit_cooldown_seconds - (time.time() - opened_at))

    return {
        "state": state,
        "failure_count": failure_count,
        "failure_threshold": settings.circuit_failure_threshold,
        "cooldown_remaining_seconds": cooldown_remaining,
    }
