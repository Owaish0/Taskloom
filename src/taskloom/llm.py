from __future__ import annotations

from google import genai

from taskloom.config import settings

_client: genai.Client | None = None


def get_gemini_client() -> genai.Client:
    """Lazy singleton, same pattern as redis_client.get_redis() — constructed
    once, reused across every call in this process. Resolves credentials
    from GOOGLE_API_KEY (via settings/.env); never hardcode a key. Uses the
    Gemini Developer API (Google AI Studio), not Vertex AI."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.google_api_key)
    return _client


def close_gemini_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
