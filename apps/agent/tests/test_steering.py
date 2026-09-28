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


async def approve_pending(manager: RunManager, run_id: str, by: str = "Dee") -> None:
    await manager.wait(run_id)
    await manager.decide(run_id, by, manager.runs[run_id].pending_approval["id"], True, None)
    await manager.wait(run_id)


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


def new_manager(checkpointer=None, llm_delay_s: float = 0) -> tuple[RunManager, Recorder]:
    recorder = Recorder()
    llm = MockLLM(delay_s=llm_delay_s)
    return RunManager(build_graph(llm, checkpointer or InMemorySaver()), recorder.send), recorder


def test_pause_takes_effect_after_current_node_and_resume_finishes():
    async def main():
        manager, recorder = new_manager(llm_delay_s=0.2)
        run_id = await manager.start("demo", "solar power", "Ann")
        # Requested while the first node (the model call) is still running.
        await manager.pause(run_id, "Ben")
        await manager.wait(run_id)

        assert manager.runs[run_id].status == "paused"
        snapshot = await manager.graph.aget_state({"configurable": {"thread_id": run_id}})
        assert snapshot.next == ("tools",)  # the model asked for a tool; it hasn't run yet
        assert [e["type"] for e in recorder.events()] == ["human", "thought", "tool_call"]

        await manager.resume(run_id, "Cy")
        await approve_pending(manager, run_id)
        return recorder

    recorder = asyncio.run(main())
    assert recorder.statuses() == ["pausing", "paused", "running", "awaiting_approval", "running", "done"]
    assert recorder.humans() == [("Ben", "pause"), ("Cy", "resume"), ("Dee", "approve")]
    assert recorder.events()[-1]["type"] == "final"


def test_commands_that_dont_fit_the_state_conflict():
    async def main():
        manager, _ = new_manager(llm_delay_s=0.2)
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
            manager, _ = new_manager(checkpointer, llm_delay_s=0.2)
            run_id = await manager.start("demo", "solar power", "Ann")
            await manager.pause(run_id, "Ben")
            await manager.wait(run_id)
            return run_id

    async def after_restart(run_id: str) -> Recorder:
        # A fresh manager knows nothing in memory; everything comes from SQLite.
        async with AsyncSqliteSaver.from_conn_string(db) as checkpointer:
            manager, recorder = new_manager(checkpointer)
            await manager.resume(run_id, "Cy")
            await manager.wait(run_id)  # runs until send_email needs approval
            return recorder

    async def after_second_restart(run_id: str) -> Recorder:
        async with AsyncSqliteSaver.from_conn_string(db) as checkpointer:
            manager, recorder = new_manager(checkpointer)
            await manager.decide(run_id, "Dee", "mock_3", True, None)
            await manager.wait(run_id)
            return recorder

    run_id = asyncio.run(before_restart())
    recorder = asyncio.run(after_restart(run_id))
    assert {room for room, _ in recorder.sent} == {"demo"}  # room recovered from checkpoint metadata
    assert recorder.statuses() == ["paused", "running", "awaiting_approval"]

    # The pending interrupt is recovered too, and answering it finishes the run.
    recorder = asyncio.run(after_second_restart(run_id))
    assert recorder.statuses() == ["awaiting_approval", "running", "done"]
    assert recorder.events()[-1]["type"] == "final"


def test_rejection_goes_back_to_the_model_as_a_tool_result():
    async def main():
        manager, recorder = new_manager()
        run_id = await manager.start("demo", "solar power", "Ann")
        await manager.wait(run_id)
        assert manager.runs[run_id].status == "awaiting_approval"
        await manager.decide(run_id, "Ben", "mock_3", False, "don't email the team yet")
        await manager.wait(run_id)
        state = await manager.graph.aget_state({"configurable": {"thread_id": run_id}})
        return recorder, state.values["messages"]

    recorder, messages = asyncio.run(main())
    result = messages[-2]["content"][0]
    assert result == {
        "type": "tool_result",
        "tool_use_id": "mock_3",
        "content": "Not run: Ben rejected this call: don't email the team yet",
        "is_error": True,
    }
    assert recorder.humans() == [("Ben", "reject")]
    assert "did not send the email" in recorder.events()[-1]["content"]


def test_simultaneous_conflicting_decisions_first_wins():
    async def main():
        manager, recorder = new_manager()
        run_id = await manager.start("demo", "solar power", "Ann")
        await manager.wait(run_id)
        approval_id = manager.runs[run_id].pending_approval["id"]
        # Both commands are in flight at once; the per-run lock orders them.
        results = await asyncio.gather(
            manager.decide(run_id, "Ben", approval_id, True, None),
            manager.decide(run_id, "Cy", approval_id, False, "no"),
            return_exceptions=True,
        )
        await manager.wait(run_id)
        return recorder, results

    recorder, (first, second) = asyncio.run(main())
    assert first is None
    assert isinstance(second, Conflict)
    assert str(second) == "Ben already approved this call"
    assert recorder.humans() == [("Ben", "approve")]
    assert recorder.statuses()[-1] == "done"


def test_decision_for_a_stale_approval_id_conflicts():
    async def main():
        manager, _ = new_manager()
        run_id = await manager.start("demo", "solar power", "Ann")
        await manager.wait(run_id)
        with pytest.raises(Conflict, match="no longer the one waiting for approval"):
            await manager.decide(run_id, "Ben", "some-older-call", True, None)

    asyncio.run(main())


def test_approval_resume_does_not_rerun_safe_tools_from_the_same_turn(monkeypatch):
    """The model asks for a safe and a risky tool in one turn. Resuming after
    the approval re-runs the approval node, which must not re-run anything."""
    ran = []

    async def fake_run_tool(name, args):
        ran.append(name)
        return "ok"

    monkeypatch.setattr("app.graph.run_tool", fake_run_tool)

    async def llm(messages):
        if len(messages) == 1:
            return [
                {"type": "tool_use", "id": "t1", "name": "search_web", "input": {"query": "x"}},
                {"type": "tool_use", "id": "t2", "name": "send_email", "input": {"to": "a", "subject": "b", "body": "c"}},
            ]
        return [{"type": "text", "text": "done"}]

    async def main():
        recorder = Recorder()
        manager = RunManager(build_graph(llm, InMemorySaver()), recorder.send)
        run_id = await manager.start("demo", "task", "Ann")
        await approve_pending(manager, run_id)

    asyncio.run(main())
    assert ran == ["search_web", "send_email"]
