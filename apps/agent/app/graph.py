"""The agent as a two-node LangGraph state machine:

    START -> agent --(tool calls?)--> tools -> agent -> ... -> END

Each node's output is streamed out as a separate update, which is what lets
us publish every step to the shared timeline as it happens. Compiling with a
checkpointer and running each task under its own thread_id is the hook for
pause/resume later (interrupt_before=["tools"] + resume from the checkpoint).
"""

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Checkpointer

from app.llm import LLM
from app.tools import run_tool


class AgentState(TypedDict):
    # Anthropic Messages API params. operator.add makes each node's returned
    # messages append to the list instead of replacing it.
    messages: Annotated[list[dict], operator.add]


def _tool_calls(message: dict) -> list[dict]:
    return [b for b in message["content"] if b["type"] == "tool_use"]


def build_graph(llm: LLM, checkpointer: Checkpointer = None):
    async def agent(state: AgentState) -> dict:
        content = await llm(state["messages"])
        return {"messages": [{"role": "assistant", "content": content}]}

    async def tools(state: AgentState) -> dict:
        results = []
        for call in _tool_calls(state["messages"][-1]):
            result = {"type": "tool_result", "tool_use_id": call["id"]}
            try:
                result["content"] = await run_tool(call["name"], call["input"])
            except Exception as exc:
                # Tool errors go back to the model so it can recover.
                result.update(content=f"Error: {exc}", is_error=True)
            results.append(result)
        # All results for one turn go back in a single user message.
        return {"messages": [{"role": "user", "content": results}]}

    def route(state: AgentState) -> str:
        return "tools" if _tool_calls(state["messages"][-1]) else END

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent)
    graph.add_node("tools", tools)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, ["tools", END])
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)
