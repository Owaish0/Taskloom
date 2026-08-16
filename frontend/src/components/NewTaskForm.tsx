import { useState } from "react";
import { createFailingTask, createFlakyTask, createSleepTask, createSummarizeTask } from "../api";

type TaskKind = "sleep" | "fail" | "flaky" | "summarize";

const SAMPLE_TEXT =
  "The Roman Empire was one of the most influential civilizations in world history, " +
  "spanning over a thousand years from its founding to its eventual fall. At its peak, " +
  "it controlled territory across Europe, North Africa, and the Middle East, connected " +
  "by an extensive network of roads and governed by a sophisticated legal system that " +
  "still influences modern law today.";

export default function NewTaskForm() {
  const [kind, setKind] = useState<TaskKind>("sleep");
  const [duration, setDuration] = useState(3);
  const [failRate, setFailRate] = useState(0.5);
  const [text, setText] = useState(SAMPLE_TEXT);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      if (kind === "sleep") {
        await createSleepTask(duration);
      } else if (kind === "fail") {
        await createFailingTask();
      } else if (kind === "flaky") {
        await createFlakyTask(failRate);
      } else {
        await createSummarizeTask(text);
      }
      // No local refresh needed — the new task arrives via the SSE stream.
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create task");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
    >
      <div className="flex flex-col gap-1">
        <label htmlFor="kind" className="text-sm font-medium text-slate-600">
          Task type
        </label>
        <select
          id="kind"
          value={kind}
          onChange={(e) => setKind(e.target.value as TaskKind)}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-slate-500 focus:outline-none"
        >
          <option value="sleep">sleep</option>
          <option value="fail">fail (demo retries → DLQ)</option>
          <option value="flaky">flaky (demo rate limit + circuit breaker)</option>
          <option value="summarize">summarize (real Gemini API call)</option>
        </select>
      </div>

      {kind === "sleep" && (
        <div className="flex flex-col gap-1">
          <label htmlFor="duration" className="text-sm font-medium text-slate-600">
            Sleep duration (seconds)
          </label>
          <input
            id="duration"
            type="number"
            min={1}
            step={1}
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value))}
            className="w-32 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-slate-500 focus:outline-none"
          />
        </div>
      )}

      {kind === "flaky" && (
        <div className="flex flex-col gap-1">
          <label htmlFor="failRate" className="text-sm font-medium text-slate-600">
            Simulated fail rate (0–1)
          </label>
          <input
            id="failRate"
            type="number"
            min={0}
            max={1}
            step={0.1}
            value={failRate}
            onChange={(e) => setFailRate(Number(e.target.value))}
            className="w-32 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-slate-500 focus:outline-none"
          />
        </div>
      )}

      {kind === "summarize" && (
        <div className="flex flex-1 min-w-[16rem] flex-col gap-1">
          <label htmlFor="text" className="text-sm font-medium text-slate-600">
            Text to summarize
          </label>
          <textarea
            id="text"
            rows={2}
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-slate-500 focus:outline-none"
          />
        </div>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
      >
        {submitting ? "Submitting…" : "Submit task"}
      </button>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </form>
  );
}
