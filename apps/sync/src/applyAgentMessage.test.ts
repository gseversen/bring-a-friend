import { test } from "node:test";
import assert from "node:assert/strict";
import * as Y from "yjs";
import { getRun, getTimeline, type RunInfo, type TimelineEvent } from "@baf/doc-schema";
import { applyAgentMessage } from "./applyAgentMessage.js";

const run = (id: string): RunInfo => ({ id, task: "t", status: "running", startedBy: "a", startedAt: 0 });
const event = (runId: string, id: string): TimelineEvent => ({ id, runId, type: "thought", content: "x", ts: 0 });

test("run_started resets the timeline and sets run info", () => {
  const doc = new Y.Doc();
  applyAgentMessage(doc, { type: "run_started", run: run("r1") });
  applyAgentMessage(doc, { type: "event", event: event("r1", "e1") });
  applyAgentMessage(doc, { type: "run_started", run: run("r2") });

  assert.equal(getRun(doc).get("id"), "r2");
  assert.equal(getTimeline(doc).length, 0);
});

test("events are appended in order and stale runs are ignored", () => {
  const doc = new Y.Doc();
  applyAgentMessage(doc, { type: "run_started", run: run("r1") });
  applyAgentMessage(doc, { type: "event", event: event("r1", "e1") });
  applyAgentMessage(doc, { type: "event", event: event("old", "e2") });
  applyAgentMessage(doc, { type: "event", event: event("r1", "e3") });
  applyAgentMessage(doc, { type: "run_finished", runId: "r1", status: "done" });

  assert.deepEqual(getTimeline(doc).toArray().map((e) => e.id), ["e1", "e3"]);
  assert.equal(getRun(doc).get("status"), "done");
});
