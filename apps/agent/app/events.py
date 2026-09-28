"""Python mirror of the wire messages in packages/doc-schema/src/index.ts,
plus the mapping from LangGraph node updates to timeline events."""

import time
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


def _now_ms() -> int:
    return int(time.time() * 1000)


def _new_id() -> str:
    return uuid.uuid4().hex


class CamelModel(BaseModel):
    # snake_case in Python, camelCase on the wire to match the TypeScript types.
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    def dump(self) -> dict:
        return self.model_dump(by_alias=True, exclude_none=True)


RunStatus = Literal["idle", "running", "pausing", "paused", "awaiting_approval", "done", "error"]
HumanAction = Literal["pause", "resume", "approve", "reject", "redirect"]


class PendingApproval(CamelModel):
    id: str
    tool_name: str
    args: dict


class RunInfo(CamelModel):
    id: str = Field(default_factory=_new_id)
    task: str
    status: RunStatus = "running"
    started_by: str
    started_at: int = Field(default_factory=_now_ms)
    pending_approval: PendingApproval | None = None


class TimelineEvent(CamelModel):
    id: str = Field(default_factory=_new_id)
    run_id: str
    type: Literal["thought", "tool_call", "tool_result", "final", "error", "approval_request", "human"]
    content: str
    tool_name: str | None = None
    args: dict | None = None
    actor: str | None = None
    action: HumanAction | None = None
    ts: int = Field(default_factory=_now_ms)


def events_from_update(node: str, update: dict, run_id: str, tool_names: dict[str, str]) -> list[TimelineEvent]:
    """Turn one graph node's output into timeline events.

    `tool_names` maps tool_use ids to tool names across the run, because a
    tool_result block only carries the id of the call it answers."""
    events = []
    for message in update["messages"]:
        blocks = message["content"]
        if node == "agent":
            calls_tools = any(b["type"] == "tool_use" for b in blocks)
            for b in blocks:
                if b["type"] == "thinking" and b["thinking"].strip():
                    events.append(TimelineEvent(run_id=run_id, type="thought", content=b["thinking"]))
                elif b["type"] == "text" and b["text"].strip():
                    # Text before a tool call is narration; text in the last turn is the answer.
                    kind = "thought" if calls_tools else "final"
                    events.append(TimelineEvent(run_id=run_id, type=kind, content=b["text"]))
                elif b["type"] == "tool_use":
                    tool_names[b["id"]] = b["name"]
                    events.append(TimelineEvent(
                        run_id=run_id, type="tool_call", content=b["name"], tool_name=b["name"], args=b["input"]
                    ))
        elif node == "tools":
            for b in blocks:
                events.append(TimelineEvent(
                    run_id=run_id,
                    type="error" if b.get("is_error") else "tool_result",
                    content=b["content"],
                    tool_name=tool_names.get(b["tool_use_id"]),
                ))
    return events
