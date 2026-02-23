#!/bin/bash
# ZANSIN Web Controller management script
# Usage: ./web_controller.sh [start|stop|restart|status]
#        Default subcommand is "start".

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT=8888
# Pattern used to identify the uvicorn process
_PROC_PATTERN="uvicorn web_controller.main:app"

# このスクリプトはリポジトリが存在する Controller マシン上で実行される
export ZANSIN_REPO_DIR="$SCRIPT_DIR"
_WEB_FILES_DIR="$SCRIPT_DIR/playbook/roles/zansin-control-server/files"
_VENV_DIR="$SCRIPT_DIR/.web_venv"
_UVICORN="$_VENV_DIR/bin/uvicorn"
_WORKDIR="$_WEB_FILES_DIR"
_APT_UPDATED=0   # apt-get update を初回インストール前に一度だけ実行するフラグ

# ── System dependency checks ──────────────────────────────────────────────────

# 指定 apt パッケージが未インストールなら自動インストールを試みる
_ensure_apt_pkg() {
    local pkg="$1"
    if dpkg -s "$pkg" &>/dev/null; then
        return 0
    fi
    if [ "$_APT_UPDATED" -eq 0 ]; then
        echo "[ZANSIN] Updating package cache..."
        sudo apt-get update -qq
        _APT_UPDATED=1
    fi
    echo "[ZANSIN] Required package '$pkg' is not installed. Attempting to install..."
    if sudo apt-get install -y "$pkg" 2>/dev/null; then
        echo "[ZANSIN] '$pkg' installed successfully."
    else
        echo "[ZANSIN] ERROR: Failed to install '$pkg'."
        echo "[ZANSIN] Please run manually: sudo apt-get install -y $pkg"
        exit 1
    fi
}

# zansin ユーザーが存在しなければ作成して sudo グループに追加する
_ensure_zansin_user() {
    if id zansin &>/dev/null; then
        return 0
    fi
    echo "[ZANSIN] User 'zansin' does not exist. Creating..."
    sudo useradd -m zansin
    sudo usermod -aG sudo zansin
    echo "[ZANSIN] User 'zansin' created."
    # パスワードを対話で取得して設定（確認入力一致まで繰り返す）
    local pw1 pw2
    while true; do
        read -r -s -p "[ZANSIN] Set password for 'zansin': " pw1; echo
        read -r -s -p "[ZANSIN] Confirm password: " pw2; echo
        if [ "$pw1" = "$pw2" ] && [ -n "$pw1" ]; then
            break
        elif [ -z "$pw1" ]; then
            echo "[ZANSIN] Password cannot be empty. Please try again."
        else
            echo "[ZANSIN] Passwords do not match. Please try again."
        fi
    done
    echo "zansin:$pw1" | sudo chpasswd
    echo "[ZANSIN] Password set for 'zansin'."
}

# start 前に必要なシステムパッケージを確認・インストール
check_deps() {
    _ensure_apt_pkg python3-venv   # venv 作成に必須（Ubuntu 22.04 は未搭載）
    _ensure_apt_pkg lsof           # ポート競合検出に必須（Ubuntu 22.04 は未搭載）
    _ensure_apt_pkg ansible        # Setup Runner 機能に必須
    _ensure_apt_pkg openssh-server # Requirements.md: SSH 接続に必須
    _ensure_zansin_user            # Requirements.md: zansin ユーザーアカウントに必須
}

# ── Helpers ───────────────────────────────────────────────────────────────────

# PIDs of processes matching our uvicorn pattern
_proc_pids() {
    pgrep -f "$_PROC_PATTERN" 2>/dev/null | tr '\n' ' ' | xargs || true
}

# PIDs of processes *listening* on our port (excludes client connections)
_port_pids() {
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null | tr '\n' ' ' | xargs || true
}

# One-line description of a PID: "PID cmd..."
_pid_info() {
    ps -p "$1" -o pid=,comm=,cmd= 2>/dev/null | head -1 || echo "$1 (unknown)"
}

# ── Subcommand implementations ────────────────────────────────────────────────

do_start() {
    check_deps

    # Pre-flight: ensure port is free before launching
    local port_pids
    port_pids=$(_port_pids)
    if [ -n "$port_pids" ]; then
        echo "[ZANSIN] ERROR: Port $PORT is already in use."
        for pid in $port_pids; do
            echo "  $(  _pid_info "$pid")"
        done
        echo "[ZANSIN] Run '$(basename "$0") stop' to free the port, or resolve the conflict above."
        exit 1
    fi

    if [ ! -x "$_VENV_DIR/bin/pip" ]; then
        echo "[ZANSIN] Creating Python venv at $_VENV_DIR ..."
        rm -rf "$_VENV_DIR"
        if ! python3 -m venv "$_VENV_DIR"; then
            echo "[ZANSIN] ERROR: Failed to create Python virtualenv at $_VENV_DIR."
            exit 1
        fi
    fi
    echo "[ZANSIN] Syncing Python packages ..."
    if ! "$_VENV_DIR/bin/pip" install -q -r "$_WEB_FILES_DIR/requirements.txt"; then
        echo "[ZANSIN] ERROR: Failed to install Python packages from requirements.txt."
        exit 1
    fi

    # wireguard keys are always in the deployed /opt/zansin path, regardless of who runs this script
    export ZANSIN_WG_DIR="/opt/zansin/red-controller/wireguard"
    export ZANSIN_RC_DIR="/opt/zansin/red-controller"

    echo "[ZANSIN] Starting Web Controller — http://0.0.0.0:$PORT"

    cd "$_WORKDIR"
    # sg は /etc/group を直接参照するため、usermod -aG 直後でも再ログインなしでグループが有効化される
    if ! id -Gn | grep -qw zansin && getent group zansin 2>/dev/null | grep -qw "$(id -un)"; then
        echo "[ZANSIN] Activating zansin group via sg (no re-login needed)..."
        exec sg zansin -c "$(printf '%q ' "$_UVICORN" web_controller.main:app \
            --host 0.0.0.0 --port "$PORT" --workers 1)"
    else
        exec "$_UVICORN" web_controller.main:app \
            --host 0.0.0.0 --port "$PORT" --workers 1
    fi
}

do_stop() {
    local proc_pids
    proc_pids=$(_proc_pids)

    if [ -z "$proc_pids" ]; then
        echo "[ZANSIN] Web Controller is not running (pattern not matched)."
        return
    fi

    # Separate pids we own from pids owned by others
    local own_pids="" other_pids=""
    local me; me=$(id -un)
    for pid in $proc_pids; do
        local owner; owner=$(ps -p "$pid" -o user= 2>/dev/null | xargs || true)
        if [ "$owner" = "$me" ] || [ "$(id -u)" = "0" ]; then
            own_pids="$own_pids $pid"
        else
            other_pids="$other_pids $pid"
            echo "[ZANSIN] PID $pid is owned by '$owner' — cannot kill without sudo."
        fi
    done

    # If we found pids owned by other users and this script wasn't run with sudo,
    # suggest retrying with sudo.
    if [ -n "$other_pids" ]; then
        echo "[ZANSIN] Hint: run 'sudo $(basename "$0") stop' to stop all processes."
    fi

    if [ -z "$own_pids" ]; then
        return
    fi

    # Send SIGTERM to our processes and wait up to 5 s
    kill $own_pids 2>/dev/null || true
    local waited=0
    while [ "$waited" -lt 10 ] && [ -n "$(_proc_pids)" ]; do
        sleep 0.5
        waited=$((waited + 1))
    done

    if [ -z "$(_proc_pids)" ]; then
        echo "[ZANSIN] Web Controller stopped (was PID:$own_pids)."
    else
        echo "[ZANSIN] SIGTERM ignored — sending SIGKILL to PID:$own_pids."
        kill -9 $own_pids 2>/dev/null || true
        sleep 0.3
        echo "[ZANSIN] Done."
    fi

    # Report if port is still occupied by something unrelated
    local port_pids
    port_pids=$(_port_pids)
    if [ -n "$port_pids" ]; then
        echo "[ZANSIN] WARNING: Port $PORT is still in use — not killed (not our process):"
        for pid in $port_pids; do
            echo "  $(_pid_info "$pid")"
        done
    fi
}

do_status() {
    local proc_pids port_pids
    proc_pids=$(_proc_pids)
    port_pids=$(_port_pids)

    if [ -n "$proc_pids" ]; then
        echo "[ZANSIN] Web Controller is running (PID: $proc_pids, port: $PORT)"
    else
        echo "[ZANSIN] Web Controller is not running."
    fi

    if [ -n "$port_pids" ] && [ "$port_pids" != "$proc_pids" ]; then
        echo "[ZANSIN] Port $PORT is held by:"
        for pid in $port_pids; do
            echo "  $(_pid_info "$pid")"
        done
    elif [ -z "$port_pids" ]; then
        echo "[ZANSIN] Port $PORT is free."
    fi
}

do_restart() {
    do_stop
    sleep 1
    do_start
}

usage() {
    echo "Usage: $(basename "$0") [start|stop|restart|status]"
    echo "  start   — Start the web controller (default)"
    echo "  stop    — Stop the running web controller"
    echo "  restart — Stop then start"
    echo "  status  — Show process and port state"
    exit 1
}

# ── Dispatch ──────────────────────────────────────────────────────────────────
case "${1:-start}" in
    start)   do_start   ;;
    stop)    do_stop    ;;
    restart) do_restart ;;
    status)  do_status  ;;
    *)       usage      ;;
esac
