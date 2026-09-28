import asyncio

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app import tools
from app.graph import build_graph
from app.llm import MockLLM
from app.runs import Conflict, NotFound, RunManager


@pytest.fixture(autouse=True)
def no_tool_delay(monkeypatch):
    monkeypatch.setattr(tools, "TOOL_DELAY_S", 0)


class Recorder:
    """Stands in for the sync server: records every message sent to a room."""

    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    async def send(self, room: str, message: dict) -> None:
        self.sent.append((room, message))

    def statuses(self) -> list[str]:
        return [m["patch"]["status"] for _, m in self.sent if m["type"] == "run_updated" and "status" in m["patch"]]

    def events(self) -> list[dict]:
        return [m["event"] for _, m in self.sent if m["type"] == "event"]

    def humans(self) -> list[tuple[str, str]]:
        return [(e["actor"], e["action"]) for e in self.events() if e["type"] == "human"]


def new_manager(checkpointer=None) -> tuple[RunManager, Recorder]:
    recorder = Recorder()
    return RunManager(build_graph(MockLLM(), checkpointer or InMemorySaver()), recorder.send), recorder


def test_pause_takes_effect_after_current_node_and_resume_finishes():
    async def main():
        manager, recorder = new_manager()
        run_id = await manager.start("demo", "solar power", "Ann")
        # Requested while the first node (the model call) is still running.
        await manager.pause(run_id, "Ben")
        await manager.wait(run_id)

        assert manager.runs[run_id].status == "paused"
        snapshot = await manager.graph.aget_state({"configurable": {"thread_id": run_id}})
        assert snapshot.next == ("tools",)  # the model asked for a tool; it hasn't run yet
        assert [e["type"] for e in recorder.events()] == ["human", "thought", "tool_call"]

        await manager.resume(run_id, "Cy")
        await manager.wait(run_id)
        return recorder

    recorder = asyncio.run(main())
    assert recorder.statuses() == ["pausing", "paused", "running", "done"]
    assert recorder.humans() == [("Ben", "pause"), ("Cy", "resume")]
    assert recorder.events()[-1]["type"] == "final"


def test_commands_that_dont_fit_the_state_conflict():
    async def main():
        manager, _ = new_manager()
        run_id = await manager.start("demo", "solar power", "Ann")
        with pytest.raises(Conflict, match="Can't resume: the run is running"):
            await manager.resume(run_id, "Cy")
        await manager.pause(run_id, "Ben")
        with pytest.raises(Conflict, match="Ben already asked the agent to pause"):
            await manager.pause(run_id, "Cy")
        with pytest.raises(Conflict, match="This room already has an unfinished run"):
            await manager.start("demo", "another task", "Cy")
        await manager.wait(run_id)
        with pytest.raises(NotFound):
            await manager.pause("no-such-run", "Cy")

    asyncio.run(main())


def test_paused_run_survives_agent_restart(tmp_path):
    db = str(tmp_path / "checkpoints.sqlite")

    async def before_restart() -> str:
        async with AsyncSqliteSaver.from_conn_string(db) as checkpointer:
            manager, _ = new_manager(checkpointer)
            run_id = await manager.start("demo", "solar power", "Ann")
            await manager.pause(run_id, "Ben")
            await manager.wait(run_id)
            return run_id

    async def after_restart(run_id: str) -> Recorder:
        # A fresh manager knows nothing in memory; everything comes from SQLite.
        async with AsyncSqliteSaver.from_conn_string(db) as checkpointer:
            manager, recorder = new_manager(checkpointer)
            await manager.resume(run_id, "Cy")
            await manager.wait(run_id)
            return recorder

    run_id = asyncio.run(before_restart())
    recorder = asyncio.run(after_restart(run_id))

    assert {room for room, _ in recorder.sent} == {"demo"}  # room recovered from checkpoint metadata
    assert recorder.statuses() == ["paused", "running", "done"]
    assert recorder.events()[-1]["type"] == "final"
