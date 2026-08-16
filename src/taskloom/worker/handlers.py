from __future__ import annotations

import asyncio
import random
from typing import Any, Awaitable, Callable

from google.genai import errors as genai_errors
from google.genai import types as genai_types
from redis.asyncio import Redis

from taskloom.circuitbreaker import CircuitOpenError, check_allowed, record_failure, record_success
from taskloom.config import settings
from taskloom.llm import get_gemini_client
from taskloom.ratelimit import RateLimitedError, try_acquire

# Finish reasons that mean the model declined to answer rather than an
# infrastructure failure — still a real failure, but not a "try harder"
# transient one. Content-safety and copyright-adjacent holds, mainly.
_DECLINED_FINISH_REASONS = {
    genai_types.FinishReason.SAFETY,
    genai_types.FinishReason.PROHIBITED_CONTENT,
    genai_types.FinishReason.BLOCKLIST,
    genai_types.FinishReason.SPII,
    genai_types.FinishReason.RECITATION,
}

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


async def summarize_handler(redis: Redis, payload: dict[str, Any]) -> dict[str, Any]:
    """Real external API call: summarizes text via the Gemini API. This is
    what Phase 4's rate limiter and circuit breaker were actually built to
    protect — the same checks flaky_handler simulated now guard a real,
    rate-limited third-party call. Provider failures raise like any other
    handler failure and flow through the normal retry/backoff/DLQ path from
    Phase 2, rather than needing bespoke handling here.
    """
    allowed, state = await check_allowed(redis)
    if not allowed:
        raise CircuitOpenError(f"circuit breaker is {state.value}, short-circuiting call")

    acquired, remaining = await try_acquire(redis)
    if not acquired:
        raise RateLimitedError("rate limit exceeded, no tokens available")

    text = str(payload["text"])[: settings.summarize_max_input_chars]
    client = get_gemini_client()

    try:
        response = await client.aio.models.generate_content(
            model=settings.summarize_model,
            contents=text,
            config=genai_types.GenerateContentConfig(
                system_instruction="Summarize the following text in 2-3 concise sentences.",
                max_output_tokens=settings.summarize_max_tokens,
                # Newer Gemini models think by default, and thinking tokens
                # draw from the same max_output_tokens budget as the visible
                # response — a low budget can be entirely consumed by
                # thinking, leaving an empty response with finish_reason
                # MAX_TOKENS. Not needed for a task this simple; disable it.
                thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
            ),
        )
    except genai_errors.APIError as exc:
        # Covers both ClientError (4xx, incl. 429 rate limits) and
        # ServerError (5xx) — record against the breaker the same as a
        # simulated flaky failure would.
        await record_failure(redis)
        raise RuntimeError(f"Gemini API call failed: {exc}") from exc

    finish_reason = response.candidates[0].finish_reason if response.candidates else None
    if finish_reason in _DECLINED_FINISH_REASONS:
        # A content hold isn't a transient failure, but it still counts
        # against the breaker the same way — the underlying call did fail.
        await record_failure(redis)
        raise RuntimeError(f"Gemini declined to summarize this text ({finish_reason.value})")

    await record_success(redis)
    return {"summary": response.text, "tokens_remaining": remaining}


HANDLERS: dict[str, HandlerFn] = {
    "sleep": sleep_handler,
    "fail": fail_handler,
    "flaky": flaky_handler,
    "summarize": summarize_handler,
}
