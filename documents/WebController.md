# ZANSIN Web Controller

The ZANSIN Web Controller is a browser-based interface for the Red Controller.
It allows instructors to run exercises for multiple learners simultaneously, monitor logs in real time, compare scores, and edit attack scenarios — all without using the command line.

---

## Architecture

```
[Browser]  ←HTTP/SSE→  [Web Controller :8888]  ←subprocess→  [red_controller.py]
                              │
                              ├── session_manager.py   (process lifecycle + log streaming)
                              ├── db_reader.py          (reads per-session SQLite)
                              └── config_editor.py      (reads/writes attack_config.ini)
```

- **Backend**: FastAPI + Server-Sent Events (SSE)
- **Frontend**: Single-page HTML with Vanilla JS and Tailwind CSS (CDN, no build step)
- **Port**: 8888 (on the Control Server)
- **Session isolation**: Each learner's exercise runs as a separate process; SQLite databases are stored in `~/red-controller/sessions/<session-id>/sqlite3/`

---

## Prerequisites

> [!IMPORTANT]
> The Web Controller runs **on the Control Server**, which must be provisioned first via the ZANSIN Ansible playbook.
> You cannot test it on a local development machine without deploying first.

Required before proceeding:

- Both machines (Control Server and Training Machine) are provisioned via `zansin.sh` / Ansible.
- You can SSH into the Control Server as the `zansin` user.
- `~/red-controller/` exists on the Control Server (created by Ansible).

---

## Deployment

### Automatic (recommended)

**Running `zansin.sh` sets up everything, including the Web Controller.**

```bash
chmod +x zansin.sh
./zansin.sh
```

The script performs these steps in order:

1. Provisions the Training Machine via Ansible.
2. Transfers all files to the Control Server via `rsync` (including `web_controller/`).
3. Creates the Python virtualenv and runs `pip install` (including `fastapi` and `uvicorn`).
4. Creates the `sessions/` directory.
5. Registers and starts the `zansin-web-controller` systemd service.

After `zansin.sh` completes, the Web Controller is running and enabled on the Control Server.

### Manual (for re-deployment or adding to an existing environment)

SSH into the Control Server as `zansin`, then:

```bash
# 1. Transfer files from the repo to the Control Server
rsync -avz playbook/roles/zansin-control-server/files/. zansin@<control-ip>:~/red-controller/

# 2. Install dependencies on the Control Server
source ~/red-controller/red_controller_venv/bin/activate
pip install -r ~/red-controller/requirements.txt
deactivate

mkdir -p ~/red-controller/sessions

# 3. Register and start the systemd service
sudo tee /etc/systemd/system/zansin-web-controller.service > /dev/null << 'EOF'
[Unit]
Description=ZANSIN Web Controller
After=network.target

[Service]
Type=simple
User=zansin
WorkingDirectory=/home/zansin/red-controller
ExecStart=/home/zansin/red-controller/red_controller_venv/bin/uvicorn web_controller.main:app --host 0.0.0.0 --port 8888 --workers 1
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

```bash
# Check status
sudo systemctl status zansin-web-controller

# Start
sudo systemctl start zansin-web-controller

# Stop
sudo systemctl stop zansin-web-controller

# View logs
sudo journalctl -u zansin-web-controller -f
```

Alternatively, start directly in the foreground (useful for debugging):

```bash
cd ~/red-controller
source red_controller_venv/bin/activate
uvicorn web_controller.main:app --host 0.0.0.0 --port 8888
```

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

## UI Overview (4 Tabs)

### Tab 1 — Exercise Management

Start, monitor, and stop exercises for multiple learners.

| Field | Description |
|-------|-------------|
| Learner Name | Identifier used for logs and scoring (e.g. `learnerA`) |
| Training IP | IP address of the learner's Training Machine |
| Control IP | IP address of this Control Server |
| Scenario | `0` = Dev, `1` = Hardest (all attacks), `2` = Medium |

Click **▶ Start** to launch the exercise. It will appear in the session list below.

- **● Running** — exercise is in progress.
- **■ Finished** — exercise has ended; Technical Point and Operation Ratio are shown.
- **■ Stop** — sends SIGTERM to the exercise process.

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

### Tab 4 — Scenario Editor

Edit `attack_config.ini` directly from the browser.

1. Select a scenario (0, 1, or 2).
2. Edit step IDs, delay times, actions, and cheat counts inline.
3. Add steps with **+ Add Step**; remove with **✕**.
4. Click **💾 Save** to write the changes to `attack_config.ini`.

> [!WARNING]
> Saving is blocked (HTTP 409) while any session is running.
> Stop all running exercises before editing.

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

# 3. API is reachable
curl http://localhost:8888/api/sessions
# Expected: [] (empty list on first run)

# 4. Session directory exists
ls ~/red-controller/sessions/
# Expected: directory exists (may be empty)
```

### Test: Launch a session via API

```bash
curl -X POST http://localhost:8888/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"learner_name":"test","training_ip":"<training-ip>","control_ip":"<control-ip>","scenario":0}'
# Expected: {"session_id":"<uuid>"}
```

### Test: Confirm SQLite isolation

```bash
ls ~/red-controller/sessions/
# Each session_id directory should appear here

ls ~/red-controller/sessions/<session-id>/sqlite3/
# Expected: judge.db and/or crawler_test.db appear once the exercise starts
```

---

## File Structure

```
~/red-controller/                        ← deployed on Control Server
├── red_controller.py                    ← CLI entry point (unchanged)
├── config.ini
├── requirements.txt                     ← fastapi, uvicorn added
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
└── web_controller/
    ├── main.py
    ├── models.py
    ├── session_manager.py
    ├── db_reader.py
    ├── config_editor.py
    └── static/
        └── index.html
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `http://<ip>:8888` not reachable | Port blocked by firewall | `sudo ufw allow 8888/tcp` |
| Service fails to start | `fastapi`/`uvicorn` not installed | Re-run Ansible or `pip install -r requirements.txt` |
| Session starts but no logs appear | Path to `red_controller.py` wrong | Check `VENV_PYTHON` and `RED_CONTROLLER_PATH` in `session_manager.py` |
| Scores show `—` after exercise ends | SQLite DB not written yet | Wait a moment; the judge runs after the crawl+attack threads join |
| "Cannot edit scenario while sessions are running" | A session is still active | Stop all running sessions first |
| `ModuleNotFoundError: web_controller` | uvicorn started from wrong directory | Ensure `WorkingDirectory=/home/zansin/red-controller` in systemd unit |
