#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from enum import Enum
from typing import Optional
from pydantic import BaseModel


class SessionStatus(str, Enum):
    RUNNING = "running"
    FINISHED = "finished"


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
