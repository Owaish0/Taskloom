import asyncio

import fakeredis.aioredis
import pytest

from taskloom.ratelimit import current_tokens, try_acquire


@pytest.fixture
async def redis():
    server = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield server
    await server.aclose()


async def test_try_acquire_allows_up_to_capacity_then_blocks(redis, monkeypatch):
    monkeypatch.setattr("taskloom.config.settings.rate_limit_capacity", 3)
    monkeypatch.setattr("taskloom.config.settings.rate_limit_refill_per_sec", 0.0)

    for _ in range(3):
        allowed, _ = await try_acquire(redis)
        assert allowed is True

    allowed, remaining = await try_acquire(redis)
    assert allowed is False
    assert remaining == 0


async def test_try_acquire_refills_over_time(redis, monkeypatch):
    monkeypatch.setattr("taskloom.config.settings.rate_limit_capacity", 3)
    monkeypatch.setattr("taskloom.config.settings.rate_limit_refill_per_sec", 0.0)

    for _ in range(3):
        await try_acquire(redis)
    allowed, _ = await try_acquire(redis)
    assert allowed is False

    # Now let it refill quickly rather than waiting on the (still zero)
    # rate — a large refill rate over a short real sleep is far more
    # reliable in a test than trying to time a slow refill precisely.
    monkeypatch.setattr("taskloom.config.settings.rate_limit_refill_per_sec", 100.0)
    await asyncio.sleep(0.05)  # 100 tokens/sec * 0.05s far exceeds capacity

    allowed, _ = await try_acquire(redis)
    assert allowed is True


async def test_current_tokens_starts_at_capacity_for_unused_bucket(redis, monkeypatch):
    monkeypatch.setattr("taskloom.config.settings.rate_limit_capacity", 5)
    assert await current_tokens(redis) == 5


async def test_current_tokens_is_read_only(redis, monkeypatch):
    monkeypatch.setattr("taskloom.config.settings.rate_limit_capacity", 3)
    monkeypatch.setattr("taskloom.config.settings.rate_limit_refill_per_sec", 0.0)

    await try_acquire(redis)  # 2 tokens left
    first_read = await current_tokens(redis)
    second_read = await current_tokens(redis)

    assert first_read == second_read == 2
