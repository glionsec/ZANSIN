# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is ZANSIN

ZANSIN is a cybersecurity training platform. It provisions two Ubuntu machines via Ansible:
- **Control Server**: Runs the Red Controller (crawler + attack tool + judge) against the training machine
- **Training Machine**: Hosts a deliberately vulnerable PHP/MySQL/Docker web game called "MINI QUEST"

Learners access the training machine and must identify and fix vulnerabilities while the control server simultaneously crawls (simulates legitimate users) and executes attack scenarios.

## Deployment

**Initial setup** (run from a machine with network access to both hosts):
```bash
chmod +x zansin.sh
./zansin.sh
```
This installs Ansible/sshpass/git, clones the repo, prompts for IPs and the `zansin` user's password, updates `playbook/inventory.ini` and `playbook/game-servers.yml`, runs the Ansible playbook, and then bootstraps the Red Controller Python virtualenv on the control server.

**Run Ansible playbook manually** (from `playbook/`):
```bash
ansible-playbook -i inventory.ini game-servers.yml
# Run only the control server role:
ansible-playbook -i inventory.ini game-servers.yml --tags zansin-control-server
```

**Inventory**: `playbook/inventory.ini` — line 2 is the training machine IP, line 4 is the control server IP.

## Running an Exercise (on the Control Server)

```bash
# Activate virtualenv
source ~/red-controller/red_controller_venv/bin/activate

# Start exercise
cd ~/red-controller
python3 red_controller.py -n <learner_name> -t <training-ip> -c <control-ip> -a <scenario>
# Attack scenarios: 0 (dev/all steps), 1 (hardest, all attacks), 2 (medium difficulty)

# Deactivate when done
deactivate
```

Red Controller runs two threads concurrently: the crawler and the attack tool. After both finish, the judge evaluates and displays Technical Point (max 100) and Operation Ratio (max 100%).

## Control Server Code Structure

All Red Controller source lives in `playbook/roles/zansin-control-server/files/` (deployed to `~/red-controller/` on the control server):

```
red_controller.py         # Entry point; orchestrates threads for crawler + attack + judge
config.ini                # Training duration (default: 240 min), port discovery settings
requirements.txt          # Python deps: docopt, requests, paramiko, python-nmap, aiohttp, bs4

attack/
  attack_controller.py   # Reads attack_config.ini, schedules POC modules per scenario
  attack_config.ini      # Scenario definitions: format is <scenario>-<step>: <delay>@<action>@<cheat_count>
  poc/                   # Individual attack modules (one Python file per attack type)
  tools/c2s/             # Perl-based C2/DNS server (c2dns.pl) used for reverse shell attacks

crawler/
  crawler_controller.py  # Simulates legitimate game players; detects cheat users in ranking
  crawler_config.ini     # API endpoints, crawler timing, cheat detection thresholds
  crawler_sql.py         # SQLite3 persistence for crawler session data
  modules/player.py      # Player simulation logic

judge/
  judge_controller.py    # Evaluates what vulnerabilities were fixed; computes technical point
  judge_config.ini       # Judge module configuration
  judge_sql.py           # SQLite3 persistence for judge results
  modules/               # One check module per vulnerability (checklogin, checkdocker, etc.)
```

**Attack scenario format** in `attack_config.ini`:
```
<scenario>-<step_id>  :  <delay_minutes>@<action_name>@<cheat_gold>
```
Scenario 0 = dev, 1 = hardest (all attacks, short intervals), 2 = medium.

## Training Machine Code Structure

Deployed to `/home/vendor/game-api/` via Ansible role `training-machine`:

```
game-api/
  docker-compose.yml    # Defines: phpapi (port 8080→80), apidebug (3000), db MySQL (3306),
                        #          phpmyadmin (5555), redis (6379)
  public/               # PHP game API source files
    login.php, new_user.php, battle.php, gacha.php, ranking.php, upload.php, etc.
  initdb.d/             # MySQL init SQL
  apidebug/             # Debug API service (Node.js)

front/                  # Static HTML/CSS/JS front-end (served by nginx on port 80)
```

**Manage game containers** (on the training machine as `vendor`):
```bash
cd /home/vendor/game-api
docker-compose up -d     # Start
docker-compose down      # Stop
```

Nginx proxies port 80 → port 8080 (phpapi container). The `default.conf` nginx template is in `playbook/roles/training-machine/templates/`.

## Known Intentional Vulnerabilities (Training Machine)

These are by design — the game for learners is to fix them:
- SQL injection in `login.php` and `new_user.php` (raw user input in SQL strings)
- File upload webshell via `upload.php`
- Docker API exposed on port 2375/TCP (unauthenticated)
- Debug API exposed on port 3000
- MySQL (3306), Redis (6379), phpMyAdmin (5555) exposed externally
- Weak default passwords: Linux accounts `vendor`/`Passw0rd!23`, MySQL `root`/`password`

## Key Credentials (Default / Exercise Values)

| Account | Password | Where |
|---|---|---|
| `zansin` | set during deploy | Both machines (SSH/sudo) |
| `vendor` | `Passw0rd!23` | Training machine SSH |
| MySQL `root` | `password` | Training machine DB |

## Python Dependencies (Control Server)

Install from `requirements.txt` into a Python 3.10 virtualenv. External tools also required: `nmap`, `nikto`, `carton` (Perl), and Perl modules via `attack/cpanfile`.
