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
    """Return {scenario_num: [ScenarioStep, ...]} for all scenarios found in config."""
    config = _load_config()
    result: dict[int, list[ScenarioStep]] = {}

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
            result[scenario_num] = []

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


_DEFAULT_NAMES = {0: "Dev (全ステップ)", 1: "最難度", 2: "中難度"}


def get_scenario_names() -> dict[int, str]:
    """Return {scenario_num: name}. Falls back to default names for 0-2."""
    config = _load_config()
    names: dict[int, str] = {}
    if config.has_section("ScenarioMeta"):
        for key, value in config.items("ScenarioMeta"):
            if key.endswith("_name"):
                try:
                    num = int(key[:-5])  # strip "_name"
                    names[num] = value.strip()
                except ValueError:
                    continue
    # Populate defaults for 0/1/2 if not in config
    for num, default in _DEFAULT_NAMES.items():
        names.setdefault(num, default)
    return names


def get_scenario_duration(scenario_num: int) -> Optional[int]:
    """Return per-scenario duration in minutes, or None if not set."""
    config = _load_config()
    if config.has_section("ScenarioMeta"):
        key = f"{scenario_num}_minutes"
        for k, v in config.items("ScenarioMeta"):
            if k.strip() == key:
                try:
                    return int(v.strip())
                except ValueError:
                    return None
    return None


def save_scenario_duration(scenario_num: int, minutes: int) -> None:
    """Write/update {scenario_num}_minutes in [ScenarioMeta] section."""
    with open(str(_ATTACK_CONFIG_PATH), "r", encoding="utf-8") as f:
        raw_lines = f.readlines()

    meta_key = f"{scenario_num}_minutes"
    in_meta = False
    found = False
    new_lines: list[str] = []

    for line in raw_lines:
        stripped = line.strip()
        if stripped == "[ScenarioMeta]":
            in_meta = True
            new_lines.append(line)
            continue
        if stripped.startswith("[") and stripped.endswith("]") and stripped != "[ScenarioMeta]":
            if in_meta and not found:
                new_lines.append(f"{meta_key:<20}: {minutes}\n")
                found = True
            in_meta = False
            new_lines.append(line)
            continue
        if in_meta and ":" in line and not stripped.startswith("#"):
            key_part = line.split(":")[0].strip()
            if key_part == meta_key:
                new_lines.append(f"{meta_key:<20}: {minutes}\n")
                found = True
                continue
        new_lines.append(line)

    if in_meta and not found:
        new_lines.append(f"{meta_key:<20}: {minutes}\n")
    elif not found:
        new_lines.append("\n[ScenarioMeta]\n")
        new_lines.append(f"{meta_key:<20}: {minutes}\n")

    with open(str(_ATTACK_CONFIG_PATH), "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def save_scenario_name(scenario_num: int, name: str) -> None:
    """Write/update {scenario_num}_name in [ScenarioMeta] section."""
    with open(str(_ATTACK_CONFIG_PATH), "r", encoding="utf-8") as f:
        raw_lines = f.readlines()

    meta_key = f"{scenario_num}_name"
    in_meta = False
    found = False
    new_lines: list[str] = []

    for line in raw_lines:
        stripped = line.strip()
        if stripped == "[ScenarioMeta]":
            in_meta = True
            new_lines.append(line)
            continue
        if stripped.startswith("[") and stripped.endswith("]") and stripped != "[ScenarioMeta]":
            if in_meta and not found:
                new_lines.append(f"{meta_key:<20}: {name}\n")
                found = True
            in_meta = False
            new_lines.append(line)
            continue
        if in_meta and ":" in line and not stripped.startswith("#"):
            key_part = line.split(":")[0].strip()
            if key_part == meta_key:
                new_lines.append(f"{meta_key:<20}: {name}\n")
                found = True
                continue
        new_lines.append(line)

    if in_meta and not found:
        # [ScenarioMeta] was last section
        new_lines.append(f"{meta_key:<20}: {name}\n")
    elif not found:
        # No [ScenarioMeta] section exists yet — append it
        new_lines.append("\n[ScenarioMeta]\n")
        new_lines.append(f"{meta_key:<20}: {name}\n")

    with open(str(_ATTACK_CONFIG_PATH), "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def delete_scenario(scenario_num: int) -> None:
    """Remove all steps and name for scenario_num from attack_config.ini."""
    with open(str(_ATTACK_CONFIG_PATH), "r", encoding="utf-8") as f:
        raw_lines = f.readlines()

    prefix = f"{scenario_num}-"
    meta_name_key = f"{scenario_num}_name"
    meta_minutes_key = f"{scenario_num}_minutes"
    new_lines: list[str] = []
    in_scenario = False
    in_meta = False

    for line in raw_lines:
        stripped = line.strip()
        if stripped == "[Scenario]":
            in_scenario = True
            in_meta = False
            new_lines.append(line)
            continue
        if stripped == "[ScenarioMeta]":
            in_meta = True
            in_scenario = False
            new_lines.append(line)
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            in_scenario = in_meta = False
            new_lines.append(line)
            continue
        # Remove target scenario step lines
        if in_scenario and ":" in line and not stripped.startswith("#"):
            key_part = line.split(":")[0].strip()
            if key_part.startswith(prefix):
                continue  # skip
        # Remove target name and minutes lines
        if in_meta and ":" in line and not stripped.startswith("#"):
            key_part = line.split(":")[0].strip()
            if key_part in (meta_name_key, meta_minutes_key):
                continue  # skip
        new_lines.append(line)

    with open(str(_ATTACK_CONFIG_PATH), "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def get_next_scenario_num() -> int:
    """Return the smallest unused scenario number >= 3."""
    existing = set(get_all_scenarios().keys())
    n = 3
    while n in existing:
        n += 1
    return n


ACTION_DESCRIPTIONS: dict[str, str] = {
    "nmap":                     "ネットワークスキャン。対象ホストの開放ポートとサービスを列挙する。",
    "nikto":                    "Webサーバー脆弱性スキャン。既知の脆弱性やミス設定を検出する。",
    "upload_webshell":          "ファイルアップロード脆弱性を悪用してWebシェルを設置する。",
    "upload_cheatfile":         "チートファイルをアップロードし、不正なゲームデータを書き込む。",
    "passcrack_ssh":            "SSH接続に対してパスワードブルートフォース攻撃を実行する。",
    "backdoor_docker":          "Docker API（port 2375）を悪用してバックドアを設置する。",
    "backdoor_debug":           "デバッグAPI（port 3000）を悪用してバックドアを設置する。",
    "backdoor_ssh":             "SSH経由でバックドアアカウントまたはキーを設置する。",
    "install_malware_ssh":      "SSH経由でマルウェアをインストールする。",
    "install_malware_rsh":      "リバースシェル経由でマルウェアをインストールする。",
    "cheat_user_sqli1":         "SQLインジェクション（パターン1）でチートユーザーを作成する。",
    "cheat_user_sqli2":         "SQLインジェクション（パターン2）でチートユーザーを作成する。",
    "cheat_user_php":           "PHPコードインジェクションでチートユーザーを作成する。",
    "cheat_battle":             "バトルシステムを改ざんして不正なゲーム結果を生成する。",
    "cheat_dump_player":        "プレイヤーデータを不正に取得・ダンプする。",
    "cheat_dump_player_delete": "ダンプしたプレイヤーデータを削除する。",
    "cheat_gacha":              "ガチャシステムを改ざんして不正なアイテムを取得する。",
    "exploit_index_docker":     "Docker API経由でインデックスページを改ざんする。",
    "exploit_index_debug":      "デバッグAPI経由でインデックスページを改ざんする。",
    "exploit_userlist_ban":     "ユーザーリストAPIを悪用してプレイヤーをBAN/復元する。",
    "judge":                    "判定処理を実行し、脆弱性修正の評価スコアを算出する。",
    "drop_db1":                 "データベースをドロップする（パターン1）。",
    "drop_db2":                 "データベースをドロップする（パターン2）。",
    "wall_c2":                  "C2サーバーとの通信チャネルを確立する。",
}


def get_action_descriptions() -> dict[str, str]:
    """Return action name → Japanese description mapping."""
    return ACTION_DESCRIPTIONS


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
