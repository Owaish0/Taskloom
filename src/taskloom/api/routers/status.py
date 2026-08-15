from fastapi import APIRouter, Request

from taskloom.circuitbreaker import get_status as get_circuit_status
from taskloom.config import settings
from taskloom.ratelimit import current_tokens

router = APIRouter(prefix="/api/v1", tags=["status"])


@router.get("/status")
async def system_status(request: Request) -> dict:
    """Live view of the shared rate limiter and circuit breaker guarding
    the simulated external service (the `flaky` task type) — not
    per-task state, but the state of the protection mechanisms themselves,
    shared across every worker replica via Redis."""
    redis = request.app.state.redis
    circuit = await get_circuit_status(redis)
    tokens = await current_tokens(redis)
    return {
        "circuit_breaker": circuit,
        "rate_limiter": {
            "tokens_available": round(tokens, 2),
            "capacity": settings.rate_limit_capacity,
            "refill_per_sec": settings.rate_limit_refill_per_sec,
        },
    }
