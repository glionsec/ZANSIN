#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Authentication and session management for ZANSIN Web Controller."""
import hashlib
import json
import secrets
import threading as _threading
import time
from pathlib import Path
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, status

_USERS_FILE = Path(__file__).parent / "users.json"
_users_lock = _threading.Lock()
# sessions: {token: {"username": str, "role": str, "expires": float}}
_sessions: dict[str, dict] = {}
SESSION_TTL = 86400  # 24 hours


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode()).hexdigest()


def load_users() -> list[dict]:
    if not _USERS_FILE.exists():
        return []
    return json.loads(_USERS_FILE.read_text(encoding="utf-8"))


def authenticate(username: str, password: str) -> Optional[str]:
    """Return role ("admin" / "trainee") on success, None on failure."""
    for u in load_users():
        if u["username"] == username:
            parts = u["password"].split(":")  # "sha256:<salt>:<hash>"
            if len(parts) == 3 and parts[0] == "sha256":
                if _hash_password(password, parts[1]) == parts[2]:
                    return u["role"]
    return None


def create_session(username: str, role: str) -> str:
    token = secrets.token_hex(32)
    _sessions[token] = {
        "username": username,
        "role": role,
        "expires": time.time() + SESSION_TTL,
    }
    return token


def get_session(token: str) -> Optional[dict]:
    s = _sessions.get(token)
    if s and s["expires"] > time.time():
        return s
    _sessions.pop(token, None)
    return None


def invalidate_session(token: str) -> None:
    _sessions.pop(token, None)


# ── FastAPI dependencies ───────────────────────────────────────────────────────

def get_current_user(zansin_session: Optional[str] = Cookie(default=None)) -> dict:
    if not zansin_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    s = get_session(zansin_session)
    if not s:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    return s


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


# ── User CRUD ─────────────────────────────────────────────────────────────────

def _write_users(users: list) -> None:
    """Write users list to users.json (caller must hold _users_lock)."""
    _USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")


def list_users() -> list[dict]:
    """Return [{username, role, wg_peer, training_ip}] for all users."""
    return [
        {
            "username": u["username"],
            "role": u["role"],
            "wg_peer": u.get("wg_peer"),
            "training_ip": u.get("training_ip"),
        }
        for u in load_users()
    ]


def create_user(username: str, password: str, role: str) -> bool:
    """Add a new user to users.json. Returns False if username already exists."""
    with _users_lock:
        users = load_users()
        if any(u["username"] == username for u in users):
            return False
        salt = secrets.token_hex(16)
        users.append({
            "username": username,
            "password": f"sha256:{salt}:{_hash_password(password, salt)}",
            "role": role,
            "wg_peer": None,
            "training_ip": None,
        })
        _write_users(users)
    return True


def delete_user(username: str) -> bool:
    """Remove a user from users.json. Returns False if user does not exist."""
    with _users_lock:
        users = load_users()
        filtered = [u for u in users if u["username"] != username]
        if len(filtered) == len(users):
            return False
        _write_users(filtered)
    return True


def update_user_peer(username: str, peer_id: Optional[str], training_ip: Optional[str] = None) -> bool:
    """Set or clear the wg_peer and training_ip fields for a user. Returns False if user not found."""
    with _users_lock:
        users = load_users()
        for u in users:
            if u["username"] == username:
                u["wg_peer"] = peer_id
                u["training_ip"] = training_ip
                _write_users(users)
                return True
    return False


def get_user(username: str) -> Optional[dict]:
    """Return the full user record, or None if not found."""
    for u in load_users():
        if u["username"] == username:
            return u
    return None
