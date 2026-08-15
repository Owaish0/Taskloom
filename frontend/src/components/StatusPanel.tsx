import { useEffect, useState } from "react";
import { getStatus } from "../api";
import type { SystemStatus } from "../types";

const POLL_INTERVAL_MS = 1000;

const CIRCUIT_STYLES: Record<string, string> = {
  closed: "bg-emerald-100 text-emerald-800",
  half_open: "bg-amber-100 text-amber-800",
  open: "bg-red-100 text-red-800",
};

export default function StatusPanel() {
  const [status, setStatus] = useState<SystemStatus | null>(null);

  useEffect(() => {
    // Deliberately polled rather than pushed over SSE — this is small,
    // cheap, non-task-lifecycle state, not worth a second pub/sub channel.
    const refresh = () => getStatus().then(setStatus).catch(() => {});
    refresh();
    const interval = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  if (status === null) {
    return null;
  }

  const { circuit_breaker, rate_limiter } = status;
  const tokenPct = Math.round((rate_limiter.tokens_available / rate_limiter.capacity) * 100);

  return (
    <div className="mt-6 flex flex-wrap gap-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm text-sm">
      <div className="flex items-center gap-2">
        <span className="font-medium text-slate-600">Circuit breaker:</span>
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${CIRCUIT_STYLES[circuit_breaker.state]}`}
        >
          {circuit_breaker.state}
        </span>
        <span className="text-slate-500">
          {circuit_breaker.failure_count}/{circuit_breaker.failure_threshold} failures
          {circuit_breaker.cooldown_remaining_seconds !== null &&
            circuit_breaker.cooldown_remaining_seconds > 0 &&
            ` · retry in ${Math.ceil(circuit_breaker.cooldown_remaining_seconds)}s`}
        </span>
      </div>

      <div className="flex items-center gap-2">
        <span className="font-medium text-slate-600">Rate limiter:</span>
        <div className="h-2 w-24 overflow-hidden rounded-full bg-slate-200">
          <div
            className="h-full bg-blue-500 transition-all"
            style={{ width: `${tokenPct}%` }}
          />
        </div>
        <span className="text-slate-500">
          {rate_limiter.tokens_available}/{rate_limiter.capacity} tokens
        </span>
      </div>
    </div>
  );
}
