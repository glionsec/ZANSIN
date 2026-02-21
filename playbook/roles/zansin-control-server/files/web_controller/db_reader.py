#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read per-session SQLite databases to extract scores and metrics."""
import sqlite3
from pathlib import Path
from typing import Optional

from .models import Session, SessionScore, SessionStatus
from .session_manager import SESSIONS_BASE_DIR, manager


def _get_sqlite_dir(session_id: str) -> Path:
    return SESSIONS_BASE_DIR / session_id / "sqlite3"


def get_technical_point(session_id: str) -> Optional[float]:
    db_path = _get_sqlite_dir(session_id) / "judge.db"
    if not db_path.exists():
        return None
    try:
        with sqlite3.connect(str(db_path), timeout=5) as conn:
            cursor = conn.execute(
                "SELECT technical_point FROM JudgeAttackTBL ORDER BY id DESC LIMIT 1"
            )
            row = cursor.fetchone()
            return float(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


def get_operation_ratio(session_id: str, learner_name: str) -> Optional[float]:
    db_path = _get_sqlite_dir(session_id) / f"crawler_{learner_name}.db"
    if not db_path.exists():
        return None
    try:
        with sqlite3.connect(str(db_path), timeout=5) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM GameStatusTBL WHERE learner_name = ?",
                (learner_name,),
            )
            total_row = cursor.fetchone()
            total = total_row[0] if total_row else 0
            if total == 0:
                return None

            cursor = conn.execute(
                "SELECT COUNT(*) FROM GameStatusTBL WHERE learner_name = ? AND is_cheat = 0 AND error = 0",
                (learner_name,),
            )
            ok_row = cursor.fetchone()
            ok = ok_row[0] if ok_row else 0
            return round(ok / total * 100, 1)
    except Exception:
        return None


def get_cheat_count(session_id: str, learner_name: str) -> int:
    db_path = _get_sqlite_dir(session_id) / f"crawler_{learner_name}.db"
    if not db_path.exists():
        return 0
    try:
        with sqlite3.connect(str(db_path), timeout=5) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM GameStatusTBL WHERE learner_name = ? AND is_cheat = 1",
                (learner_name,),
            )
            row = cursor.fetchone()
            return row[0] if row else 0
    except Exception:
        return 0


def get_avg_charge(session_id: str, learner_name: str) -> Optional[float]:
    db_path = _get_sqlite_dir(session_id) / f"crawler_{learner_name}.db"
    if not db_path.exists():
        return None
    try:
        with sqlite3.connect(str(db_path), timeout=5) as conn:
            cursor = conn.execute(
                "SELECT AVG(charge_amount) FROM GameStatusTBL WHERE learner_name = ?",
                (learner_name,),
            )
            row = cursor.fetchone()
            if row and row[0] is not None:
                return round(float(row[0]), 1)
            return None
    except Exception:
        return None


def build_session_score(session: Session) -> SessionScore:
    return SessionScore(
        session_id=session.session_id,
        learner_name=session.learner_name,
        training_ip=session.training_ip,
        scenario=session.scenario,
        technical_point=get_technical_point(session.session_id),
        operation_ratio=get_operation_ratio(session.session_id, session.learner_name),
        status=session.status,
        start_time=session.start_time,
        end_time=session.end_time,
    )


def get_ranking() -> list[SessionScore]:
    sessions = manager.get_all_sessions()
    scores = [build_session_score(s) for s in sessions]
    # Sort: finished sessions with scores first (desc), then running, then no score
    def sort_key(sc: SessionScore):
        tp = sc.technical_point if sc.technical_point is not None else -1
        return (0 if sc.status == SessionStatus.FINISHED else 1, -tp)

    return sorted(scores, key=sort_key)


def get_comparison() -> dict:
    sessions = manager.get_all_sessions()
    result = []
    for s in sessions:
        score = build_session_score(s)
        result.append({
            "session_id": s.session_id,
            "learner_name": s.learner_name,
            "training_ip": s.training_ip,
            "scenario": s.scenario,
            "status": s.status.value,
            "start_time": s.start_time,
            "end_time": s.end_time,
            "technical_point": score.technical_point,
            "operation_ratio": score.operation_ratio,
            "cheat_count": get_cheat_count(s.session_id, s.learner_name),
            "avg_charge": get_avg_charge(s.session_id, s.learner_name),
        })
    return {"sessions": result}
