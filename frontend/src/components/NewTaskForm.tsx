import { useState } from "react";
import { createFailingTask, createSleepTask } from "../api";

interface Props {
  onCreated: () => void;
}

type TaskKind = "sleep" | "fail";

export default function NewTaskForm({ onCreated }: Props) {
  const [kind, setKind] = useState<TaskKind>("sleep");
  const [duration, setDuration] = useState(3);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      if (kind === "sleep") {
        await createSleepTask(duration);
      } else {
        await createFailingTask();
      }
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create task");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex items-end gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
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
