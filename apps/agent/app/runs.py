import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import aclosing, suppress
from dataclasses import dataclass, field
from typing import Any

from langgraph.types import Command

from app.events import HumanAction, RunInfo, RunStatus, TimelineEvent, events_from_update

logger = logging.getLogger(__name__)

Send = Callable[[str, dict], Awaitable[None]]

FINISHED: set[RunStatus] = {"done", "error"}

# For conflict messages: "Can't resume: the run is <...>".
DESCRIBE: dict[RunStatus, str] = {
    "idle": "not started",
    "running": "running",
    "pausing": "already pausing",
    "paused": "paused",
    "awaiting_approval": "waiting for an approval decision",
    "done": "finished",
    "error": "stopped with an error",
}


class Conflict(Exception):
    """The command doesn't fit the run's current state (HTTP 409)."""


class NotFound(Exception):
    """No run with that id (HTTP 404)."""


@dataclass
class Run:
    id: str
    room: str
    status: RunStatus
    # Serializes commands on this run: each one checks the state and changes
    # it while holding the lock, so the first command to arrive wins.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # The background task driving the graph, while one is active.
    driver: asyncio.Task | None = None
    pause_requested_by: str | None = None
    # The interrupt payload ({id, toolName, args}) while awaiting approval.
    pending_approval: dict | None = None
    # The most recent decision, so a late duplicate gets a clear 409.
    last_decision: dict | None = None
    # tool_use id -> tool name, so results can be labeled even when the call
    # happened before a pause.
    tool_names: dict[str, str] = field(default_factory=dict)


class RunManager:
    """Owns every run's lifecycle: starting it, driving the graph, and
    publishing each step and status change to the run's room."""

    def __init__(self, graph, send: Send):
        self.graph = graph
        self.send = send
        self.runs: dict[str, Run] = {}

    def _config(self, run: Run) -> dict:
        # thread_id selects this run's checkpoints. The room goes into the
        # checkpoint metadata so a restarted agent can find where to publish.
        return {"configurable": {"thread_id": run.id}, "metadata": {"room": run.room}}

    async def _update(self, run: Run, **patch: Any) -> None:
        if "status" in patch:
            run.status = patch["status"]
        await self.send(run.room, {"type": "run_updated", "runId": run.id, "patch": patch})

    async def _event(self, run: Run, event: TimelineEvent) -> None:
        await self.send(run.room, {"type": "event", "event": event.dump()})

    async def _human(self, run: Run, by: str, action: HumanAction, content: str) -> None:
        """Attribution: every steering action shows up on the timeline with who did it."""
        await self._event(run, TimelineEvent(run_id=run.id, type="human", actor=by, action=action, content=content))

    async def _get(self, run_id: str) -> Run:
        """Find a run, rebuilding it from its checkpoint if this process doesn't
        know it (e.g. the agent restarted while the run was paused)."""
        if run_id in self.runs:
            return self.runs[run_id]
        snapshot = await self.graph.aget_state({"configurable": {"thread_id": run_id}})
        if not snapshot.values:
            raise NotFound("No run with that id")

        # snapshot.next is the node(s) that would run next; empty means the
        # graph reached END. A task with an error means the last node failed,
        # and snapshot.interrupts holds any interrupt() waiting for a resume.
        pending = None
        if any(task.error for task in snapshot.tasks):
            status: RunStatus = "error"
        elif snapshot.interrupts:
            status = "awaiting_approval"
            pending = snapshot.interrupts[0].value
        elif snapshot.next:
            # Whatever it was doing when the agent stopped, it can continue
            # from the last checkpoint, so it comes back as paused.
            status = "paused"
        else:
            status = "done"

        # Another command may have recovered this run while we awaited.
        if run_id in self.runs:
            return self.runs[run_id]
        run = self.runs[run_id] = Run(
            id=run_id, room=snapshot.metadata["room"], status=status, pending_approval=pending
        )
        for message in snapshot.values["messages"]:
            if message["role"] == "assistant":
                run.tool_names.update({b["id"]: b["name"] for b in message["content"] if b["type"] == "tool_use"})
        # The doc may still show a stale status from before the restart.
        await self._update(run, status=status, pendingApproval=pending)
        return run

    async def pause(self, run_id: str, by: str) -> None:
        run = await self._get(run_id)
        async with run.lock:
            if run.status == "pausing":
                raise Conflict(f"{run.pause_requested_by} already asked the agent to pause")
            if run.status != "running":
                raise Conflict(f"Can't pause: the run is {DESCRIBE[run.status]}")
            # Cooperative: the driver notices this after the current node finishes.
            run.pause_requested_by = by
            await self._update(run, status="pausing")
            await self._human(run, by, "pause", f"{by} asked the agent to pause")

    async def resume(self, run_id: str, by: str) -> None:
        run = await self._get(run_id)
        async with run.lock:
            if run.status != "paused":
                raise Conflict(f"Can't resume: the run is {DESCRIBE[run.status]}")
            await self._update(run, status="running")
            await self._human(run, by, "resume", f"{by} resumed the agent")
            # None as input means "no new input: continue from the latest checkpoint".
            self._drive(run, None)

    async def start(self, room: str, task: str, started_by: str) -> str:
        # No await between this check and claiming the room, so two
        # simultaneous starts can't both pass it.
        if any(r.room == room and r.status not in FINISHED for r in self.runs.values()):
            raise Conflict("This room already has an unfinished run")
        info = RunInfo(task=task, started_by=started_by)
        run = self.runs[info.id] = Run(id=info.id, room=room, status="running")
        try:
            await self.send(room, {"type": "run_started", "run": info.dump()})
        except Exception:
            del self.runs[run.id]
            raise
        self._drive(run, {"messages": [{"role": "user", "content": task}]})
        return run.id

    async def decide(self, run_id: str, by: str, approval_id: str, approved: bool, reason: str | None) -> None:
        run = await self._get(run_id)
        verb = "approve" if approved else "reject"
        async with run.lock:
            last = run.last_decision
            if last and last["id"] == approval_id:
                raise Conflict(f"{last['by']} already {'approved' if last['approved'] else 'rejected'} this call")
            if run.status != "awaiting_approval":
                raise Conflict(f"Can't {verb}: the run is {DESCRIBE[run.status]}")
            if run.pending_approval["id"] != approval_id:
                raise Conflict(f"Can't {verb}: that tool call is no longer the one waiting for approval")

            tool = run.pending_approval["toolName"]
            run.last_decision = {"id": approval_id, "by": by, "approved": approved}
            run.pending_approval = None
            await self._update(run, status="running", pendingApproval=None)
            detail = f": {reason}" if reason else ""
            await self._human(run, by, "approve" if approved else "reject", f"{by} {verb}d {tool}{detail}")
            # Command(resume=...) re-runs the approval node, and interrupt()
            # returns this value there. It records who decided and why.
            self._drive(run, Command(resume={"approved": approved, "by": by, "reason": reason}))

    def _drive(self, run: Run, graph_input: Any) -> None:
        """Start (or continue) the graph in the background. `graph_input` is the
        initial state for a new run, None to continue from the checkpoint, or a
        Command(resume=...) answering a pending interrupt."""
        run.driver = asyncio.create_task(self._run_graph(run, graph_input))

    async def _run_graph(self, run: Run, graph_input: Any) -> None:
        status: RunStatus = "done"
        pending = None
        try:
            # stream_mode="updates" yields {node_name: node_output} after every
            # node, so each step reaches the timeline as soon as it finishes.
            # durability="sync" makes LangGraph finish saving each checkpoint
            # before the next node starts, so stopping between nodes is safe.
            # aclosing() closes the stream as soon as we break out of it.
            stream = self.graph.astream(graph_input, self._config(run), stream_mode="updates", durability="sync")
            async with aclosing(stream):
                async for update in stream:
                    if "__interrupt__" in update:
                        # interrupt() was called: the graph has stopped and
                        # checkpointed, and the stream ends here.
                        status = "awaiting_approval"
                        pending = update["__interrupt__"][0].value
                        break
                    for node, node_output in update.items():
                        for event in events_from_update(node, node_output, run.id, run.tool_names):
                            await self._event(run, event)
                    if run.status == "pausing":
                        # The node that just finished is already checkpointed, so
                        # we can simply stop reading. Resume picks up at the next node.
                        status = "paused"
                        break
        except Exception as exc:
            logger.exception("run %s failed", run.id)
            status = "error"
            # The sync server may be what failed, so reporting the error is best effort.
            with suppress(Exception):
                await self._event(run, TimelineEvent(run_id=run.id, type="error", content=str(exc)))
        # Take the lock so this final status can't interleave with a command.
        async with run.lock:
            run.status = status
            run.pending_approval = pending
            with suppress(Exception):
                if pending:
                    await self._event(run, TimelineEvent(
                        run_id=run.id, type="approval_request", tool_name=pending["toolName"],
                        args=pending["args"], content=f"{pending['toolName']} needs a participant's approval",
                    ))
                    await self._update(run, status=status, pendingApproval=pending)
                else:
                    await self._update(run, status=status)

    async def wait(self, run_id: str) -> None:
        """Wait for the run's current driver to stop (used by tests)."""
        run = self.runs[run_id]
        if run.driver:
            await run.driver
