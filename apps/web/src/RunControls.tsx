import { useEffect, useState, type FormEvent } from "react";
import type { RunInfo } from "@baf/doc-schema";
import { postToAgent } from "./api";

interface Props {
  run: Partial<RunInfo>;
  userName: string;
}

const button = "rounded-md px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-40";
const input = "flex-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm focus:border-slate-500 focus:outline-none";

// Steering controls for the room's run. Every participant sees the same
// controls because they are derived from the shared run status.
export function RunControls({ run, userName }: Props) {
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [instruction, setInstruction] = useState("");
  const [reason, setReason] = useState("");

  // A message about a previous run is stale once a new run starts.
  useEffect(() => {
    setError(null);
  }, [run.id]);

  async function command(action: string, body: object = {}): Promise<boolean> {
    setError(null);
    setSending(true);
    const err = await postToAgent(`/runs/${run.id}/${action}`, { by: userName, ...body });
    setSending(false);
    setError(err);
    return !err;
  }

  async function onRedirect(e: FormEvent) {
    e.preventDefault();
    if (await command("redirect", { instruction })) setInstruction("");
  }

  async function decide(approved: boolean) {
    const approvalId = run.pendingApproval?.id;
    if (await command("approval", { approvalId, approved, reason: reason || null })) setReason("");
  }

  let body = null;
  switch (run.status) {
    case "running":
      body = (
        <button onClick={() => command("pause")} disabled={sending} className={`${button} bg-slate-900 text-white`}>
          Pause
        </button>
      );
      break;
    case "pausing":
      body = (
        <button disabled className={`${button} bg-slate-900 text-white`}>
          Pausing… (after the current step)
        </button>
      );
      break;
    case "paused":
      body = (
        <div className="flex flex-col gap-2">
          <button onClick={() => command("resume")} disabled={sending} className={`${button} self-start bg-slate-900 text-white`}>
            Resume
          </button>
          <form onSubmit={onRedirect} className="flex gap-2">
            <input
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder="Redirect: add an instruction for the agent"
              className={input}
            />
            <button type="submit" disabled={!instruction.trim() || sending} className={`${button} border border-slate-300 bg-white`}>
              Add instruction
            </button>
          </form>
        </div>
      );
      break;
    case "awaiting_approval":
      body = run.pendingApproval && (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-slate-700">
            The agent wants to run <code className="font-semibold">{run.pendingApproval.toolName}</code>. Anyone in the
            room can decide.
          </p>
          <pre className="overflow-x-auto rounded bg-slate-50 p-2 text-xs text-slate-700">
            {JSON.stringify(run.pendingApproval.args, null, 2)}
          </pre>
          <div className="flex gap-2">
            <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (optional)" className={input} />
            <button onClick={() => decide(true)} disabled={sending} className={`${button} bg-emerald-600 text-white`}>
              Approve
            </button>
            <button onClick={() => decide(false)} disabled={sending} className={`${button} bg-red-600 text-white`}>
              Reject
            </button>
          </div>
        </div>
      );
      break;
  }
  // Keep a rejected command's message (e.g. "Ben already approved this call")
  // visible even after the run moves on, until this person acts again.
  if (!body && !error) return null;

  return (
    <section className="flex flex-col gap-2 rounded-md border border-slate-200 bg-white p-3">
      {body}
      {error && <p className="text-sm text-red-600">{error}</p>}
    </section>
  );
}
