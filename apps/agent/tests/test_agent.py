import asyncio

import pytest

from app import tools
from langgraph.checkpoint.memory import InMemorySaver

from app.events import events_from_update
from app.graph import build_graph
from app.llm import MockLLM, _drop_declined_attempt
from app.runs import RunManager


@pytest.fixture(autouse=True)
def no_tool_delay(monkeypatch):
    monkeypatch.setattr(tools, "TOOL_DELAY_S", 0)


def run(graph, task="solar power"):
    sent = []

    async def send(room, message):
        sent.append((room, message))

    async def main():
        manager = RunManager(graph, send)
        await manager.wait(await manager.start("demo", task, "tester"))

    asyncio.run(main())
    return sent


def test_mock_run_streams_every_step_in_order():
    sent = run(build_graph(MockLLM(), InMemorySaver()))

    assert all(room == "demo" for room, _ in sent)
    events = [m["event"] for _, m in sent if m["type"] == "event"]
    assert [e["type"] for e in events] == [
        "thought", "tool_call", "tool_result",
        "thought", "tool_call", "tool_result",
        "thought", "tool_call", "tool_result",
        "final",
    ]
    assert [e["toolName"] for e in events if e["type"] == "tool_result"] == ["search_web", "read_page", "save_note"]
    assert sent[-1][1] == {"type": "run_updated", "runId": events[0]["runId"], "patch": {"status": "done"}}


def test_llm_failure_reports_error_and_finishes_run():
    async def broken_llm(messages):
        raise RuntimeError("boom")

    sent = run(build_graph(broken_llm, InMemorySaver()))

    events = [m["event"] for _, m in sent if m["type"] == "event"]
    assert [(e["type"], e["content"]) for e in events] == [("error", "boom")]
    assert sent[-1][1]["patch"]["status"] == "error"


def test_text_is_narration_when_tools_are_called_and_final_otherwise():
    narrate = {"messages": [{"role": "assistant", "content": [
        {"type": "text", "text": "Let me search."},
        {"type": "tool_use", "id": "t1", "name": "search_web", "input": {"query": "x"}},
    ]}]}
    answer = {"messages": [{"role": "assistant", "content": [{"type": "text", "text": "Done."}]}]}

    assert [e.type for e in events_from_update("agent", narrate, "r", {})] == ["thought", "tool_call"]
    assert [e.type for e in events_from_update("agent", answer, "r", {})] == ["final"]


def test_declined_attempt_is_dropped_before_fallback_boundary():
    content = [
        {"type": "thinking", "thinking": "declined model", "signature": "s"},
        {"type": "text", "text": "partial"},
        {"type": "fallback", "from": {"model": "a"}, "to": {"model": "b"}},
        {"type": "tool_use", "id": "t1", "name": "search_web", "input": {}},
    ]
    assert [b["type"] for b in _drop_declined_attempt(content)] == ["text", "tool_use"]
