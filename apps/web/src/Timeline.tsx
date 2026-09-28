import { useEffect, useRef } from "react";
import type { RunInfo, TimelineEvent, TimelineEventType } from "@baf/doc-schema";

const LABELS: Record<TimelineEventType, { text: string; className: string }> = {
  thought: { text: "Thought", className: "bg-slate-100 text-slate-700" },
  tool_call: { text: "Tool call", className: "bg-blue-100 text-blue-800" },
  tool_result: { text: "Result", className: "bg-emerald-100 text-emerald-800" },
  final: { text: "Answer", className: "bg-violet-100 text-violet-800" },
  error: { text: "Error", className: "bg-red-100 text-red-800" },
  approval_request: { text: "Needs approval", className: "bg-amber-100 text-amber-800" },
  human: { text: "Participant", className: "bg-sky-100 text-sky-800" },
};

interface Props {
  run: Partial<RunInfo>;
  events: TimelineEvent[];
}

export function Timeline({ run, events }: Props) {
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [events.length]);

  if (!run.id) {
    return <p className="text-sm text-slate-500">No task yet. Start one and everyone in this room will see the agent work.</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="text-sm text-slate-600">
        <span className="font-medium text-slate-900">{run.task}</span>
        {" · started by "}
        {run.startedBy}
        {" · "}
        <span className={run.status === "error" ? "text-red-600" : ""}>{run.status}</span>
      </div>
      <ol className="flex flex-col gap-2">
        {events.map((event) => (
          <li key={event.id} className="rounded-md border border-slate-200 bg-white p-3 text-sm">
            <div className="mb-1 flex items-center gap-2">
              <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${LABELS[event.type].className}`}>
                {LABELS[event.type].text}
              </span>
              {event.toolName && <code className="text-xs text-slate-500">{event.toolName}</code>}
              <time className="ml-auto text-xs text-slate-400">{new Date(event.ts).toLocaleTimeString()}</time>
            </div>
            {event.type === "tool_call" ? (
              <pre className="overflow-x-auto text-xs text-slate-700">{JSON.stringify(event.args, null, 2)}</pre>
            ) : (
              <p className="whitespace-pre-wrap text-slate-800">{event.content}</p>
            )}
          </li>
        ))}
      </ol>
      {run.status === "running" && <p className="animate-pulse text-sm text-slate-500">Agent is working…</p>}
      <div ref={bottom} />
    </div>
  );
}
