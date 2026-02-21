#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import collections
import os
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import Session, SessionStatus

# Paths (resolved relative to this file's location inside web_controller/)
_WEB_CONTROLLER_DIR = Path(__file__).parent
_RED_CONTROLLER_DIR = _WEB_CONTROLLER_DIR.parent
RED_CONTROLLER_PATH = str(_RED_CONTROLLER_DIR / "red_controller.py")
SESSIONS_BASE_DIR = Path.home() / "red-controller" / "sessions"

# Prefer the virtualenv python when available
_VENV_PYTHON = _RED_CONTROLLER_DIR / "red_controller_venv" / "bin" / "python3"
VENV_PYTHON = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else sys.executable

LOG_RING_BUFFER_SIZE = 1000


class _SessionInfo:
    def __init__(
        self,
        session_id: str,
        learner_name: str,
        training_ip: str,
        control_ip: str,
        scenario: int,
        process: subprocess.Popen,
        session_dir: Path,
    ):
        self.session_id = session_id
        self.learner_name = learner_name
        self.training_ip = training_ip
        self.control_ip = control_ip
        self.scenario = scenario
        self.process = process
        self.session_dir = session_dir
        self.start_time = datetime.now(timezone.utc).isoformat()
        self.end_time: Optional[str] = None
        self.log_buffer: collections.deque = collections.deque(maxlen=LOG_RING_BUFFER_SIZE)
        self.sse_queues: list[asyncio.Queue] = []
        self._lock = threading.Lock()

    def add_log_line(self, line: str):
        with self._lock:
            self.log_buffer.append(line)
            for q in list(self.sse_queues):
                try:
                    q.put_nowait(line)
                except asyncio.QueueFull:
                    pass

    def register_sse_queue(self, q: asyncio.Queue):
        with self._lock:
            self.sse_queues.append(q)

    def unregister_sse_queue(self, q: asyncio.Queue):
        with self._lock:
            try:
                self.sse_queues.remove(q)
            except ValueError:
                pass

    def get_log_history(self) -> list[str]:
        with self._lock:
            return list(self.log_buffer)

    def to_session(self) -> Session:
        proc = self.process
        status = SessionStatus.RUNNING if proc.poll() is None else SessionStatus.FINISHED
        return Session(
            session_id=self.session_id,
            learner_name=self.learner_name,
            training_ip=self.training_ip,
            control_ip=self.control_ip,
            scenario=self.scenario,
            status=status,
            start_time=self.start_time,
            end_time=self.end_time,
            pid=proc.pid if proc.poll() is None else None,
        )


class SessionManager:
    def __init__(self):
        self._sessions: dict[str, _SessionInfo] = {}
        self._lock = threading.Lock()

    def start_session(
        self,
        learner_name: str,
        training_ip: str,
        control_ip: str,
        scenario: int,
    ) -> str:
        session_id = str(uuid.uuid4())
        session_dir = SESSIONS_BASE_DIR / session_id / "sqlite3"
        session_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["ZANSIN_SESSION_DIR"] = str(session_dir)

        process = subprocess.Popen(
            [
                VENV_PYTHON,
                RED_CONTROLLER_PATH,
                "-n", learner_name,
                "-t", training_ip,
                "-c", control_ip,
                "-a", str(scenario),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(_RED_CONTROLLER_DIR),
            env=env,
            start_new_session=True,   # puts process in its own process group
        )

        info = _SessionInfo(
            session_id=session_id,
            learner_name=learner_name,
            training_ip=training_ip,
            control_ip=control_ip,
            scenario=scenario,
            process=process,
            session_dir=session_dir,
        )

        with self._lock:
            self._sessions[session_id] = info

        # Background thread: read stdout → ring buffer + SSE queues
        t = threading.Thread(
            target=self._read_process_output,
            args=(info,),
            daemon=True,
        )
        t.start()

        return session_id

    def _read_process_output(self, info: _SessionInfo):
        try:
            for line in info.process.stdout:
                line = line.rstrip("\n")
                info.add_log_line(line)
        except Exception:
            pass
        finally:
            info.process.wait()
            info.end_time = datetime.now(timezone.utc).isoformat()
            # Signal all SSE consumers that the stream ended
            info.add_log_line("__ZANSIN_SESSION_ENDED__")

    def stop_session(self, session_id: str) -> bool:
        with self._lock:
            info = self._sessions.get(session_id)
        if info is None:
            return False
        if info.process.poll() is not None:
            return False
        try:
            os.killpg(os.getpgid(info.process.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        return True

    def get_session(self, session_id: str) -> Optional[Session]:
        with self._lock:
            info = self._sessions.get(session_id)
        if info is None:
            return None
        return info.to_session()

    def get_all_sessions(self) -> list[Session]:
        with self._lock:
            infos = list(self._sessions.values())
        return [i.to_session() for i in infos]

    def get_session_info(self, session_id: str) -> Optional[_SessionInfo]:
        with self._lock:
            return self._sessions.get(session_id)

    def get_log_history(self, session_id: str) -> Optional[list[str]]:
        with self._lock:
            info = self._sessions.get(session_id)
        if info is None:
            return None
        return info.get_log_history()

    async def stream_logs(self, session_id: str):
        """Async generator that yields log lines for SSE."""
        with self._lock:
            info = self._sessions.get(session_id)
        if info is None:
            return

        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        # First send history
        history = info.get_log_history()
        for line in history:
            if line == "__ZANSIN_SESSION_ENDED__":
                yield line
                return
            yield line

        # Then subscribe to new lines
        info.register_sse_queue(q)
        try:
            while True:
                try:
                    line = await asyncio.wait_for(q.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield ":keepalive"
                    continue
                if line == "__ZANSIN_SESSION_ENDED__":
                    yield line
                    break
                yield line
        finally:
            info.unregister_sse_queue(q)


# Global singleton
manager = SessionManager()
