"""The agent as a LangGraph state machine:

    START -> agent --(risky tool call?)--> approval -> tools -> agent -> ...
                   --(safe tool calls)-------------> tools -> agent -> ...
                   --(no tool calls)--> END

Each node's output is streamed out as a separate update, and a checkpoint is
saved after every node. That is what makes pause/resume, approvals and
redirects possible: the run can stop between any two nodes and continue
later from the saved state.
"""

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Checkpointer, interrupt

from app.llm import LLM
from app.tools import RISKY_TOOLS, run_tool


def _merge(left: dict, right: dict) -> dict:
    return {**left, **right}


class AgentState(TypedDict):
    # Anthropic Messages API params. operator.add makes each node's returned
    # messages append to the list instead of replacing it.
    messages: Annotated[list[dict], operator.add]
    # Approval decisions by tool_use id, filled in by the approval node.
    decisions: Annotated[dict[str, dict], _merge]


def _tool_calls(message: dict) -> list[dict]:
    return [b for b in message["content"] if b["type"] == "tool_use"]


def build_graph(llm: LLM, checkpointer: Checkpointer = None):
    async def agent(state: AgentState) -> dict:
        content = await llm(state["messages"])
        return {"messages": [{"role": "assistant", "content": content}]}

    async def approval(state: AgentState) -> dict:
        # interrupt() stops the graph and saves a checkpoint. Resuming with
        # Command(resume=decision) re-runs this node from the top, and this
        # time interrupt() returns the decision. Because the node re-runs, it
        # must do nothing with side effects; that's why approval is its own
        # node rather than a step inside `tools`. With several risky calls,
        # each interrupt() gets its own resume, matched by order.
        decisions = {}
        for call in _tool_calls(state["messages"][-1]):
            if call["name"] in RISKY_TOOLS:
                # The payload is shaped like PendingApproval in the doc schema.
                decisions[call["id"]] = interrupt({"id": call["id"], "toolName": call["name"], "args": call["input"]})
        return {"decisions": decisions}

    async def tools(state: AgentState) -> dict:
        decisions = state.get("decisions", {})
        results = []
        for call in _tool_calls(state["messages"][-1]):
            result = {"type": "tool_result", "tool_use_id": call["id"]}
            decision = decisions.get(call["id"])
            if call["name"] in RISKY_TOOLS and not (decision and decision["approved"]):
                # Rejections go back to the model as a result, so it can adapt.
                reason = f": {decision['reason']}" if decision and decision.get("reason") else ""
                by = decision["by"] if decision else "a participant"
                result.update(content=f"Not run: {by} rejected this call{reason}", is_error=True)
            else:
                try:
                    result["content"] = await run_tool(call["name"], call["input"])
                except Exception as exc:
                    # Tool errors go back to the model so it can recover.
                    result.update(content=f"Error: {exc}", is_error=True)
            results.append(result)
        # All results for one turn go back in a single user message.
        return {"messages": [{"role": "user", "content": results}]}

    def route(state: AgentState) -> str:
        calls = _tool_calls(state["messages"][-1])
        if any(call["name"] in RISKY_TOOLS for call in calls):
            return "approval"
        return "tools" if calls else END

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent)
    graph.add_node("approval", approval)
    graph.add_node("tools", tools)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, ["approval", "tools", END])
    graph.add_edge("approval", "tools")
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)
