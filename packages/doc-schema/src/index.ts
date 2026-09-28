// The shape of the shared Yjs document, one Y.Doc per room.
// Both the web client (reader) and the sync server (the only writer of
// agent data) import from here, so the schema is defined exactly once.
// The Python agent mirrors the wire messages in apps/agent/app/events.py.
import type * as Y from "yjs";

// running -> pausing -> paused -> running, and running -> awaiting_approval -> running.
export type RunStatus = "idle" | "running" | "pausing" | "paused" | "awaiting_approval" | "done" | "error";

// A risky tool call waiting for a participant to approve or reject it.
// `id` is the tool_use id; approve/reject commands must echo it back.
export interface PendingApproval {
  id: string;
  toolName: string;
  args: Record<string, unknown>;
}

export interface RunInfo {
  id: string;
  task: string;
  status: RunStatus;
  startedBy: string;
  startedAt: number;
  pendingApproval?: PendingApproval | null;
}

export type TimelineEventType =
  | "thought"
  | "tool_call"
  | "tool_result"
  | "final"
  | "error"
  | "approval_request"
  | "human";

// Steering actions a participant can take; each becomes a "human" timeline event.
export type HumanAction = "pause" | "resume" | "approve" | "reject" | "redirect";

// Timeline entries are append-only and never edited after they are written,
// so they are stored as plain JSON objects rather than nested Y types.
export interface TimelineEvent {
  id: string;
  runId: string;
  type: TimelineEventType;
  content: string;
  toolName?: string;
  args?: Record<string, unknown>;
  // Set on "human" events: who did what.
  actor?: string;
  action?: HumanAction;
  ts: number;
}

// Messages the agent POSTs to the sync server (see apps/sync/src/index.ts).
export type AgentMessage =
  | { type: "run_started"; run: RunInfo }
  | { type: "event"; event: TimelineEvent }
  | { type: "run_updated"; runId: string; patch: Partial<Omit<RunInfo, "id">> };

// Ephemeral per-client state shared through Yjs awareness, not stored in the doc.
export interface PresenceUser {
  name: string;
  color: string;
}

export const getRun = (doc: Y.Doc) => doc.getMap<RunInfo[keyof RunInfo]>("run");
export const getTimeline = (doc: Y.Doc) => doc.getArray<TimelineEvent>("timeline");
