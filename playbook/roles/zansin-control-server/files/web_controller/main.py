#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ZANSIN Web Controller — FastAPI entry point.

Run with:
    uvicorn web_controller.main:app --host 0.0.0.0 --port 8888 --workers 1
"""
import asyncio
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config_editor import get_all_scenarios, get_available_actions, save_scenario
from .db_reader import get_comparison, get_ranking, build_session_score
from .models import ScenarioUpdate, SessionCreate
from .session_manager import manager

_STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="ZANSIN Web Controller", version="1.0.0")


# ── Static files ──────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def root():
    return FileResponse(str(_STATIC_DIR / "index.html"))


# Serve static/ for JS/CSS assets if needed
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ── Session management ────────────────────────────────────────────────────────

@app.get("/api/sessions")
def list_sessions():
    return manager.get_all_sessions()


@app.post("/api/sessions", status_code=201)
def create_session(body: SessionCreate):
    try:
        session_id = manager.start_session(
            learner_name=body.learner_name,
            training_ip=body.training_ip,
            control_ip=body.control_ip,
            scenario=body.scenario,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"session_id": session_id}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    session = manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    score = build_session_score(session)
    return score


@app.delete("/api/sessions/{session_id}", status_code=204)
def delete_session(session_id: str):
    session = manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    manager.stop_session(session_id)
    return Response(status_code=204)


# ── Logs ──────────────────────────────────────────────────────────────────────

@app.get("/api/sessions/{session_id}/logs/history")
def log_history(session_id: str):
    lines = manager.get_log_history(session_id)
    if lines is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"lines": lines}


@app.get("/api/sessions/{session_id}/logs/stream")
async def log_stream(session_id: str):
    """Server-Sent Events log stream."""
    session = manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    async def event_generator() -> AsyncGenerator[str, None]:
        async for line in manager.stream_logs(session_id):
            if line == ":keepalive":
                yield ":keepalive\n\n"
            elif line == "__ZANSIN_SESSION_ENDED__":
                yield "event: end\ndata: session finished\n\n"
                break
            else:
                # Escape newlines within a single SSE data field
                safe = line.replace("\n", " ")
                yield f"data: {safe}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Ranking & comparison ──────────────────────────────────────────────────────

@app.get("/api/ranking")
def ranking():
    return get_ranking()


@app.get("/api/comparison")
def comparison():
    return get_comparison()


# ── Scenario editing ──────────────────────────────────────────────────────────

@app.get("/api/scenario")
def get_scenarios():
    all_scenarios = get_all_scenarios()
    return {str(k): [s.model_dump() for s in v] for k, v in all_scenarios.items()}


@app.post("/api/scenario", status_code=200)
def update_scenario(body: ScenarioUpdate):
    # Refuse if any session is currently running
    running = [s for s in manager.get_all_sessions() if s.status.value == "running"]
    if running:
        raise HTTPException(
            status_code=409,
            detail="Cannot edit scenario while sessions are running",
        )
    try:
        save_scenario(body.scenario, body.steps)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "saved"}


@app.get("/api/scenario/actions")
def get_actions():
    return {"actions": get_available_actions()}
