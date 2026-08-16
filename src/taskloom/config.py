from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://localhost:6379/0"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173"
    worker_poll_timeout: int = 5

    # Retry / dead-letter queue (Phase 2)
    default_max_attempts: int = 3
    retry_backoff_base: float = 2.0
    retry_poll_interval: float = 1.0

    # Rate limiting / circuit breaker (Phase 4) — sized for demoability, not
    # production realism: small enough to trip both from the dashboard.
    rate_limit_capacity: int = 3
    rate_limit_refill_per_sec: float = 0.5
    circuit_failure_threshold: int = 3
    circuit_cooldown_seconds: float = 10.0
    flaky_default_fail_rate: float = 0.5

    # Real LLM call (Phase 5) — what Phase 4's rate limiter/circuit breaker
    # were actually built to protect. Gemini Flash by default: Google AI
    # Studio's free tier needs no billing setup, unlike OpenAI/Anthropic.
    google_api_key: str | None = None
    summarize_model: str = "gemini-flash-latest"
    summarize_max_tokens: int = 1024
    summarize_max_input_chars: int = 50_000

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
