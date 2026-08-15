export type TaskStatus = "pending" | "active" | "completed" | "retry_scheduled" | "failed";

export interface TaskRecord {
  id: string;
  type: string;
  status: TaskStatus;
  payload: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
  attempts: number;
  max_attempts: number;
  created_at: string;
  updated_at: string;
}

export type CircuitBreakerState = "closed" | "open" | "half_open";

export interface SystemStatus {
  circuit_breaker: {
    state: CircuitBreakerState;
    failure_count: number;
    failure_threshold: number;
    cooldown_remaining_seconds: number | null;
  };
  rate_limiter: {
    tokens_available: number;
    capacity: number;
    refill_per_sec: number;
  };
}
