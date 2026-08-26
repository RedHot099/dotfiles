from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from bootstrap_core import (
    AuditFinding,
    CatalogError,
    ExecutionPlan,
    MachineFacts,
    apply_plan,
    audit_plan,
    build_plan,
    detect_machine,
    load_catalog,
    load_profiles,
    resolve_features,
)


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)
    try:
        if args.command is None:
            return run_wizard()
        if args.command == "plan":
            return plan_command(args)
        if args.command == "apply":
            return apply_command(args)
        if args.command == "audit":
            return audit_command(args)
    except (CatalogError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 2
    parser.error("missing command")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Configure a fresh Omarchy 4 installation")
    subparsers = parser.add_subparsers(dest="command")

    plan = subparsers.add_parser("plan", help="Build a read-only installation plan")
    plan.add_argument("--profile", action="append", default=[])
    plan.add_argument("--select", action="append", default=[])
    plan.add_argument("--no-defaults", action="store_true")
    plan.add_argument("--hardware", default="auto", choices=("auto", "generic", "desktop-ultrawide-nvidia", "wizard"))
    plan.add_argument("--monitor-output")
    plan.add_argument("--monitor-mode")
    plan.add_argument("--monitor-scale", default="1")
    plan.add_argument("--monitor-position", default="0x0")
    plan.add_argument("--default-agent", default="claude", choices=("claude", "codex", "opencode"))
    plan.add_argument("--target-home", type=Path, default=Path.home())
    plan.add_argument("--facts", type=Path)
    plan.add_argument("--out", type=Path, default=ROOT / ".bootstrap" / "plan.json")

    apply = subparsers.add_parser("apply", help="Apply a reviewed plan")
    apply.add_argument("--plan", type=Path, required=True)
    apply.add_argument("--yes", action="store_true")
    apply.add_argument("--simulate-system", action="store_true")

    audit = subparsers.add_parser("audit", help="Audit a plan without writing")
    audit.add_argument("--plan", type=Path, required=True)
    audit.add_argument("--facts", type=Path)
    audit.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def plan_command(args: argparse.Namespace) -> int:
    features = load_catalog(ROOT / "features")
    profiles = load_profiles(ROOT / "profiles")
    facts = load_facts(args.facts) if args.facts else detect_machine(features.values())
    requested = set() if args.no_defaults else {feature.id for feature in features.values() if feature.default}
    for profile in split_values(args.profile):
        if profile not in profiles:
            raise CatalogError(f"unknown profile: {profile}")
        requested.update(profiles[profile])
    requested.update(split_values(args.select))
    hardware, monitor_content = resolve_hardware(args, interactive=False)
    if hardware == "desktop-ultrawide-nvidia" and not args.no_defaults:
        requested.add("session-autostart")
    plan = build_plan(ROOT, features, requested, hardware, args.target_home, facts, args.default_agent, monitor_content)
    write_plan(args.out, plan)
    print_plan(plan, features)
    print(f"\nPlan written to {args.out}")
    return 0


def apply_command(args: argparse.Namespace) -> int:
    plan = read_plan(args.plan)
    real_home = Path(plan.target_home).resolve() == Path.home().resolve()
    system_changes = real_home and not args.simulate_system
    if system_changes and not args.yes:
        if not sys.stdin.isatty() or not confirm("Apply this plan to the current machine?"):
            print("Aborted.")
            return 1
    result = apply_plan(ROOT, plan, system_changes=system_changes, interactive=sys.stdin.isatty())
    print(f"Changed: {result.changed}")
    print(f"Unchanged: {result.unchanged}")
    print(f"System actions not run: {result.simulated}")
    if result.skipped_features:
        print(f"Skipped features: {', '.join(result.skipped_features)}")
    return 0 if not result.skipped_features else 1


def audit_command(args: argparse.Namespace) -> int:
    plan = read_plan(args.plan)
    features = load_catalog(ROOT / "features")
    facts = load_facts(args.facts) if args.facts else detect_machine(features.values())
    findings = audit_plan(ROOT, plan, facts)
    if args.format == "json":
        print(json.dumps([finding.__dict__ for finding in findings], indent=2))
    else:
        print_audit(findings)
    return 1 if any(finding.status == "FAIL" for finding in findings) else 0


def run_wizard() -> int:
    if not sys.stdin.isatty() or not shutil.which("gum"):
        raise CatalogError("interactive mode requires a terminal and gum; use 'bootstrap plan' instead")
    features = load_catalog(ROOT / "features")
    facts = detect_machine(features.values())
    choices = []
    labels: dict[str, str] = {}
    selected_labels = []
    default_ids = default_wizard_selections(features)
    for feature in sorted((item for item in features.values() if item.visible), key=lambda item: (item.group, item.label)):
        installed = feature.commands and all(command in facts.commands for command in feature.commands)
        suffix = " [installed]" if installed else ""
        label = f"{feature.group}: {feature.label}{suffix}"
        labels[label] = feature.id
        choices.append(label)
        if feature.id in default_ids:
            selected_labels.append(label)
    command = ["gum", "choose", "--no-limit", "--height", "20", "--header", "Select programs and features"]
    if selected_labels:
        command.extend(["--selected", ",".join(selected_labels)])
    command.extend(choices)
    output = subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE).stdout.splitlines()
    requested = {labels[label] for label in output}
    hardware, monitor_content = interactive_hardware()
    if hardware == "desktop-ultrawide-nvidia" and "core-desktop" in requested:
        requested.add("session-autostart")
    default_agent = subprocess.run(["gum", "choose", "--header", "Choose the default AI agent", "claude", "codex", "opencode"], check=True, text=True, stdout=subprocess.PIPE).stdout.strip()
    plan = build_plan(ROOT, features, requested, hardware, Path.home(), facts, default_agent, monitor_content)
    plan_path = ROOT / ".bootstrap" / "plan.json"
    write_plan(plan_path, plan)
    print_plan(plan, features)
    if not confirm("Apply this plan?"):
        print(f"Plan saved to {plan_path}")
        return 0
    result = apply_plan(ROOT, plan, system_changes=True, interactive=True)
    print(f"Changed: {result.changed}; unchanged: {result.unchanged}; pending manual steps: {result.simulated}")
    findings = audit_plan(ROOT, plan)
    print_audit(findings)
    return 1 if any(finding.status == "FAIL" for finding in findings) else 0


def default_wizard_selections(features: dict[str, object]) -> set[str]:
    return {feature.id for feature in features.values() if feature.default}


def resolve_hardware(args: argparse.Namespace, interactive: bool) -> tuple[str, str | None]:
    if args.hardware == "desktop-ultrawide-nvidia":
        return args.hardware, None
    if args.hardware == "generic":
        return args.hardware, None
    if args.monitor_output and args.monitor_mode:
        return "custom", render_monitor(args.monitor_output, args.monitor_mode, args.monitor_position, args.monitor_scale)
    detected = detect_known_hardware()
    if detected:
        return detected, None
    if args.hardware == "wizard" or interactive:
        return interactive_hardware()
    raise CatalogError("unknown monitor; use --hardware wizard in a terminal or provide --monitor-output and --monitor-mode")


def interactive_hardware() -> tuple[str, str | None]:
    detected = detect_known_hardware()
    if detected:
        return detected, None
    monitors = monitor_facts()
    if not monitors:
        raise CatalogError("Hyprland did not report any monitors")
    labels = [f"{item['name']}: {item.get('description') or 'unknown display'}" for item in monitors]
    choice = subprocess.run(["gum", "choose", "--header", "Choose the primary monitor", *labels], check=True, text=True, stdout=subprocess.PIPE).stdout.strip()
    monitor = monitors[labels.index(choice)]
    mode_default = f"{monitor['width']}x{monitor['height']}@{monitor['refreshRate']}"
    mode = gum_input("Resolution and refresh rate", mode_default)
    scale = gum_input("Scale", str(monitor.get("scale", 1)))
    position = gum_input("Position", "0x0")
    content = render_monitor(str(monitor["name"]), mode, position, scale)
    if len(monitors) > 1:
        layout = subprocess.run(["gum", "choose", "--header", "Choose the monitor layout", "Extend right", "Extend left", "Automatic"], check=True, text=True, stdout=subprocess.PIPE).stdout.strip()
        secondary_position = {"Extend right": "auto-right", "Extend left": "auto-left", "Automatic": "auto"}[layout]
        for secondary in monitors:
            if secondary["name"] != monitor["name"]:
                content += render_monitor(str(secondary["name"]), "preferred", secondary_position, "auto", include_gdk=False)
    return "custom", content


def detect_known_hardware() -> str | None:
    monitors = monitor_facts()
    descriptions = " ".join(str(item.get("description", "")) for item in monitors)
    gpu = subprocess.run(["lspci"], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout if shutil.which("lspci") else ""
    if len(monitors) == 1 and "MAG 341C" in descriptions and "NVIDIA" in gpu:
        return "desktop-ultrawide-nvidia"
    return None


def monitor_facts() -> list[dict[str, object]]:
    if not shutil.which("hyprctl"):
        return []
    result = subprocess.run(["hyprctl", "-j", "monitors", "all"], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if result.returncode != 0:
        return []
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def render_monitor(output: str, mode: str, position: str, scale: str, include_gdk: bool = True) -> str:
    patterns = {
        "output": (output, r"[A-Za-z0-9_.:-]+"),
        "mode": (mode, r"(?:preferred|[0-9]+x[0-9]+@[0-9]+(?:\.[0-9]+)?)"),
        "position": (position, r"(?:auto(?:-(?:left|right|up|down))?|-?[0-9]+x-?[0-9]+)"),
        "scale": (scale, r"(?:auto|[0-9]+(?:\.[0-9]+)?)"),
    }
    for label, (value, pattern) in patterns.items():
        if not re.fullmatch(pattern, value):
            raise CatalogError(f"invalid monitor {label}: {value}")
    prefix = 'hl.env("GDK_SCALE", "2")\n' if include_gdk else ""
    scale_value = f'"{scale}"' if scale == "auto" else scale
    return prefix + f'hl.monitor({{ output = "{output}", mode = "{mode}", position = "{position}", scale = {scale_value} }})\n'


def gum_input(header: str, value: str) -> str:
    return subprocess.run(["gum", "input", "--header", header, "--value", value], check=True, text=True, stdout=subprocess.PIPE).stdout.strip()


def confirm(prompt: str) -> bool:
    if shutil.which("gum"):
        return subprocess.run(["gum", "confirm", prompt]).returncode == 0
    answer = input(f"{prompt} [y/N] ")
    return answer.lower() in {"y", "yes"}


def load_facts(path: Path) -> MachineFacts:
    value = json.loads(path.read_text())
    return MachineFacts(int(value["omarchy_major"]), frozenset(value.get("packages", [])), frozenset(value.get("commands", [])))


def read_plan(path: Path) -> ExecutionPlan:
    return ExecutionPlan.from_dict(json.loads(path.read_text()))


def write_plan(path: Path, plan: ExecutionPlan) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(plan.to_dict(), indent=2, sort_keys=True) + "\n"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(content)
    temporary.replace(path)


def print_plan(plan: ExecutionPlan, features: dict[str, object]) -> None:
    print("Omarchy 4 bootstrap plan")
    print(f"Hardware: {plan.hardware}")
    print(f"Default agent: {plan.default_agent}")
    print("Selected features:")
    for feature_id in plan.selected:
        feature = features[feature_id]
        print(f"  - {feature.label}")
    counts: dict[str, int] = {}
    for action in plan.actions:
        counts[action.kind] = counts.get(action.kind, 0) + 1
    print("Actions:")
    for kind, count in sorted(counts.items()):
        print(f"  - {kind}: {count}")
    print(f"Digest: {plan.digest}")


def print_audit(findings: tuple[AuditFinding, ...]) -> None:
    groups: dict[tuple[str, str], list[str]] = {}
    for finding in findings:
        groups.setdefault((finding.status, finding.feature), []).append(finding.message)
    order = {"FAIL": 0, "WARN": 1, "PASS": 2}
    for (status, feature), messages in sorted(groups.items(), key=lambda item: (order[item[0][0]], item[0][1])):
        if len(messages) == 1:
            detail = messages[0]
        else:
            samples = "; ".join(messages[:3])
            detail = f"{len(messages)} checks; {samples}"
            if len(messages) > 3:
                detail += f"; and {len(messages) - 3} more"
        print(f"{status:<4} {feature:<24} {detail}")


def split_values(values: list[str]) -> set[str]:
    return {item.strip() for value in values for item in value.split(",") if item.strip()}


if __name__ == "__main__":
    raise SystemExit(main())
