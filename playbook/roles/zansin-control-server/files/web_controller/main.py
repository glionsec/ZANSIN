#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ZANSIN Web Controller — FastAPI entry point.

Run with:
    uvicorn web_controller.main:app --host 0.0.0.0 --port 8888 --workers 1
"""
import asyncio
import mimetypes
from pathlib import Path
from typing import AsyncGenerator, Optional

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .auth import (
    authenticate, create_session, delete_user, get_current_user, get_session,
    get_user, invalidate_session, list_users, create_user, require_admin,
    update_user_peer,
)
from .config_editor import (
    delete_scenario, get_action_descriptions, get_all_scenarios,
    get_available_actions, get_next_scenario_num, get_scenario_duration,
    get_scenario_names, save_scenario, save_scenario_duration, save_scenario_name,
)
from .db_reader import get_comparison, get_ranking, build_session_score
from .models import (
    LoginRequest, LoginResponse, PeerAssign, ScenarioCreate, ScenarioUpdate,
    SessionCreate, SetupConfig, TrainingAction, UserCreate, UserInfo,
    VpnPeer, VpnStatus,
)
from . import vpn_manager
from .session_manager import manager
from . import setup_runner
from . import training_checker

_STATIC_DIR = Path(__file__).parent / "static"
_WEB_CONTROLLER_DIR = Path(__file__).parent


def _find_docs_dir() -> Path:
    candidates = [
        Path.home() / "red-controller" / "documents",          # deployed
        _WEB_CONTROLLER_DIR.parent.parent.parent.parent.parent / "documents",  # repo root (dev)
        _WEB_CONTROLLER_DIR.parent.parent / "documents",        # fallback
    ]
    for p in candidates:
        if p.is_dir():
            return p
    raise HTTPException(status_code=503, detail="Documents directory not found")


def _find_images_dir() -> Path:
    candidates = [
        Path.home() / "red-controller" / "images",                              # deployed
        _WEB_CONTROLLER_DIR.parent.parent.parent.parent.parent / "images",      # repo root (dev)
        _WEB_CONTROLLER_DIR.parent.parent / "images",                           # fallback
    ]
    for p in candidates:
        if p.is_dir():
            return p
    raise HTTPException(status_code=503, detail="Images directory not found")



app = FastAPI(title="ZANSIN Web Controller", version="1.0.0")


# ── Static files ──────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def root():
    return FileResponse(str(_STATIC_DIR / "index.html"))


# Serve static/ for JS/CSS assets if needed
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ── Authentication ────────────────────────────────────────────────────────────

@app.post("/auth/login")
def login(body: LoginRequest, response: Response):
    role = authenticate(body.username, body.password)
    if role is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_session(body.username, role)
    response.set_cookie(
        "zansin_session", token,
        httponly=True, samesite="strict", max_age=86400,
    )
    return LoginResponse(username=body.username, role=role)


@app.post("/auth/logout")
def logout(response: Response, zansin_session: Optional[str] = Cookie(default=None)):
    if zansin_session:
        invalidate_session(zansin_session)
    response.delete_cookie("zansin_session")
    return {"status": "logged out"}


@app.get("/auth/me")
def me(user: dict = Depends(get_current_user)):
    return {"username": user["username"], "role": user["role"]}


# ── Session management ────────────────────────────────────────────────────────

@app.get("/api/sessions")
def list_sessions(user: dict = Depends(get_current_user)):
    return manager.get_all_sessions()


@app.post("/api/sessions", status_code=201)
def create_session_endpoint(body: SessionCreate, user: dict = Depends(require_admin)):
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
def get_session_endpoint(session_id: str, user: dict = Depends(get_current_user)):
    session = manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    score = build_session_score(session)
    return score


@app.delete("/api/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, user: dict = Depends(require_admin)):
    session = manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    manager.stop_session(session_id)
    return Response(status_code=204)


# ── Logs ──────────────────────────────────────────────────────────────────────

@app.get("/api/sessions/{session_id}/logs/history")
def log_history(session_id: str, user: dict = Depends(get_current_user)):
    lines = manager.get_log_history(session_id)
    if lines is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"lines": lines}


@app.get("/api/sessions/{session_id}/logs/stream")
async def log_stream(session_id: str, user: dict = Depends(get_current_user)):
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
def ranking(user: dict = Depends(get_current_user)):
    return get_ranking()


@app.get("/api/comparison")
def comparison(user: dict = Depends(get_current_user)):
    return get_comparison()


# ── Scenario editing ──────────────────────────────────────────────────────────

@app.get("/api/scenario")
def get_scenarios(user: dict = Depends(get_current_user)):
    all_scenarios = get_all_scenarios()
    return {str(k): [s.model_dump() for s in v] for k, v in all_scenarios.items()}


@app.post("/api/scenario", status_code=200)
def update_scenario(body: ScenarioUpdate, user: dict = Depends(require_admin)):
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
def get_actions(user: dict = Depends(get_current_user)):
    return {
        "actions": get_available_actions(),
        "descriptions": get_action_descriptions(),
    }


@app.get("/api/scenario/meta")
def get_scenario_meta(user: dict = Depends(get_current_user)):
    """Return {str(num): {name, step_count, duration_minutes}} for all scenarios."""
    all_sc = get_all_scenarios()
    names = get_scenario_names()
    all_nums = sorted(set(all_sc.keys()) | set(names.keys()))
    return {
        str(n): {
            "name": names.get(n, f"シナリオ {n}"),
            "step_count": len(all_sc.get(n, [])),
            "duration_minutes": get_scenario_duration(n),  # None = global default
        }
        for n in all_nums
    }


@app.post("/api/scenario/create", status_code=201)
def create_scenario(body: ScenarioCreate, user: dict = Depends(require_admin)):
    import re
    # --- Validation: check duration against max step delay ---
    if body.duration_minutes is not None:
        if body.copy_from is not None:
            source_steps = get_all_scenarios().get(body.copy_from, [])
        else:
            source_steps = []
        if source_steps:
            max_delay = max(int(s.delay) for s in source_steps)
            if body.duration_minutes < max_delay:
                worst = max(source_steps, key=lambda s: int(s.delay))
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"指定した演習時間 ({body.duration_minutes} 分) は"
                        f"最も遅い攻撃ステップ「{worst.step_id}」"
                        f"(遅延 {max_delay} 分) より短いため無効です。"
                        f"演習時間は {max_delay} 分以上に設定してください。"
                    ),
                )
    # --- Create scenario ---
    new_num = get_next_scenario_num()
    if body.copy_from is not None:
        all_sc = get_all_scenarios()
        source_steps = all_sc.get(body.copy_from, [])
        new_steps = []
        for s in source_steps:
            new_id = re.sub(r"^\d+", str(new_num), s.step_id)
            new_steps.append(s.model_copy(update={"step_id": new_id}))
        save_scenario(new_num, new_steps)
    else:
        save_scenario(new_num, [])
    save_scenario_name(new_num, body.name)
    if body.duration_minutes is not None:
        save_scenario_duration(new_num, body.duration_minutes)
    return {"scenario": new_num, "name": body.name, "status": "created"}


@app.delete("/api/scenario/{num}", status_code=200)
def remove_scenario(num: int, user: dict = Depends(require_admin)):
    running = [s for s in manager.get_all_sessions() if s.status.value == "running"]
    if running:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete scenario while sessions are running",
        )
    try:
        delete_scenario(num)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "deleted", "scenario": num}


# ── Documents ─────────────────────────────────────────────────────────────────

@app.get("/api/docs")
def list_docs(user: dict = Depends(get_current_user)):
    """Return list of files under documents/ (including subdirectories)."""
    docs_dir = _find_docs_dir()
    files = []
    for p in sorted(docs_dir.rglob("*")):
        if p.is_file():
            rel = p.relative_to(docs_dir)
            files.append({
                "path": str(rel).replace("\\", "/"),
                "name": p.name,
                "size": p.stat().st_size,
                "directory": str(rel.parent).replace("\\", "/") if rel.parent != Path(".") else "",
            })
    return {"files": files}


@app.get("/api/docs/{file_path:path}/content")
def get_doc_content(file_path: str, user: dict = Depends(get_current_user)):
    """Return raw file content as JSON (for Markdown viewer)."""
    docs_dir = _find_docs_dir()
    try:
        target = (docs_dir / file_path).resolve()
        target.relative_to(docs_dir.resolve())  # path traversal prevention
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=415, detail="Binary file cannot be previewed")
    return {"filename": target.name, "content": content}


@app.get("/api/docs/{file_path:path}")
def download_doc(file_path: str, user: dict = Depends(get_current_user)):
    """Download a file from the documents/ directory."""
    docs_dir = _find_docs_dir()
    # Prevent path traversal
    try:
        target = (docs_dir / file_path).resolve()
        docs_dir_resolved = docs_dir.resolve()
        target.relative_to(docs_dir_resolved)  # raises ValueError if outside
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    mime, _ = mimetypes.guess_type(str(target))
    return FileResponse(
        str(target),
        media_type=mime or "application/octet-stream",
        filename=target.name,
    )


# ── User management ───────────────────────────────────────────────────────────

@app.get("/api/admin/users")
def admin_list_users(user: dict = Depends(require_admin)):
    return list_users()


@app.post("/api/admin/users", status_code=201)
def admin_create_user(body: UserCreate, user: dict = Depends(require_admin)):
    ok = create_user(body.username, body.password, body.role.value)
    if not ok:
        raise HTTPException(status_code=409, detail="Username already exists")
    return {"username": body.username, "role": body.role}


@app.delete("/api/admin/users/{username}", status_code=204)
def admin_delete_user(username: str, user: dict = Depends(require_admin)):
    if username == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete the admin user")
    ok = delete_user(username)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return Response(status_code=204)


# ── VPN management ────────────────────────────────────────────────────────────

@app.get("/api/vpn/status")
def vpn_status(user: dict = Depends(require_admin)):
    configured = vpn_manager.is_configured()
    server_pub = vpn_manager.get_server_public_key()
    endpoint = f"{vpn_manager.get_control_ip()}:{vpn_manager.WG_PORT}" if configured else ""

    # Build peer → assigned user and training_ip mappings
    users = list_users()
    peer_to_user: dict[str, str] = {
        u["wg_peer"]: u["username"] for u in users if u.get("wg_peer")
    }
    peer_to_training_ip: dict[str, str] = {
        u["wg_peer"]: u["training_ip"] for u in users if u.get("wg_peer") and u.get("training_ip")
    }

    peers = [
        VpnPeer(
            peer_id=pid,
            ip_address=vpn_manager.peer_id_to_ip(pid),
            assigned_to=peer_to_user.get(pid),
            training_ip=peer_to_training_ip.get(pid),
        )
        for pid in vpn_manager.all_peer_ids()
    ]

    return VpnStatus(
        configured=configured,
        server_public_key=server_pub,
        endpoint=endpoint,
        subnet="10.100.0.0/24",
        peers=peers,
    )


@app.post("/api/vpn/peers/{peer_id}/assign", status_code=200)
def vpn_assign_peer(peer_id: str, body: PeerAssign, user: dict = Depends(require_admin)):
    if peer_id not in vpn_manager.all_peer_ids():
        raise HTTPException(status_code=404, detail="Peer not found")

    users = list_users()

    if body.username is None:
        # Unassign: clear whoever currently holds this peer (also clear training_ip)
        for u in users:
            if u.get("wg_peer") == peer_id:
                update_user_peer(u["username"], None, None)
        return {"status": "unassigned", "peer_id": peer_id}

    # Validate target user exists
    target = get_user(body.username)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Clear old assignment for this peer from any previous holder
    for u in users:
        if u.get("wg_peer") == peer_id and u["username"] != body.username:
            update_user_peer(u["username"], None, None)

    ok = update_user_peer(body.username, peer_id, body.training_ip)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "assigned", "peer_id": peer_id, "username": body.username, "training_ip": body.training_ip}


@app.get("/api/vpn/peers/{peer_id}/download")
def vpn_download_peer_conf(peer_id: str, user: dict = Depends(require_admin)):
    if not vpn_manager.is_configured():
        raise HTTPException(status_code=503, detail="WireGuard not configured")
    # Find the training_ip for the user assigned to this peer
    rec = next((u for u in list_users() if u.get("wg_peer") == peer_id), None)
    training_ip = rec.get("training_ip") if rec else None
    if not training_ip:
        raise HTTPException(status_code=409, detail="Training IP not assigned to this peer")
    data = vpn_manager.generate_client_conf(peer_id, training_ip)
    if data is None:
        raise HTTPException(status_code=404, detail="Client key not found")
    return Response(
        content=data,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{peer_id}.conf"'},
    )


@app.get("/api/vpn/myconfig")
def vpn_my_config(user: dict = Depends(get_current_user)):
    rec = get_user(user["username"])
    wg_peer = rec.get("wg_peer") if rec else None
    if not wg_peer:
        raise HTTPException(status_code=403, detail="No VPN peer assigned to your account")
    training_ip = rec.get("training_ip") if rec else None
    if not training_ip:
        raise HTTPException(status_code=409, detail="Training IP not assigned to your peer")
    data = vpn_manager.generate_client_conf(wg_peer, training_ip)
    if data is None:
        raise HTTPException(status_code=404, detail="Client key not found")
    fname = f"zansin-vpn-{user['username']}.conf"
    return Response(
        content=data,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.get("/api/images/{file_path:path}")
def serve_image(file_path: str, user: dict = Depends(get_current_user)):
    """Serve image files referenced in Markdown documents."""
    images_dir = _find_images_dir()
    try:
        target = (images_dir / file_path).resolve()
        target.relative_to(images_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    mime, _ = mimetypes.guess_type(str(target))
    return FileResponse(str(target), media_type=mime or "application/octet-stream")


# ── Setup (ansible-playbook) ──────────────────────────────────────────────────

@app.get("/api/setup/available")
def setup_available(user: dict = Depends(require_admin)):
    return setup_runner.check_availability()


@app.get("/api/setup/config")
def get_setup_config(user: dict = Depends(require_admin)):
    if not setup_runner.is_available():
        raise HTTPException(status_code=503, detail="Setup unavailable in this mode")
    return setup_runner.read_config()


@app.post("/api/setup/run", status_code=202)
def run_setup(body: SetupConfig, user: dict = Depends(require_admin)):
    if not setup_runner.is_available():
        raise HTTPException(status_code=503, detail="Setup unavailable in this mode")
    setup_runner.write_config(body.training_ips, body.control_ip, body.password)
    started = setup_runner.run_playbook(body.scope)
    if not started:
        raise HTTPException(status_code=409, detail="Setup already running")
    return {"status": "started"}


@app.get("/api/setup/status")
def get_setup_status(user: dict = Depends(require_admin)):
    return setup_runner.get_status()


@app.get("/api/setup/stream")
async def setup_stream(user: dict = Depends(require_admin)):
    """Server-Sent Events stream for ansible-playbook output."""
    async def event_generator() -> AsyncGenerator[str, None]:
        async for line in setup_runner.stream_logs():
            if line == ":keepalive":
                yield ":keepalive\n\n"
            elif line == "__SETUP_ENDED__":
                yield "event: end\ndata: setup finished\n\n"
                break
            else:
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


# ── Training machine monitoring ───────────────────────────────────────────────

@app.get("/api/training/status")
def training_status(ip: str, password: str = "Passw0rd!23", user: dict = Depends(require_admin)):
    try:
        services = training_checker.check_all(ip, password)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"services": services}


@app.post("/api/training/start")
def training_start(body: TrainingAction, user: dict = Depends(require_admin)):
    try:
        output = training_checker.start_services(body.training_ip, body.password)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"output": output}


@app.post("/api/training/stop")
def training_stop(body: TrainingAction, user: dict = Depends(require_admin)):
    try:
        output = training_checker.stop_services(body.training_ip, body.password)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"output": output}


@app.post("/api/training/restart")
def training_restart(body: TrainingAction, user: dict = Depends(require_admin)):
    if not body.container:
        raise HTTPException(status_code=422, detail="container is required")
    try:
        output = training_checker.restart_container(
            body.training_ip, body.container, body.password
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"output": output}
