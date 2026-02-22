#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WireGuard VPN utilities — dynamic per-learner client config generation."""
from pathlib import Path
from typing import Optional

_NUM_CLIENTS = 30
_WG_SERVER_DIR = Path("/etc/wireguard")
_CLIENT_DIR = Path.home() / "red-controller" / "wireguard" / "clients"
_CONTROL_IP_FILE = Path.home() / "red-controller" / "wireguard" / "control_ip.txt"
WG_PORT = 51820


def is_configured() -> bool:
    return (_WG_SERVER_DIR / "server_public.key").exists() and _CONTROL_IP_FILE.exists()


def get_server_public_key() -> str:
    p = _WG_SERVER_DIR / "server_public.key"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def get_control_ip() -> str:
    """Return the Control Server's public IP (written by wireguard_setup.sh)."""
    return _CONTROL_IP_FILE.read_text(encoding="utf-8").strip() if _CONTROL_IP_FILE.exists() else ""


def generate_client_conf(peer_id: str, training_ip: str) -> Optional[bytes]:
    """Dynamically generate a WireGuard client .conf using the stored private key.

    Combines: client private key + server public key + control IP + training IP.
    Returns None if peer_id is invalid or the private key file is missing.
    """
    valid_ids = [f"client{i}" for i in range(1, _NUM_CLIENTS + 1)]
    if peer_id not in valid_ids:
        return None

    priv_file = _CLIENT_DIR / f"{peer_id}_private.key"
    if not priv_file.exists():
        return None

    client_priv = priv_file.read_text(encoding="utf-8").strip()
    server_pub = get_server_public_key()
    control_ip = get_control_ip()
    client_ip = peer_id_to_ip(peer_id)

    conf = (
        f"[Interface]\n"
        f"Address = {client_ip}/32\n"
        f"PrivateKey = {client_priv}\n"
        f"DNS = 8.8.8.8\n"
        f"\n"
        f"[Peer]\n"
        f"PublicKey = {server_pub}\n"
        f"Endpoint = {control_ip}:{WG_PORT}\n"
        f"AllowedIPs = {training_ip}/32\n"
        f"PersistentKeepalive = 25\n"
    )
    return conf.encode("utf-8")


def peer_id_to_ip(peer_id: str) -> str:
    """Convert 'clientN' → '10.100.0.N+1'."""
    try:
        n = int(peer_id.replace("client", ""))
        return f"10.100.0.{n + 1}"
    except ValueError:
        return ""


def all_peer_ids() -> list[str]:
    return [f"client{i}" for i in range(1, _NUM_CLIENTS + 1)]
