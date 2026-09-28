from contextlib import asynccontextmanager

import httpx2
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import Field

from app.config import settings
from app.events import CamelModel
from app.graph import build_graph
from app.llm import ClaudeLLM, MockLLM
from app.runs import Conflict, NotFound, RunManager
from app.sync_client import SyncClient

sync = SyncClient(settings.sync_http_url)
manager: RunManager  # created in lifespan, once the checkpointer is open


@asynccontextmanager
async def lifespan(_: FastAPI):
    global manager
    settings.checkpoint_db.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_db)) as checkpointer:
        llm = MockLLM() if settings.agent_mock_llm else ClaudeLLM(settings)
        manager = RunManager(build_graph(llm, checkpointer=checkpointer), sync.send)
        yield
    await sync.aclose()


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.web_origin], allow_methods=["POST"], allow_headers=["*"])


@app.exception_handler(Conflict)
async def conflict_handler(_: Request, exc: Conflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(httpx2.HTTPError)
async def sync_error_handler(_: Request, exc: httpx2.HTTPError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": "Sync server unreachable"})


@app.exception_handler(NotFound)
async def not_found_handler(_: Request, exc: NotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


class StartRunRequest(CamelModel):
    room: str = Field(min_length=1, max_length=100)
    task: str = Field(min_length=1, max_length=2000)
    started_by: str = Field(min_length=1, max_length=100)


class CommandRequest(CamelModel):
    by: str = Field(min_length=1, max_length=100)


class ApprovalRequest(CommandRequest):
    # The expected state: which pending tool call this decision is for.
    approval_id: str
    approved: bool
    reason: str | None = Field(default=None, max_length=500)


@app.post("/runs", status_code=202)
async def start_run(req: StartRunRequest) -> dict:
    # Return immediately; clients watch progress through the shared doc, not this response.
    return {"runId": await manager.start(req.room, req.task, req.started_by)}


# Commands return as soon as they're accepted; their effects arrive through the doc.
@app.post("/runs/{run_id}/pause", status_code=202)
async def pause_run(run_id: str, req: CommandRequest) -> dict:
    await manager.pause(run_id, req.by)
    return {"ok": True}


@app.post("/runs/{run_id}/resume", status_code=202)
async def resume_run(run_id: str, req: CommandRequest) -> dict:
    await manager.resume(run_id, req.by)
    return {"ok": True}


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "model": "mock" if settings.agent_mock_llm else settings.anthropic_model}


@app.post("/runs/{run_id}/approval", status_code=202)
async def decide_approval(run_id: str, req: ApprovalRequest) -> dict:
    await manager.decide(run_id, req.by, req.approval_id, req.approved, req.reason)
    return {"ok": True}
