import asyncio

import fakeredis.aioredis
import pytest

from taskloom.circuitbreaker import CircuitState, check_allowed, get_status, record_failure, record_success


@pytest.fixture
async def redis():
    server = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield server
    await server.aclose()


async def test_starts_closed_and_allows(redis):
    allowed, state = await check_allowed(redis)
    assert allowed is True
    assert state == CircuitState.CLOSED


async def test_opens_after_reaching_failure_threshold(redis, monkeypatch):
    monkeypatch.setattr("taskloom.config.settings.circuit_failure_threshold", 3)

    assert await record_failure(redis) == CircuitState.CLOSED
    assert await record_failure(redis) == CircuitState.CLOSED
    assert await record_failure(redis) == CircuitState.OPEN

    allowed, state = await check_allowed(redis)
    assert allowed is False
    assert state == CircuitState.OPEN


async def test_success_resets_failure_count(redis, monkeypatch):
    monkeypatch.setattr("taskloom.config.settings.circuit_failure_threshold", 3)

    await record_failure(redis)
    await record_failure(redis)
    await record_success(redis)

    status = await get_status(redis)
    assert status["state"] == "closed"
    assert status["failure_count"] == 0


async def test_transitions_to_half_open_after_cooldown_and_grants_probe(redis, monkeypatch):
    monkeypatch.setattr("taskloom.config.settings.circuit_failure_threshold", 1)
    monkeypatch.setattr("taskloom.config.settings.circuit_cooldown_seconds", 0.05)

    await record_failure(redis)  # trips open immediately

    allowed, state = await check_allowed(redis)
    assert allowed is False
    assert state == CircuitState.OPEN

    await asyncio.sleep(0.06)

    allowed, state = await check_allowed(redis)
    assert allowed is True
    assert state == CircuitState.HALF_OPEN


async def test_half_open_rejects_a_second_concurrent_call(redis, monkeypatch):
    monkeypatch.setattr("taskloom.config.settings.circuit_failure_threshold", 1)
    monkeypatch.setattr("taskloom.config.settings.circuit_cooldown_seconds", 0.0)
    await record_failure(redis)

    allowed_first, state_first = await check_allowed(redis)  # becomes the probe
    allowed_second, state_second = await check_allowed(redis)  # arrives while probe in flight

    assert allowed_first is True
    assert state_first == CircuitState.HALF_OPEN
    assert allowed_second is False
    assert state_second == CircuitState.HALF_OPEN


async def test_successful_probe_closes_the_circuit(redis, monkeypatch):
    monkeypatch.setattr("taskloom.config.settings.circuit_failure_threshold", 1)
    monkeypatch.setattr("taskloom.config.settings.circuit_cooldown_seconds", 0.0)
    await record_failure(redis)
    await check_allowed(redis)  # half_open, probe granted

    await record_success(redis)

    allowed, state = await check_allowed(redis)
    assert allowed is True
    assert state == CircuitState.CLOSED


async def test_failed_probe_reopens_the_circuit(redis, monkeypatch):
    monkeypatch.setattr("taskloom.config.settings.circuit_failure_threshold", 1)
    monkeypatch.setattr("taskloom.config.settings.circuit_cooldown_seconds", 0.0)
    await record_failure(redis)
    await check_allowed(redis)  # half_open, probe granted

    # Cooldown restarts on a failed probe — give it a real window here so
    # the immediate check below doesn't just see the 0.0 cooldown already
    # elapsed and grant a new probe right away (which would be correct
    # behavior for cooldown=0, just not what this test is checking).
    monkeypatch.setattr("taskloom.config.settings.circuit_cooldown_seconds", 10.0)
    state = await record_failure(redis)

    assert state == CircuitState.OPEN
    allowed, _ = await check_allowed(redis)
    assert allowed is False


async def test_get_status_reports_cooldown_remaining_while_open(redis, monkeypatch):
    monkeypatch.setattr("taskloom.config.settings.circuit_failure_threshold", 1)
    monkeypatch.setattr("taskloom.config.settings.circuit_cooldown_seconds", 10.0)
    await record_failure(redis)

    status = await get_status(redis)

    assert status["state"] == "open"
    assert status["cooldown_remaining_seconds"] > 9
