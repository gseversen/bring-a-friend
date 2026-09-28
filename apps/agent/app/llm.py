"""The model call, behind a tiny interface so tests and demos can use a
scripted fake instead of Claude. Both return the assistant's content blocks
as plain dicts, which keeps LangGraph state JSON-serializable (required once
we add a persistent checkpointer for pause/resume)."""

import asyncio
from typing import Protocol

from anthropic import AsyncAnthropic

from app.config import Settings
from app.tools import TOOLS, slugify

SYSTEM_PROMPT = (
    "You are a research assistant working in a shared session that several people "
    "are watching live. Research the user's topic with the tools provided: search, "
    "read one or two relevant pages, save a short note, email a short summary to "
    "team@example.com with send_email, then give a concise answer. Participants may "
    "reject a tool call or add instructions mid-task; follow the latest instructions. "
    "Keep the whole task to a handful of steps."
)


class LLM(Protocol):
    async def __call__(self, messages: list[dict]) -> list[dict]: ...


class LLMStopped(Exception):
    pass


class ClaudeLLM:
    def __init__(self, settings: Settings):
        # api_key=None lets the SDK fall back to its other credential sources.
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key or None)
        self.model = settings.anthropic_model
        self.fallbacks = settings.anthropic_fallbacks

    async def __call__(self, messages: list[dict]) -> list[dict]:
        fallback_args = {}
        if self.fallbacks:
            # If the model declines on policy grounds, the API retries the same
            # request on a fallback model inside this one call.
            fallback_args = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": self.fallbacks}

        response = await self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            # "summarized" returns readable reasoning summaries, which become
            # the "thought" entries on the shared timeline.
            thinking={"type": "adaptive", "display": "summarized"},
            messages=messages,
            **fallback_args,
        )
        if response.stop_reason in ("refusal", "max_tokens"):
            raise LLMStopped(f"Model stopped early: {response.stop_reason}")

        content = [block.model_dump(exclude_none=True) for block in response.content]
        return _drop_declined_attempt(content)


def _drop_declined_attempt(content: list[dict]) -> list[dict]:
    """A `fallback` block marks where a declined model's partial output ends.
    Its thinking and tool calls must not be sent back in later turns."""
    boundary = max((i for i, b in enumerate(content) if b["type"] == "fallback"), default=None)
    if boundary is None:
        return content
    kept = [b for b in content[:boundary] if b["type"] not in ("thinking", "redacted_thinking", "tool_use")]
    return kept + content[boundary + 1 :]


class MockLLM:
    """Scripted stand-in for Claude: search -> read -> note -> email -> answer.
    No API key or cost; used by tests and AGENT_MOCK_LLM=1."""

    def __init__(self, delay_s: float = 0.5):
        # The pause makes the live timeline readable in demos.
        self.delay_s = delay_s

    async def __call__(self, messages: list[dict]) -> list[dict]:
        await asyncio.sleep(self.delay_s)
        task = messages[0]["content"]
        turn = sum(1 for m in messages if m["role"] == "assistant")
        steps = [
            ("I'll start with a broad search on the topic.", "search_web", {"query": task}),
            ("The overview result looks most relevant, so I'll read it.", "read_page",
             {"url": f"https://example.com/{slugify(task)}/1"}),
            ("I have the key facts; saving a note.", "save_note",
             {"note": f"{task}: three key facts, experts split on long-term impact."}),
            ("Emailing the team a short summary.", "send_email",
             {"to": "team@example.com", "subject": f"Research: {task}",
              "body": "Three key facts found; experts disagree on long-term impact."}),
        ]
        if turn < len(steps):
            thought, tool, args = steps[turn]
            return [
                {"type": "thinking", "thinking": thought, "signature": "mock"},
                {"type": "tool_use", "id": f"mock_{turn}", "name": tool, "input": args},
            ]
        last = messages[-1]["content"]
        rejected = isinstance(last, list) and any(b.get("is_error") for b in last)
        email = "I did not send the email because it was rejected." if rejected else "I emailed the team a summary."
        instructions = [
            b["text"] for m in messages[1:] if m["role"] == "user" and isinstance(m["content"], list)
            for b in m["content"] if b["type"] == "text"
        ]
        followed = f" {instructions[-1]} (noted)." if instructions else ""
        return [{"type": "text", "text": f"Summary of '{task}': three key facts found; "
                 f"experts disagree on long-term impact. {email}{followed} (mock answer)"}]
