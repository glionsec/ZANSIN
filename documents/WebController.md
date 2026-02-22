# ZANSIN Web Controller

The ZANSIN Web Controller is a browser-based interface for the Red Controller.
It allows instructors to run exercises for multiple learners simultaneously, monitor logs in real time, compare scores, edit attack scenarios, manage VPN peers, and provision machines — all without using the command line.

---

## Architecture

```
[Browser]  ←HTTP/SSE→  [Web Controller :8888]  ←subprocess→  [red_controller.py]
                              │
                              ├── auth.py              (authentication + user CRUD)
                              ├── session_manager.py   (process lifecycle + log streaming)
                              ├── db_reader.py          (reads per-session SQLite)
                              ├── config_editor.py      (reads/writes attack_config.ini)
                              ├── vpn_manager.py        (WireGuard config generation)
                              ├── setup_runner.py       (ansible-playbook execution + SSE)
                              └── training_checker.py   (SSH-based service monitoring)
```

- **Backend**: FastAPI + Server-Sent Events (SSE)
- **Frontend**: Single-page HTML with Vanilla JS and Tailwind CSS (CDN, no build step)
- **Port**: 8888 (on the Control Server)
- **Session isolation**: Each learner's exercise runs as a separate process; SQLite databases are stored in `/opt/zansin/red-controller/sessions/<session-id>/sqlite3/`

---

## Prerequisites

> [!IMPORTANT]
> The Web Controller runs **on the Control Server**, which must be provisioned first via the ZANSIN Ansible playbook.
> You cannot test it on a local development machine without deploying first.

Required before proceeding:

- Both machines (Control Server and Training Machine) are provisioned via `zansin.sh` / Ansible.
- You can SSH into the Control Server as the `zansin` user.
- `/opt/zansin/red-controller/` exists on the Control Server (created by Ansible).

---

## Authentication

### Login

When you open `http://<control-server-ip>:8888`, a login overlay is displayed.
Enter your username and password to proceed. Credentials are validated against `users.json` on the Control Server.

- **Endpoint**: `POST /auth/login`
- **Session cookie**: `zansin_session` (HTTP-only, SameSite=Strict, 24-hour TTL)
- **Logout**: Click the logout button in the top-right corner, or `POST /auth/logout`

### Roles and Permissions

| Tab | admin | trainee |
|-----|-------|---------|
| Exercise Management | ✅ Start / Stop | 👁 View only |
| Real-time Monitor | ✅ | ✅ |
| Ranking & Comparison | ✅ | ✅ |
| Scenario Editor | ✅ | ❌ Hidden |
| Setup | ✅ | ❌ Hidden |
| Training Machine | ✅ | ❌ Hidden |
| Documents | ✅ | ✅ |
| VPN Management | ✅ | ❌ Hidden |

### Default Credentials

| Username | Password | Role |
|----------|----------|------|
| `admin` | `admin` | admin |
| `trainee` | `trainee` | trainee |

> [!WARNING]
> Change the default passwords before running any real exercises.
> See the [User Management](#user-management) section below.

### Password Storage

Passwords are stored in `users.json` as `sha256:<salt>:<hash>`:

```
sha256:<16-byte-hex-salt>:<sha256(salt + password)>
```

To change a password, use the User Management API (admin only) or edit `users.json` directly and restart the service.

---

## Deployment

### Via Web UI — Setup Tab (Recommended)

**The easiest way to provision ZANSIN is directly from the browser.**

1. Run `./web_controller.sh` on the machine where the repository is checked out.
2. Open `http://localhost:8888` and log in (default: `admin` / `admin`).
3. Go to **Tab 5 (Setup)**.
4. Enter the Training Machine IP(s), Control Server IP, and SSH password.
5. Select provisioning scope (**All** or **Training only**) and click **▶ Run Ansible**.

Ansible runs and WireGuard is configured automatically — no terminal interaction required.

> [!NOTE]
> `./web_controller.sh` must be running **before** you open the browser. Ansible must also be installed on the same machine. See [Starting and Stopping the Service](#starting-and-stopping-the-service) below.

### Alternative: zansin.sh (headless / no local browser)

Use this when you cannot run a browser locally (CI pipeline, remote-only environment):

```bash
chmod +x zansin.sh
./zansin.sh
```

The script performs these steps in order:

1. Provisions the Training Machine via Ansible.
2. Transfers all files to the Control Server via `rsync` (including `web_controller/` and `documents/`).
3. Creates the Python virtualenv and runs `pip install` (including `fastapi` and `uvicorn`).
4. Creates the `sessions/` directory.
5. Runs `wireguard_setup.sh` to generate WireGuard server keys.
6. Registers and starts the `zansin-web-controller` systemd service.

After `zansin.sh` completes, the Web Controller is running and enabled on the Control Server.

### Manual (re-deploy specific parts)

SSH into the Control Server as `zansin`, then:

```bash
# 1. Transfer files from the repo to the Control Server
rsync -avz playbook/roles/zansin-control-server/files/. zansin@<control-ip>:/opt/zansin/red-controller/
rsync -avz documents/ zansin@<control-ip>:/opt/zansin/red-controller/documents/

# 2. Install dependencies on the Control Server
source /opt/zansin/red-controller/red_controller_venv/bin/activate
pip install -r /opt/zansin/red-controller/requirements.txt
deactivate

mkdir -p /opt/zansin/red-controller/sessions

# 3. Register and start the systemd service
sudo tee /etc/systemd/system/zansin-web-controller.service > /dev/null << 'EOF'
[Unit]
Description=ZANSIN Web Controller
After=network.target

[Service]
Type=simple
User=zansin
WorkingDirectory=/opt/zansin/red-controller
ExecStart=/opt/zansin/red-controller/red_controller_venv/bin/uvicorn web_controller.main:app --host 0.0.0.0 --port 8888 --workers 1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now zansin-web-controller
```

---

## Starting and Stopping the Service

### After Deployment

After deployment (via the Setup tab or `zansin.sh`), the Web Controller is started automatically by systemd and enabled on boot. No manual action is required.

### Checking Status / Troubleshooting (systemd)

```bash
# Check status
sudo systemctl status zansin-web-controller

# View logs (follow)
sudo journalctl -u zansin-web-controller -f

# Restart if needed
sudo systemctl restart zansin-web-controller
```

These commands are for status checks and troubleshooting only. The service starts on boot automatically once enabled by Ansible.

### For Re-provisioning: web_controller.sh

`web_controller.sh` is a script in the repository root that starts the Web Controller from your local machine (where the repo is checked out). It is **required** if you want to use the [Setup tab](#tab-5--setup) to run Ansible playbooks from the browser.

```bash
# Start (default)
./web_controller.sh

# or explicitly:
./web_controller.sh start

# Stop the running instance
./web_controller.sh stop

# Stop then start
./web_controller.sh restart

# Show process and port state
./web_controller.sh status
```

What `web_controller.sh start` does:

1. Creates `.web_venv/` in the repo root (if it does not exist) and installs `requirements.txt`.
2. Sets environment variables:
   - `ZANSIN_REPO_DIR` — repo root path (enables the Setup tab)
   - `ZANSIN_WG_DIR=/opt/zansin/red-controller/wireguard` — WireGuard key directory
   - `ZANSIN_RC_DIR=/opt/zansin/red-controller` — deployed Red Controller path
3. Launches `uvicorn` via `sg zansin -c "..."` so that the `zansin` group is active immediately after `usermod -aG zansin ubuntu` (no re-login required).

> [!NOTE]
> `web_controller.sh` listens on the same port 8888. Stop the systemd service first if it is running, or there will be a port conflict.

---

## Accessing the Web UI

Open a browser and navigate to:

```
http://<control-server-ip>:8888
```

> [!NOTE]
> Port 8888 must be reachable from the instructor's machine.
> If the Control Server has a firewall, open the port:
> ```bash
> sudo ufw allow 8888/tcp
> ```

---

## UI Overview (8 Tabs)

| # | Tab | Access |
|---|-----|--------|
| 1 | Exercise Management | All users |
| 2 | Real-time Monitor | All users |
| 3 | Ranking & Comparison | All users |
| 4 | Scenario Editor | Admin only |
| 5 | Setup | Admin only |
| 6 | Training Machine | Admin only |
| 7 | Documents | All users |
| 8 | VPN Management | Admin only |

---

### Tab 1 — Exercise Management

Start, monitor, and stop exercises for multiple learners.

| Field | Description |
|-------|-------------|
| Learner Name | Identifier used for logs and scoring (e.g. `learnerA`) |
| Training IP | IP address of the learner's Training Machine |
| Control IP | IP address of this Control Server |
| Scenario | Select from the configured scenarios (default: `0`=Dev, `1`=Hardest, `2`=Medium) |

Click **▶ Start** to launch the exercise. It will appear in the session list below.

- **● Running** — exercise is in progress.
- **■ Finished** — exercise has ended; Technical Point and Operation Ratio are shown.
- **■ Stop** — sends SIGTERM to the exercise process.

> [!NOTE]
> Only admin users can start or stop sessions. Trainee users can view the session list but cannot start or stop exercises.

---

### Tab 2 — Real-time Monitor

View live log output from one or more exercise sessions side by side.

1. Select a session from the dropdown and click **+ Add**.
2. Logs stream automatically via SSE.
3. Toggle **Auto-scroll** per pane as needed.
4. Close individual panes with ✕.

Log lines are color-coded:

| Color | Tag | Meaning |
|-------|-----|---------|
| Green | `[*]` | Success / OK |
| Blue | `[+]` | Info / Note |
| Red | `[-]` | Failure |
| Yellow | `[!]` | Warning |

---

### Tab 3 — Ranking & Comparison

Available after one or more exercises have finished.

**Ranking table** — learners sorted by Technical Point (descending). Medals 🥇🥈🥉 are shown for the top three.

**Comparison table** — side-by-side detail for all learners:

| Metric | Source |
|--------|--------|
| Technical Point | `JudgeAttackTBL` in `judge.db` |
| Operation Ratio | `GameStatusTBL` in `crawler_<name>.db` |
| Scenario | Session metadata |
| Cheat detection count | `GameStatusTBL.is_cheat` |
| Average charge per epoch | `GameStatusTBL.charge_amount` |

Click **↻ Refresh** to reload after a session ends.

---

### Tab 4 — Scenario Editor

Edit `attack_config.ini` directly from the browser. *(Admin only)*

1. Select a scenario from the list.
2. Edit step IDs, delay times, actions, and cheat counts inline. Hover over an action name to see a tooltip description.
3. Add steps with **+ Add Step**; remove with **✕**.
4. Click **💾 Save** to write the changes to `attack_config.ini`.
5. Use **+ New Scenario** to create a new scenario (optionally copying from an existing one).
6. Use **🗑 Delete** to remove a scenario.

> [!WARNING]
> Saving and deleting are blocked (HTTP 409) while any session is running.
> Stop all running exercises before editing.

---

### Tab 5 — Setup

Run the ZANSIN Ansible playbook directly from the browser. *(Admin only)*

**Availability requirements** (both must be true):
- The Web Controller was started via `./web_controller.sh` (which sets `ZANSIN_REPO_DIR`).
- `ansible-playbook` is available in PATH on the machine running `web_controller.sh`.

If either condition is not met, the tab displays a diagnostic message explaining why Setup is unavailable.

**How to use:**

1. Enter the Training Machine IP(s), Control Server IP, and SSH password.
2. Select the provisioning scope:
   - **All** — provisions both the Training Machine and the Control Server.
   - **Training only** — provisions only the Training Machine (skips `zansin-control-server` role).
3. Click **▶ Run Ansible** to start the playbook.
4. Ansible output streams in real time via SSE.

> [!NOTE]
> The Setup tab is intentionally unavailable when the Web Controller is running under systemd, because in that mode `ZANSIN_REPO_DIR` is not set. Use `web_controller.sh` from your local machine if you need to re-provision via the browser.

---

### Tab 6 — Training Machine

Monitor and control the services running on a Training Machine via SSH. *(Admin only)*

Enter the Training Machine IP and click **🔍 Check** to connect and retrieve service status.

**Monitored services:**

| Service | Port | Check method | Docker container |
|---------|------|--------------|-----------------|
| nginx | 80 | HTTP | — (host process) |
| phpapi | 8080 | HTTP | `phpapi` |
| apidebug | 3000 | HTTP | `apidebug` |
| phpmyadmin | 5555 | HTTP | `phpmyadmin` |
| mysql (db) | 3306 | TCP | `db` |
| redis | 6379 | TCP | `redis` |

**Actions:**

| Button | Action |
|--------|--------|
| **▶ Start All** | Runs `docker-compose up -d` on the Training Machine |
| **■ Stop All** | Runs `docker-compose down` on the Training Machine |
| **↺ Restart** (per row) | Runs `docker restart <container>` for that service |

SSH credentials used: `vendor` / `Passw0rd!23` (the intentional default from CLAUDE.md).

---

### Tab 7 — Documents

Browse and read the ZANSIN documentation in the browser. *(All users)*

- **File list** — displays all files under `documents/` on the Control Server.
  - Click a `.md` file to render it as formatted Markdown.
  - Switch between **EN** (English) and **JA** (Japanese) versions using the language buttons.
  - Click **⬇ Download** to save any file locally.
- **Image support** — images referenced from Markdown (via `/api/images/`) are served from the `images/` directory alongside `documents/`.
- **Reload** — click the refresh button (↺) to re-fetch the file list.

---

### Tab 8 — VPN Management

Manage WireGuard VPN peers and assign them to learners. *(Admin only)*

#### Network Overview

```
[Learner laptop]  ──WireGuard──▶  [Control Server :51820 UDP]  ──SSH/HTTP──▶  [Training Machine]
10.100.0.2–31                          10.100.0.1                              <training_ip>
```

- **Subnet**: `10.100.0.0/24`
- **Server IP**: `10.100.0.1` (Control Server's WireGuard address)
- **Client IPs**: `10.100.0.2` – `10.100.0.31` (client1 – client30)
- **Port**: UDP 51820
- **Routing**: Split tunnel — only traffic to the learner's specific Training Machine IP is routed through the VPN.

#### Prerequisites

WireGuard keys are generated automatically as part of the Ansible deployment (Setup tab or `zansin.sh`). No manual step is required.

If keys need to be regenerated manually (e.g., after a Control Server IP change):

```bash
bash /opt/zansin/red-controller/wireguard_setup.sh <control-server-ip>
```

This regenerates server and client key pairs under `/opt/zansin/red-controller/wireguard/`.

#### Assigning a VPN Peer

1. The **Users** table shows all registered users with their current peer assignment.
2. The **Peers** table shows all 30 WireGuard peers (`client1`–`client30`) and their assignment status.
3. To assign a peer:
   - Select the username from the dropdown in the peer row.
   - Enter the **Training IP** (the IP of the learner's Training Machine).
   - Click **Assign**.
4. To unassign: select "— unassign —" from the dropdown and click **Assign**.

#### Downloading a Client Configuration

Once a peer has a Training IP assigned, click **⬇ Download** in the peer row to download the `.conf` file.

The configuration is generated on demand by combining:
- Client private key (from `wireguard/clients/<peer-id>_private.key`)
- Server public key (from `wireguard/server_public.key`)
- Control Server IP (from `wireguard/control_ip.txt`)
- Training Machine IP (from the peer assignment)

Learners can also download their own config (if assigned) via **My VPN Config** at the top of the tab.

#### Installing the Configuration (Learner Side)

```bash
# Install WireGuard
sudo apt install wireguard

# Place the .conf file
sudo cp client1.conf /etc/wireguard/zansin.conf

# Activate
sudo wg-up zansin     # bring up
sudo wg-down zansin   # bring down
```

Or import the `.conf` file into the WireGuard GUI app on Windows/macOS.

---

## User Management

*(Admin only — managed from the VPN Management tab's Users section)*

### Creating a User (Web UI)

1. Open **Tab 8 (VPN Management)** and scroll to the **User Management** section.
2. Enter the username, password, and role.
3. Click **＋ Create**.

### Deleting a User (Web UI)

1. Open **Tab 8 (VPN Management)** and find the user in the users table.
2. Click the **[Delete]** button in the user's row.

> [!NOTE]
> The `admin` user cannot be deleted.

### Alternative: API (CLI)

Use the following `curl` commands when scripting or when the Web UI is not accessible.

**Adding a user:**

```bash
# First, get a session cookie (replace admin/admin with actual credentials)
curl -s -c /tmp/z.cookie -X POST http://<control-ip>:8888/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}'

# Create a trainee user
curl -s -b /tmp/z.cookie -X POST http://<control-ip>:8888/api/admin/users \
  -H "Content-Type: application/json" \
  -d '{"username":"learnerA","password":"<password>","role":"trainee"}'
```

**Deleting a user:**

```bash
curl -s -b /tmp/z.cookie -X DELETE http://<control-ip>:8888/api/admin/users/learnerA
```

### users.json Structure

```json
[
  {
    "username": "admin",
    "password": "sha256:<salt>:<hash>",
    "role": "admin"
  },
  {
    "username": "trainee",
    "password": "sha256:<salt>:<hash>",
    "role": "trainee",
    "wg_peer": null,
    "training_ip": null
  }
]
```

| Field | Description |
|-------|-------------|
| `username` | Login name |
| `password` | `sha256:<16-char-hex-salt>:<sha256-hex-hash>` |
| `role` | `"admin"` or `"trainee"` |
| `wg_peer` | Assigned WireGuard peer ID (e.g. `"client1"`), or `null` |
| `training_ip` | Training Machine IP for VPN routing, or `null` |

---

## File Structure

```
/opt/zansin/red-controller/              ← deployed on Control Server
├── red_controller.py                    ← CLI entry point
├── config.ini
├── requirements.txt                     ← fastapi, uvicorn, paramiko added
├── users.json                           ← user credentials (auto-created)
├── attack/
│   └── attack_config.ini               ← edited via Scenario tab
├── crawler/
│   └── crawler_sql.py                  ← ZANSIN_SESSION_DIR aware
├── judge/
│   └── judge_sql.py                    ← ZANSIN_SESSION_DIR aware
├── sessions/                           ← created at runtime
│   └── <session-id>/
│       └── sqlite3/
│           ├── judge.db
│           └── crawler_<name>.db
├── wireguard/                          ← created by wireguard_setup.sh
│   ├── server_public.key
│   ├── control_ip.txt
│   └── clients/
│       ├── client1_private.key
│       ├── client1_public.key
│       └── ... (up to client30)
├── documents/                          ← synced from repo by zansin.sh
│   ├── WebController.md
│   └── ja/
│       └── WebController_ja.md
└── web_controller/
    ├── main.py                          ← FastAPI entry point
    ├── models.py                        ← Pydantic models
    ├── auth.py                          ← authentication + user CRUD
    ├── session_manager.py               ← session lifecycle + log streaming
    ├── db_reader.py                     ← SQLite score reader
    ├── config_editor.py                 ← scenario config read/write
    ├── vpn_manager.py                   ← WireGuard config generation
    ├── setup_runner.py                  ← ansible-playbook runner + SSE
    ├── training_checker.py              ← SSH-based service monitor
    └── static/
        └── index.html                   ← 8-tab single-page frontend
```

---

## Verification Checklist

After deployment, confirm each item:

```bash
# 1. Service is running
sudo systemctl status zansin-web-controller
# Expected: Active: active (running)

# 2. Port is listening
ss -tlnp | grep 8888
# Expected: 0.0.0.0:8888

# 3. Unauthenticated request is rejected
curl -s -o /dev/null -w "%{http_code}" http://localhost:8888/api/sessions
# Expected: 401

# 4. Login and get session cookie
curl -s -c /tmp/z.cookie -X POST http://localhost:8888/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}'
# Expected: {"username":"admin","role":"admin"}

# 5. Authenticated API call succeeds
curl -s -b /tmp/z.cookie http://localhost:8888/api/sessions
# Expected: [] (empty list on first run)

# 6. Session directory exists
ls /opt/zansin/red-controller/sessions/
# Expected: directory exists (may be empty)

# 7. VPN configuration status
curl -s -b /tmp/z.cookie http://localhost:8888/api/vpn/status
# Expected: {"configured": true, ...}  (if wireguard_setup.sh was run)

# 8. Setup tab availability (only works via web_controller.sh, not systemd)
curl -s -b /tmp/z.cookie http://localhost:8888/api/setup/available
# Expected via web_controller.sh: {"available": true, "reasons": []}
# Expected via systemd:           {"available": false, "reasons": ["ZANSIN_REPO_DIR 未設定..."]}
```

### Test: Launch a session via API

```bash
curl -s -b /tmp/z.cookie -X POST http://localhost:8888/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"learner_name":"test","training_ip":"<training-ip>","control_ip":"<control-ip>","scenario":0}'
# Expected: {"session_id":"<uuid>"}
```

### Test: Confirm SQLite isolation

```bash
ls /opt/zansin/red-controller/sessions/
# Each session_id directory should appear here

ls /opt/zansin/red-controller/sessions/<session-id>/sqlite3/
# Expected: judge.db and/or crawler_test.db appear once the exercise starts
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `http://<ip>:8888` not reachable | Port blocked by firewall | `sudo ufw allow 8888/tcp` |
| Service fails to start | `fastapi`/`uvicorn` not installed | Re-run Ansible or `pip install -r requirements.txt` |
| Login screen does not go away | Cookie not set or session expired | Clear browser cookies; check that the browser accepts cookies from port 8888 |
| HTTP 401 on all API calls | Not logged in or cookie missing | Log in via the browser first; include `-b <cookie-file>` in curl commands |
| Session starts but no logs appear | Path to `red_controller.py` wrong | Check `ZANSIN_RC_DIR` env var; verify `/opt/zansin/red-controller/red_controller.py` exists |
| Scores show `—` after exercise ends | SQLite DB not written yet | Wait a moment; the judge runs after the crawl+attack threads join |
| "Cannot edit scenario while sessions are running" | A session is still active | Stop all running sessions first |
| `ModuleNotFoundError: web_controller` | uvicorn started from wrong directory | Ensure `WorkingDirectory=/opt/zansin/red-controller` in systemd unit |
| VPN tab shows "WireGuard not configured" | Ansible not yet run, or keys missing | Re-run Setup tab (or `zansin.sh`); if keys were deleted, run `bash /opt/zansin/red-controller/wireguard_setup.sh <control-ip>` |
| VPN .conf download returns 409 | Training IP not set for this peer | Assign a Training IP to the peer before downloading |
| WireGuard keys not readable | `zansin` group not active | Run `sudo usermod -aG zansin $USER`, then restart with `./web_controller.sh restart` |
| Setup tab shows "unavailable" | `ZANSIN_REPO_DIR` not set | Start via `./web_controller.sh` instead of systemd |
| Setup tab: "ansible-playbook not found" | Ansible not installed | `sudo apt install ansible` on the machine running `web_controller.sh` |
