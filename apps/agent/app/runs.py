import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress

from app.events import RunInfo, TimelineEvent, events_from_update

logger = logging.getLogger(__name__)

Send = Callable[[str, dict], Awaitable[None]]


async def run_task(graph, send: Send, room: str, run: RunInfo) -> None:
    """Run the graph for one task, publishing each step to the room as it happens."""
    tool_names: dict[str, str] = {}
    status = "done"
    try:
        # stream_mode="updates" yields {node_name: node_output} after every node,
        # so each step reaches the timeline as soon as it finishes. Events are
        # sent one at a time, in order, so every client sees the same sequence.
        async for update in graph.astream(
            {"messages": [{"role": "user", "content": run.task}]},
            config={"configurable": {"thread_id": run.id}},
            stream_mode="updates",
        ):
            for node, node_output in update.items():
                for event in events_from_update(node, node_output, run.id, tool_names):
                    await send(room, {"type": "event", "event": event.dump()})
    except Exception as exc:
        logger.exception("run %s failed", run.id)
        status = "error"
        # The sync server may be what failed, so reporting the error is best effort.
        with suppress(Exception):
            event = TimelineEvent(run_id=run.id, type="error", content=str(exc))
            await send(room, {"type": "event", "event": event.dump()})
    with suppress(Exception):
        await send(room, {"type": "run_finished", "runId": run.id, "status": status})
