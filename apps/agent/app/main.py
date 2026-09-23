import asyncio
from contextlib import asynccontextmanager

import httpx2
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from app.config import settings
from app.events import CamelModel, RunInfo
from app.graph import build_graph
from app.llm import ClaudeLLM, MockLLM
from app.runs import run_task
from app.sync_client import SyncClient

llm = MockLLM() if settings.agent_mock_llm else ClaudeLLM(settings)
# In-memory for now; swapping in a persistent checkpointer is the first step of pause/resume.
graph = build_graph(llm, checkpointer=InMemorySaver())
sync = SyncClient(settings.sync_http_url)

# One run per room at a time. In-memory, like the rest of Milestone 1.
active_rooms: set[str] = set()
# asyncio only keeps weak references to tasks; hold them so runs aren't garbage collected.
background_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await sync.aclose()


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.web_origin], allow_methods=["POST"], allow_headers=["*"])


class StartRunRequest(CamelModel):
    room: str = Field(min_length=1, max_length=100)
    task: str = Field(min_length=1, max_length=2000)
    started_by: str = Field(min_length=1, max_length=100)


@app.post("/runs", status_code=202)
async def start_run(req: StartRunRequest) -> dict:
    if req.room in active_rooms:
        raise HTTPException(409, "A run is already in progress in this room")
    # Claim the room before awaiting, so two simultaneous requests can't both start a run.
    active_rooms.add(req.room)

    run = RunInfo(task=req.task, started_by=req.started_by)
    try:
        await sync.send(req.room, {"type": "run_started", "run": run.dump()})
    except httpx2.HTTPError:
        active_rooms.discard(req.room)
        raise HTTPException(502, "Sync server unreachable")

    # Return immediately; clients watch progress through the shared doc, not this response.
    task = asyncio.create_task(run_task(graph, sync.send, req.room, run))
    background_tasks.add(task)

    def cleanup(t: asyncio.Task) -> None:
        background_tasks.discard(t)
        active_rooms.discard(req.room)

    task.add_done_callback(cleanup)
    return {"runId": run.id}


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "model": "mock" if settings.agent_mock_llm else settings.anthropic_model}
