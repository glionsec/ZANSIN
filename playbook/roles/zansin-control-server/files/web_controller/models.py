#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel


class SessionStatus(str, Enum):
    RUNNING = "running"
    FINISHED = "finished"


class UserRole(str, Enum):
    ADMIN = "admin"
    TRAINEE = "trainee"


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    username: str
    role: UserRole


class SessionCreate(BaseModel):
    learner_name: str
    training_ip: str
    control_ip: str
    scenario: int


class Session(BaseModel):
    session_id: str
    learner_name: str
    training_ip: str
    control_ip: str
    scenario: int
    status: SessionStatus
    start_time: str
    end_time: Optional[str] = None
    pid: Optional[int] = None
    current_step: str = ""
    duration_minutes: int = 240


class SessionScore(BaseModel):
    session_id: str
    learner_name: str
    training_ip: str
    scenario: int
    technical_point: Optional[float] = None
    operation_ratio: Optional[float] = None
    status: SessionStatus
    start_time: str
    end_time: Optional[str] = None


class ScenarioStep(BaseModel):
    step_id: str       # e.g. "1-001"
    delay: str         # minutes as string, e.g. "001"
    action: str        # e.g. "nmap"
    cheat_count: str   # e.g. "0"


class ScenarioUpdate(BaseModel):
    scenario: int
    steps: list[ScenarioStep]


class ScenarioCreate(BaseModel):
    name: str
    copy_from: Optional[int] = None   # scenario num to clone; None = empty
    duration_minutes: Optional[int] = None  # None = use global default (240)


class SetupConfig(BaseModel):
    training_ips: List[str]
    control_ip: str
    password: str
    scope: str = "training_only"   # "all" | "training_only"


class TrainingAction(BaseModel):
    training_ip: str
    password: str = "Passw0rd!23"
    container: Optional[str] = None  # required for restart


# ── User management models ─────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    password: str
    role: UserRole


class UserInfo(BaseModel):
    username: str
    role: UserRole
    wg_peer: Optional[str] = None
    training_ip: Optional[str] = None


# ── VPN models ────────────────────────────────────────────────────────────────

class PeerAssign(BaseModel):
    username: Optional[str] = None      # None = unassign
    training_ip: Optional[str] = None  # Training Machine IP for this learner


class VpnPeer(BaseModel):
    peer_id: str
    ip_address: str                     # WireGuard VPN IP (10.100.0.x)
    assigned_to: Optional[str] = None  # username
    training_ip: Optional[str] = None  # Training Machine physical IP


class VpnStatus(BaseModel):
    configured: bool
    server_public_key: str
    endpoint: str    # "<CONTROL_IP>:51820"
    subnet: str      # "10.100.0.0/24"
    peers: List[VpnPeer]
