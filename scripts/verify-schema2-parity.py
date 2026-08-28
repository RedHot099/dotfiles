#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

from bootstrap.catalog import load_workspace
from bootstrap.planner import HostState, PlanInputs, plan_install
from bootstrap.platform import PlatformFacts
from bootstrap.domain import PlatformId
from bootstrap.packages import StaticPackageProvider


ROOT = Path(__file__).resolve().parents[1]
ALIASES = {"desktop-portable": "core-desktop", "todoist-helper": "todoist"}
RENAMED_FEATURES = {
    "todoist",
    "todoist-helper",
    "user-skills",
    "tool.rclone",
    "cloud.google-drive",
    "cloud.onedrive",
}


def main() -> int:
    workspace = load_workspace(ROOT, PlatformId.OMARCHY)
    normalized_root = ROOT / "tests/snapshots/schema1/normalized"
    raw_root = ROOT / "tests/snapshots/schema1/raw"
    for expected_path in sorted(normalized_root.glob("*.json")):
        expected = json.loads(expected_path.read_text())
        raw = json.loads((raw_root / expected_path.name).read_text())
        facts = fixture_facts(expected["target_home"])
        monitor_content = next(
            (
                item["data"]["content"]
                for item in raw["actions"]
                if item["feature"] == "hardware" and "content" in item["data"]
            ),
            None,
        )
        github_keys = {
            item["data"]["username"]: tuple(item["data"]["keys"])
            for item in raw["actions"]
            if item["kind"] == "github-ssh"
        }
        actual = plan_install(
            ROOT,
            workspace,
            facts,
            HostState(frozenset(), frozenset()),
            set(expected["selected"]),
            PlanInputs(
                expected["hardware"],
                expected["default_agent"],
                monitor_content,
                github_keys,
            ),
            StaticPackageProvider(),
        )
        expected_actions = canonical_actions(expected["actions"])
        actual_actions = canonical_actions(actual.to_dict()["actions"])
        if expected_actions != actual_actions:
            raise SystemExit(f"schema-2 Omarchy parity failed: {expected_path.name}")
    verify_deliberate_renames()
    print("Schema-2 Omarchy parity checks passed.")
    return 0


def canonical_actions(actions: list[dict[str, object]]) -> tuple[str, ...]:
    result: list[str] = []
    for original in actions:
        if original["feature"] in RENAMED_FEATURES:
            continue
        if original["data"].get("target") == ".local/bin/arch-hypr-agent":
            continue
        item = {
            "kind": original["kind"],
            "feature": ALIASES.get(str(original["feature"]), original["feature"]),
            "data": dict(original["data"]),
        }
        if item["feature"] == "ssh-access" and item["kind"] in {
            "repository-packages",
            "system-unit",
        }:
            continue
        if item["kind"] == "generated-file":
            item["kind"] = "user-file"
            item["data"].pop("content", None)
        if item["kind"] == "repository-packages":
            item["data"].pop("sources", None)
            item["data"].pop("transaction", None)
        if item["kind"] == "aur-build":
            for field in ("package_base", "version", "url", "commit", "files", "dependencies"):
                item["data"].pop(field, None)
            for package in item["data"]["packages"]:
                split = {**item, "data": {**item["data"], "packages": [package]}}
                result.append(json.dumps(split, sort_keys=True, separators=(",", ":")))
            continue
        if item["kind"] == "manual-authentication":
            for field in ("command", "probe"):
                if isinstance(item["data"].get(field), str):
                    item["data"][field] = shlex.split(item["data"][field])
        if item["kind"] == "user-unit":
            for probe in item["data"].get("auth_probes", []):
                if isinstance(probe.get("command"), str):
                    probe["command"] = shlex.split(probe["command"])
            item["data"].pop("enabled", None)
            item["data"].pop("start", None)
        result.append(json.dumps(item, sort_keys=True, separators=(",", ":")))
    return tuple(sorted(result))


def verify_deliberate_renames() -> None:
    common = ROOT / "common"
    omarchy = ROOT / "omarchy"
    for tree in (common, omarchy):
        for path in tree.rglob("*"):
            if path.is_symlink():
                content = os.readlink(path)
            elif path.is_file():
                try:
                    content = path.read_text()
                except UnicodeDecodeError:
                    continue
            else:
                continue
            if "omarchy-bootstrap" in content or "omarchy-todoist" in content:
                raise SystemExit(f"legacy portable name remains: {path}")
    links = sum(1 for path in (common / "payload/user-skills").rglob("*") if path.is_symlink())
    if links != 249:
        raise SystemExit(f"expected 249 skill adapters, found {links}")
    if not (common / "payload/todoist-helper/.local/bin/todoist-helper").is_file():
        raise SystemExit("portable Todoist helper is missing")


def fixture_facts(target_home: str) -> PlatformFacts:
    return PlatformFacts(
        platform=PlatformId.OMARCHY,
        contract_major=4,
        os_id="omarchy",
        architecture="x86_64",
        uid=1000,
        target_home=target_home,
        omarchy_major=4,
        hyprland_version="0.56.2",
        uwsm_version="0.24.0",
        shell_name="omarchy-shell",
        shell_version="1.2.0",
        pacman_config_digest="a" * 64,
        repositories=("core|siglevel=required|usage=All",),
        capabilities=frozenset(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
