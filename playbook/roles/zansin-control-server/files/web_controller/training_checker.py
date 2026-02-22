#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check and control services on the Training Machine via SSH (paramiko).

Default credentials match the intentional defaults documented in CLAUDE.md.
"""
import socket
from typing import Optional

import paramiko
import requests as _requests

VENDOR_USER = "vendor"
VENDOR_PASS = "Passw0rd!23"
GAME_API_DIR = "/home/vendor/game-api"

SERVICES: list[dict] = [
    {"name": "nginx",      "type": "http", "port": 80,   "container": None},
    {"name": "phpapi",     "type": "http", "port": 8080, "container": "phpapi"},
    {"name": "apidebug",   "type": "http", "port": 3000, "container": "apidebug"},
    {"name": "phpmyadmin", "type": "http", "port": 5555, "container": "phpmyadmin"},
    {"name": "mysql (db)", "type": "tcp",  "port": 3306, "container": "db"},
    {"name": "redis",      "type": "tcp",  "port": 6379, "container": "redis"},
]


# ── Port / HTTP reachability ───────────────────────────────────────────────────

def check_port(host: str, port: int, timeout: float = 3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def check_http(host: str, port: int, timeout: float = 3) -> bool:
    try:
        r = _requests.get(
            f"http://{host}:{port}/", timeout=timeout, allow_redirects=True
        )
        return r.status_code < 500
    except Exception:
        return False


# ── SSH helpers ───────────────────────────────────────────────────────────────

def _ssh_run(ip: str, password: str, cmd: str) -> tuple[str, str]:
    """Open SSH session, run cmd, return (stdout, stderr)."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(ip, username=VENDOR_USER, password=password, timeout=10)
        _, stdout, stderr = client.exec_command(cmd)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        return out, err
    finally:
        client.close()


def get_docker_status(ip: str, password: str) -> dict[str, str]:
    """Return {container_name: status_string} via SSH → docker ps."""
    out, _ = _ssh_run(
        ip, password,
        "docker ps -a --format '{{.Label \"com.docker.compose.service\"}}\t{{.Status}}'"
    )
    result: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2 and parts[0].strip():
            result[parts[0].strip()] = parts[1].strip()
    return result


# ── Public API ────────────────────────────────────────────────────────────────

def check_all(ip: str, password: str = VENDOR_PASS) -> list[dict]:
    """Return service status list for all defined services."""
    docker_error: Optional[str] = None
    docker_status: dict[str, str] = {}
    try:
        docker_status = get_docker_status(ip, password)
    except Exception as exc:
        docker_error = str(exc)

    results = []
    for svc in SERVICES:
        if svc["type"] == "http":
            reachable = check_http(ip, svc["port"])
        else:
            reachable = check_port(ip, svc["port"])

        container = svc["container"]
        if container is None:
            container_status = "N/A"
        elif docker_error:
            container_status = f"SSH error: {docker_error}"
        else:
            container_status = docker_status.get(container, "Not running")

        results.append(
            {
                "name": svc["name"],
                "port": svc["port"],
                "container": container,      # actual docker container name (or None)
                "reachable": reachable,
                "container_status": container_status,
            }
        )
    return results


def start_services(ip: str, password: str = VENDOR_PASS) -> str:
    """Run docker-compose up -d on the training machine."""
    out, err = _ssh_run(
        ip, password, f"cd {GAME_API_DIR} && docker-compose up -d 2>&1"
    )
    return (out + err).strip()


def stop_services(ip: str, password: str = VENDOR_PASS) -> str:
    """Run docker-compose down on the training machine."""
    out, err = _ssh_run(
        ip, password, f"cd {GAME_API_DIR} && docker-compose down 2>&1"
    )
    return (out + err).strip()


def restart_container(ip: str, container: str, password: str = VENDOR_PASS) -> str:
    """Restart a single container on the training machine."""
    out, err = _ssh_run(ip, password, f"docker restart {container} 2>&1")
    return (out + err).strip()
