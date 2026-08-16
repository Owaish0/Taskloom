import fakeredis.aioredis
import pytest
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from taskloom.circuitbreaker import record_failure
from taskloom.models import TaskStatus
from taskloom.queue import create_task, get_task
from taskloom.worker.main import process_task


@pytest.fixture
async def redis():
    server = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield server
    await server.aclose()


class _FakeCandidate:
    def __init__(self, finish_reason=genai_types.FinishReason.STOP):
        self.finish_reason = finish_reason


class _FakeResponse:
    def __init__(self, text: str = "A short summary.", finish_reason=genai_types.FinishReason.STOP):
        self.text = text
        self.candidates = [_FakeCandidate(finish_reason)]


class _FakeModels:
    def __init__(self, response=None, exc: Exception | None = None):
        self._response = response
        self._exc = exc

    async def generate_content(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return self._response


class _FakeAio:
    def __init__(self, response=None, exc: Exception | None = None):
        self.models = _FakeModels(response, exc)


class _FakeGeminiClient:
    def __init__(self, response=None, exc: Exception | None = None):
        self.aio = _FakeAio(response, exc)


def _server_error() -> genai_errors.ServerError:
    return genai_errors.ServerError(code=503, response_json={"error": {"message": "unavailable"}})


def _rate_limit_error() -> genai_errors.ClientError:
    return genai_errors.ClientError(code=429, response_json={"error": {"message": "rate limited"}})


async def test_summarize_task_succeeds(redis, monkeypatch):
    fake_client = _FakeGeminiClient(response=_FakeResponse("Rome ruled for centuries."))
    monkeypatch.setattr("taskloom.worker.handlers.get_gemini_client", lambda: fake_client)

    record = await create_task(redis, "summarize", {"text": "The history of Rome..."})
    await process_task(redis, record.id)

    fetched = await get_task(redis, record.id)
    assert fetched.status == TaskStatus.COMPLETED
    assert fetched.result["summary"] == "Rome ruled for centuries."


async def test_summarize_short_circuits_when_breaker_open(redis, monkeypatch):
    monkeypatch.setattr("taskloom.config.settings.circuit_failure_threshold", 1)
    await record_failure(redis)  # trips the breaker before the task ever runs

    fake_client = _FakeGeminiClient(response=_FakeResponse())
    monkeypatch.setattr("taskloom.worker.handlers.get_gemini_client", lambda: fake_client)

    record = await create_task(redis, "summarize", {"text": "..."}, max_attempts=1)
    await process_task(redis, record.id)

    fetched = await get_task(redis, record.id)
    assert fetched.status == TaskStatus.FAILED
    assert "circuit breaker" in fetched.error


async def test_summarize_fails_when_rate_limited(redis, monkeypatch):
    monkeypatch.setattr("taskloom.config.settings.rate_limit_capacity", 0)

    fake_client = _FakeGeminiClient(response=_FakeResponse())
    monkeypatch.setattr("taskloom.worker.handlers.get_gemini_client", lambda: fake_client)

    record = await create_task(redis, "summarize", {"text": "..."}, max_attempts=1)
    await process_task(redis, record.id)

    fetched = await get_task(redis, record.id)
    assert fetched.status == TaskStatus.FAILED
    assert "rate limit" in fetched.error


async def test_summarize_api_error_trips_breaker(redis, monkeypatch):
    monkeypatch.setattr("taskloom.config.settings.rate_limit_capacity", 5)
    monkeypatch.setattr("taskloom.config.settings.circuit_failure_threshold", 1)

    fake_client = _FakeGeminiClient(exc=_server_error())
    monkeypatch.setattr("taskloom.worker.handlers.get_gemini_client", lambda: fake_client)

    record = await create_task(redis, "summarize", {"text": "..."}, max_attempts=1)
    await process_task(redis, record.id)

    fetched = await get_task(redis, record.id)
    assert fetched.status == TaskStatus.FAILED
    assert "Gemini API call failed" in fetched.error

    from taskloom.circuitbreaker import check_allowed

    allowed, _ = await check_allowed(redis)
    assert allowed is False  # confirms the breaker actually tripped


async def test_summarize_rate_limit_error_from_api_is_retryable_failure(redis, monkeypatch):
    monkeypatch.setattr("taskloom.config.settings.rate_limit_capacity", 5)

    fake_client = _FakeGeminiClient(exc=_rate_limit_error())
    monkeypatch.setattr("taskloom.worker.handlers.get_gemini_client", lambda: fake_client)

    record = await create_task(redis, "summarize", {"text": "..."}, max_attempts=3)
    await process_task(redis, record.id)

    fetched = await get_task(redis, record.id)
    assert fetched.status == TaskStatus.RETRY_SCHEDULED
    assert fetched.attempts == 1


async def test_summarize_safety_decline_counts_as_failure(redis, monkeypatch):
    monkeypatch.setattr("taskloom.config.settings.rate_limit_capacity", 5)

    fake_client = _FakeGeminiClient(
        response=_FakeResponse(text="", finish_reason=genai_types.FinishReason.SAFETY)
    )
    monkeypatch.setattr("taskloom.worker.handlers.get_gemini_client", lambda: fake_client)

    record = await create_task(redis, "summarize", {"text": "..."}, max_attempts=1)
    await process_task(redis, record.id)

    fetched = await get_task(redis, record.id)
    assert fetched.status == TaskStatus.FAILED
    assert "declined" in fetched.error
