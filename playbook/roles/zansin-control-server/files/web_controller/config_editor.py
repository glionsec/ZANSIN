#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parse and write attack_config.ini scenarios."""
import configparser
import os
from pathlib import Path
from typing import Optional

from .models import ScenarioStep

_ATTACK_CONFIG_PATH = Path(__file__).parent.parent / "attack" / "attack_config.ini"
_POC_DIR = Path(__file__).parent.parent / "attack" / "poc"


def _load_config() -> configparser.RawConfigParser:
    config = configparser.RawConfigParser()
    config.optionxform = str  # preserve case
    config.read(str(_ATTACK_CONFIG_PATH), encoding="utf-8")
    return config


def get_all_scenarios() -> dict[int, list[ScenarioStep]]:
    """Return {scenario_num: [ScenarioStep, ...]} for scenarios 0, 1, 2."""
    config = _load_config()
    result: dict[int, list[ScenarioStep]] = {0: [], 1: [], 2: []}

    if not config.has_section("Scenario"):
        return result

    for key, value in config.items("Scenario"):
        # key: "0-001", value: "001@nmap@0"
        key = key.strip()
        if "-" not in key:
            continue
        try:
            scenario_num = int(key.split("-")[0])
        except ValueError:
            continue
        if scenario_num not in result:
            continue

        parts = value.strip().split("@")
        if len(parts) != 3:
            continue
        delay, action, cheat_count = parts
        result[scenario_num].append(
            ScenarioStep(
                step_id=key,
                delay=delay.strip(),
                action=action.strip(),
                cheat_count=cheat_count.strip(),
            )
        )

    for k in result:
        result[k].sort(key=lambda s: s.step_id)

    return result


def get_available_actions() -> list[str]:
    """Return action names derived from poc/*.py filenames."""
    actions = set()
    if _POC_DIR.exists():
        for f in _POC_DIR.glob("zansinapp_atk_*.py"):
            # zansinapp_atk_nmap.py -> nmap
            stem = f.stem.replace("zansinapp_atk_", "")
            actions.add(stem)
    # Add known actions from config that may not map 1:1 to poc files
    extra = {
        "nmap", "nikto", "upload_webshell", "upload_cheatfile", "passcrack_ssh",
        "backdoor_docker", "backdoor_debug", "backdoor_ssh", "install_malware_ssh",
        "install_malware_rsh", "cheat_user_sqli1", "cheat_user_sqli2", "cheat_user_php",
        "cheat_battle", "cheat_dump_player", "cheat_gacha", "exploit_index_docker",
        "exploit_index_debug", "exploit_userlist_ban", "cheat_dump_player_delete",
        "judge", "drop_db1", "drop_db2", "wall_c2",
    }
    actions.update(extra)
    return sorted(actions)


def save_scenario(scenario_num: int, steps: list[ScenarioStep]) -> None:
    """Overwrite the steps for one scenario in attack_config.ini.

    Reads the raw file, replaces lines belonging to the given scenario,
    and writes it back preserving all other sections and formatting.
    """
    with open(str(_ATTACK_CONFIG_PATH), "r", encoding="utf-8") as f:
        raw_lines = f.readlines()

    prefix = f"{scenario_num}-"
    in_scenario_section = False
    new_lines: list[str] = []
    inserted = False

    for line in raw_lines:
        stripped = line.strip()

        # Detect [Scenario] section header
        if stripped == "[Scenario]":
            in_scenario_section = True
            new_lines.append(line)
            continue

        # Detect next section
        if stripped.startswith("[") and stripped.endswith("]") and stripped != "[Scenario]":
            # Before switching sections, flush new steps if not yet done
            if in_scenario_section and not inserted:
                for step in sorted(steps, key=lambda s: s.step_id):
                    new_lines.append(
                        f"{step.step_id:<20}: {step.delay}@{step.action}@{step.cheat_count}\n"
                    )
                inserted = True
            in_scenario_section = False
            new_lines.append(line)
            continue

        if in_scenario_section:
            # Check if this line belongs to the target scenario
            if ":" in line and not stripped.startswith("#"):
                key_part = line.split(":")[0].strip()
                if key_part.startswith(prefix):
                    # Skip old lines for this scenario; insert new ones once
                    if not inserted:
                        for step in sorted(steps, key=lambda s: s.step_id):
                            new_lines.append(
                                f"{step.step_id:<20}: {step.delay}@{step.action}@{step.cheat_count}\n"
                            )
                        inserted = True
                    continue
            new_lines.append(line)
        else:
            new_lines.append(line)

    # Edge case: [Scenario] was the last section
    if in_scenario_section and not inserted:
        for step in sorted(steps, key=lambda s: s.step_id):
            new_lines.append(
                f"{step.step_id:<20}: {step.delay}@{step.action}@{step.cheat_count}\n"
            )

    with open(str(_ATTACK_CONFIG_PATH), "w", encoding="utf-8") as f:
        f.writelines(new_lines)
