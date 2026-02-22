#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import collections
import os
import re
import select
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config_editor import get_scenario_duration
from .models import Session, SessionStatus

# Paths (resolved relative to this file's location inside web_controller/)
_WEB_CONTROLLER_DIR = Path(__file__).parent
_LOCAL_RC_DIR = _WEB_CONTROLLER_DIR.parent          # this module's sibling dir
_HOME_RC_DIR  = Path.home() / "red-controller"      # standard deployed location

# Prefer the co-located venv; fall back to ~/red-controller/red_controller_venv
_LOCAL_VENV = _LOCAL_RC_DIR / "red_controller_venv" / "bin" / "python3"
_HOME_VENV  = _HOME_RC_DIR  / "red_controller_venv" / "bin" / "python3"

if _LOCAL_VENV.exists():
    _RED_CONTROLLER_DIR = _LOCAL_RC_DIR
    _VENV_PYTHON = _LOCAL_VENV
elif _HOME_VENV.exists():
    _RED_CONTROLLER_DIR = _HOME_RC_DIR
    _VENV_PYTHON = _HOME_VENV
else:
    _RED_CONTROLLER_DIR = _LOCAL_RC_DIR
    _VENV_PYTHON = Path(sys.executable)

RED_CONTROLLER_PATH = str(_RED_CONTROLLER_DIR / "red_controller.py")
SESSIONS_BASE_DIR = Path.home() / "red-controller" / "sessions"
VENV_PYTHON = str(_VENV_PYTHON)

LOG_RING_BUFFER_SIZE = 1000

# Watchdog: terminate process this many seconds after the scheduled end time.
# Accounts for the crawler's per-epoch sleep (epoch_delay_time=30s) and
# HTTP request timeouts (con_timeout=30s × up to 4 cheat-check requests).
_WATCHDOG_GRACE_SECONDS = 60

_ANSI_RE = re.compile(r'\033\[[0-9;]*[a-zA-Z]')
_STEP_RE = re.compile(r'\[\*\]\s+\d{8}T\d{6}Z:(.+)$')


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
        duration_minutes: int = 240,
    ):
        self.session_id = session_id
        self.learner_name = learner_name
        self.training_ip = training_ip
        self.control_ip = control_ip
        self.scenario = scenario
        self.process = process
        self.session_dir = session_dir
        self.duration_minutes = duration_minutes
        self.start_time = datetime.now(timezone.utc).isoformat()
        self.end_time: Optional[str] = None
        self.current_step: str = ""
        self.log_buffer: collections.deque = collections.deque(maxlen=LOG_RING_BUFFER_SIZE)
        self.sse_queues: list[asyncio.Queue] = []
        self._lock = threading.Lock()

    def _update_phase(self, line: str):
        if line == "__ZANSIN_SESSION_ENDED__":
            self.current_step = "完了"
            return
        clean = _ANSI_RE.sub('', line)
        m = _STEP_RE.search(clean)
        if m:
            self.current_step = m.group(1).strip()

    def add_log_line(self, line: str):
        with self._lock:
            self._update_phase(line)
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
            current_step=self.current_step,
            duration_minutes=self.duration_minutes,
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

        duration = get_scenario_duration(scenario)
        effective_duration = duration if duration is not None else 240

        cmd = [
            VENV_PYTHON,
            RED_CONTROLLER_PATH,
            "-n", learner_name,
            "-t", training_ip,
            "-c", control_ip,
            "-a", str(scenario),
        ]
        if duration is not None:
            cmd += ["-d", str(duration)]

        process = subprocess.Popen(
            cmd,
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
            duration_minutes=effective_duration,
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

        # Watchdog: force-terminate the process group if it overshoots the
        # scheduled duration.  The crawler only checks end_time at the top of
        # its epoch loop, so network timeouts can cause significant overshoot.
        wdog_delay = effective_duration * 60 + _WATCHDOG_GRACE_SECONDS
        wdog = threading.Timer(wdog_delay, self._kill_overrun, args=(info,))
        wdog.daemon = True
        wdog.start()

        return session_id

    def _kill_overrun(self, info: _SessionInfo):
        """SIGTERM → 30秒後に SIGKILL でフォールバック。"""
        if info.process.poll() is None:
            try:
                os.killpg(os.getpgid(info.process.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                return
            # SIGTERM が効かない場合のフォールバック
            followup = threading.Timer(30, self._force_kill, args=(info,))
            followup.daemon = True
            followup.start()

    def _force_kill(self, info: _SessionInfo):
        """SIGKILL で強制終了（最終手段）。"""
        if info.process.poll() is None:
            try:
                os.killpg(os.getpgid(info.process.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass

    def _read_process_output(self, info: _SessionInfo):
        try:
            while True:
                # 1秒タイムアウト付きでパイプを監視
                ready = select.select([info.process.stdout], [], [], 1.0)[0]
                if ready:
                    line = info.process.stdout.readline()
                    if not line:
                        break  # EOF（全プロセスがパイプを閉じた）
                    info.add_log_line(line.rstrip("\n"))
                elif info.process.poll() is not None:
                    # 親プロセスが終了済み → 孫プロセスがパイプを保持していても抜ける
                    break
        except Exception:
            pass
        finally:
            try:
                info.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
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
