#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Manage ansible-playbook execution with SSE log streaming.

Enabled only when the ZANSIN_REPO_DIR environment variable points to a
repository checkout that contains playbook/inventory.ini.
"""
import asyncio
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Optional

# Repo root injected by web_controller.sh (empty string on control server)
_REPO_DIR: str = os.environ.get("ZANSIN_REPO_DIR", "")
_INVENTORY: Optional[Path] = (
    Path(_REPO_DIR) / "playbook" / "inventory.ini" if _REPO_DIR else None
)
_GAMESERVERS: Optional[Path] = (
    Path(_REPO_DIR) / "playbook" / "game-servers.yml" if _REPO_DIR else None
)

# ── Availability ───────────────────────────────────────────────────────────────

def check_availability() -> dict:
    """Return {available, reasons} for diagnostics."""
    reasons = []
    if not _REPO_DIR:
        reasons.append(
            "ZANSIN_REPO_DIR 未設定（リポジトリルートから ./web_controller.sh start で起動してください）"
        )
    elif not _INVENTORY or not _INVENTORY.exists():
        reasons.append(
            f"playbook/inventory.ini が見つかりません ({_INVENTORY})"
        )
    if not shutil.which("ansible-playbook"):
        reasons.append(
            "ansible-playbook が PATH にありません（sudo apt install ansible）"
        )
    return {"available": len(reasons) == 0, "reasons": reasons}


def is_available() -> bool:
    """Setup tab enabled only when running from repo with ansible installed."""
    return check_availability()["available"]


# ── Config read/write ─────────────────────────────────────────────────────────

def read_config() -> dict:
    """Read training_ips and control_ip from inventory.ini (section-based parsing)."""
    content = _INVENTORY.read_text(encoding="utf-8")
    section = None
    training_ips: list[str] = []
    control_ip = ""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped
        elif section == "[training-machine]" and stripped:
            training_ips.append(stripped)
        elif section == "[zansin-control-server]" and stripped:
            control_ip = stripped
    return {"training_ips": training_ips, "control_ip": control_ip}


def write_config(training_ips: list[str], control_ip: str, password: str) -> None:
    """Persist IPs to inventory.ini and password to game-servers.yml."""
    inv_lines = ["[training-machine]"]
    inv_lines += [ip for ip in training_ips if ip.strip()]
    inv_lines += ["", "[zansin-control-server]", control_ip, ""]
    _INVENTORY.write_text("\n".join(inv_lines), encoding="utf-8")

    # game-servers.yml: update ansible_ssh_pass and ansible_become_password
    content = _GAMESERVERS.read_text(encoding="utf-8")
    content = re.sub(
        r"(ansible_ssh_pass:\s*).*", rf"\g<1>{password}", content
    )
    content = re.sub(
        r"(ansible_become_password:\s*).*", rf"\g<1>{password}", content
    )
    _GAMESERVERS.write_text(content, encoding="utf-8")


# ── Process state ──────────────────────────────────────────────────────────────

_setup_proc: Optional[subprocess.Popen] = None
_setup_log: list[str] = []
_setup_lock = threading.Lock()
_setup_sse_queues: list[asyncio.Queue] = []

_ENDED = "__SETUP_ENDED__"


def run_playbook(scope: str) -> bool:
    """Launch ansible-playbook in a background thread.

    scope: 'all' | 'training_only'
    Returns False if a run is already in progress.
    """
    global _setup_proc, _setup_log
    with _setup_lock:
        if _setup_proc and _setup_proc.poll() is None:
            return False  # already running
        _setup_log = []
        cmd = ["ansible-playbook", "-i", "inventory.ini", "game-servers.yml"]
        if scope == "training_only":
            cmd += ["--skip-tags", "zansin-control-server"]
        _setup_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(Path(_REPO_DIR) / "playbook"),
        )
    threading.Thread(target=_read_setup_output, daemon=True).start()
    return True


def _read_setup_output() -> None:
    """Background thread: read process stdout → buffer + SSE queues."""
    try:
        for line in _setup_proc.stdout:
            line = line.rstrip("\n")
            with _setup_lock:
                _setup_log.append(line)
                for q in list(_setup_sse_queues):
                    try:
                        q.put_nowait(line)
                    except Exception:
                        pass
    finally:
        _setup_proc.wait()
        with _setup_lock:
            _setup_log.append(_ENDED)
            for q in list(_setup_sse_queues):
                try:
                    q.put_nowait(_ENDED)
                except Exception:
                    pass


def get_status() -> dict:
    p = _setup_proc
    if p is None:
        return {"running": False, "returncode": None}
    rc = p.poll()
    return {"running": rc is None, "returncode": rc}


def get_log_history() -> list[str]:
    with _setup_lock:
        return list(_setup_log)


# ── SSE async generator ────────────────────────────────────────────────────────

async def stream_logs():
    """Async generator yielding log lines for SSE (same pattern as session_manager)."""
    q: asyncio.Queue = asyncio.Queue(maxsize=500)

    # Replay history first
    history = get_log_history()
    for line in history:
        if line == _ENDED:
            yield line
            return
        yield line

    # Subscribe to live output
    with _setup_lock:
        _setup_sse_queues.append(q)
    try:
        while True:
            try:
                line = await asyncio.wait_for(q.get(), timeout=30.0)
            except asyncio.TimeoutError:
                yield ":keepalive"
                continue
            if line == _ENDED:
                yield line
                break
            yield line
    finally:
        with _setup_lock:
            try:
                _setup_sse_queues.remove(q)
            except ValueError:
                pass
