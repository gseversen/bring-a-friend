import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from app.events import RunInfo, RunStatus, TimelineEvent, events_from_update

logger = logging.getLogger(__name__)

Send = Callable[[str, dict], Awaitable[None]]

FINISHED: set[RunStatus] = {"done", "error"}


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

    def _drive(self, run: Run, graph_input: Any) -> None:
        """Start (or continue) the graph in the background. `graph_input` is the
        initial state for a new run."""
        run.driver = asyncio.create_task(self._run_graph(run, graph_input))

    async def _run_graph(self, run: Run, graph_input: Any) -> None:
        tool_names: dict[str, str] = {}
        status: RunStatus = "done"
        try:
            # stream_mode="updates" yields {node_name: node_output} after every
            # node, so each step reaches the timeline as soon as it finishes.
            # durability="sync" makes LangGraph finish saving each checkpoint
            # before the next node starts, so stopping between nodes is safe.
            async for update in self.graph.astream(
                graph_input, self._config(run), stream_mode="updates", durability="sync"
            ):
                for node, node_output in update.items():
                    for event in events_from_update(node, node_output, run.id, tool_names):
                        await self._event(run, event)
        except Exception as exc:
            logger.exception("run %s failed", run.id)
            status = "error"
            # The sync server may be what failed, so reporting the error is best effort.
            with suppress(Exception):
                await self._event(run, TimelineEvent(run_id=run.id, type="error", content=str(exc)))
        with suppress(Exception):
            await self._update(run, status=status)
        run.status = status

    async def wait(self, run_id: str) -> None:
        """Wait for the run's current driver to stop (used by tests)."""
        run = self.runs[run_id]
        if run.driver:
            await run.driver
