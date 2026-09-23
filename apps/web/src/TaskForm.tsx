import { useState, type FormEvent } from "react";

const AGENT_URL = import.meta.env.VITE_AGENT_URL ?? "http://localhost:8000";

interface Props {
  room: string;
  userName: string;
  running: boolean;
}

export function TaskForm({ room, userName, running }: Props) {
  const [task, setTask] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      // Only starts the run. Progress comes back through the shared doc, so
      // every client (not just this one) sees it.
      const res = await fetch(`${AGENT_URL}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ room, task, startedBy: userName }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setError(typeof body?.detail === "string" ? body.detail : `Agent returned ${res.status}`);
        return;
      }
      setTask("");
    } catch {
      setError("Could not reach the agent service.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2">
      <div className="flex gap-2">
        <input
          value={task}
          onChange={(e) => setTask(e.target.value)}
          placeholder="Give the agent a research topic, e.g. the history of solar power"
          className="flex-1 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
        />
        <button
          type="submit"
          disabled={!task.trim() || running || submitting}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
        >
          {running ? "Agent working…" : "Start task"}
        </button>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </form>
  );
}
