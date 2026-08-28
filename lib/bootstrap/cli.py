from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .audit import AuditFinding, audit_install
from .catalog import CatalogError, Workspace, load_workspace
from .domain import PlanHostMismatch, PlanSchemaError, ExecutionPlan, parse_plan_json
from .executor import apply_install
from .host import LocalHostProbe
from .planner import HostState, PlanInputs, plan_install, resolve_features
from .platform import PlatformDetectionError, PlatformFacts, detect_platform
from .ssh import fetch_github_keys, ssh_fingerprint


ROOT = Path(__file__).resolve().parents[2]


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
    except (
        CatalogError,
        PlanHostMismatch,
        PlanSchemaError,
        PlatformDetectionError,
        OSError,
        RuntimeError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
    ) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 2
    parser.error("missing command")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Configure a supported Arch Hyprland installation"
    )
    subparsers = parser.add_subparsers(dest="command")
    plan = subparsers.add_parser("plan", help="Build a read-only installation plan")
    plan.add_argument("--profile", action="append", default=[])
    plan.add_argument("--select", action="append", default=[])
    plan.add_argument("--no-defaults", action="store_true")
    plan.add_argument(
        "--hardware",
        default="auto",
        choices=("auto", "generic", "desktop-ultrawide-nvidia", "wizard"),
    )
    plan.add_argument("--monitor-output")
    plan.add_argument("--monitor-mode")
    plan.add_argument("--monitor-scale", default="1")
    plan.add_argument("--monitor-position", default="0x0")
    plan.add_argument(
        "--default-agent", default="claude", choices=("claude", "codex", "opencode")
    )
    plan.add_argument("--target-home", type=Path, default=Path.home())
    plan.add_argument("--facts", type=Path)
    plan.add_argument("--out", type=Path, default=ROOT / ".bootstrap/plan.json")

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
    facts = detect_platform(LocalHostProbe(args.target_home))
    workspace = load_workspace(ROOT, facts.platform)
    state = load_host_state(args.facts) if args.facts else detect_host_state(workspace)
    requested = requested_features(workspace, args)
    hardware, monitor_content = resolve_hardware(args, interactive=False)
    if hardware == "desktop-ultrawide-nvidia" and not args.no_defaults:
        requested.add("session-autostart")
    keys = reviewed_github_keys(workspace, requested)
    plan = plan_install(
        ROOT,
        workspace,
        facts,
        state,
        requested,
        PlanInputs(hardware, args.default_agent, monitor_content, keys),
    )
    write_plan(args.out, plan)
    print_plan(plan, workspace, hardware, args.default_agent)
    print(f"\nPlan written to {args.out}")
    return 0


def apply_command(args: argparse.Namespace) -> int:
    plan = read_plan(args.plan)
    facts = detect_platform(LocalHostProbe(Path(plan.target_home)))
    workspace = load_workspace(ROOT, facts.platform)
    real_home = Path(plan.target_home).resolve() == Path.home().resolve()
    system_changes = real_home and not args.simulate_system
    interactive = sys.stdin.isatty()
    if system_changes and not args.yes:
        if not interactive or not confirm("Apply this plan to the current machine?"):
            print("Aborted.")
            return 1
    result = apply_install(
        ROOT,
        workspace,
        plan,
        facts,
        system_changes=system_changes,
        interactive=interactive,
    )
    print(f"Changed: {result.changed}")
    print(f"Unchanged: {result.unchanged}")
    print(f"System actions not run: {result.simulated}")
    if result.skipped_features:
        print(f"Skipped features: {', '.join(result.skipped_features)}")
    return 0 if not result.skipped_features else 1


def audit_command(args: argparse.Namespace) -> int:
    plan = read_plan(args.plan)
    facts = detect_platform(LocalHostProbe(Path(plan.target_home)))
    workspace = load_workspace(ROOT, facts.platform)
    findings = audit_install(workspace, plan, facts)
    if args.format == "json":
        print(json.dumps([finding.__dict__ for finding in findings], indent=2))
    else:
        print_audit(findings)
    return 1 if any(finding.status == "FAIL" for finding in findings) else 0


def run_wizard() -> int:
    if not sys.stdin.isatty() or not shutil.which("gum"):
        raise CatalogError("interactive mode requires a terminal and gum; use 'bootstrap plan' instead")
    facts = detect_platform(LocalHostProbe(Path.home()))
    workspace = load_workspace(ROOT, facts.platform)
    state = detect_host_state(workspace)
    choices: list[str] = []
    labels: dict[str, str] = {}
    selected_labels: list[str] = []
    defaults = {feature.id for feature in workspace.public_catalog.values() if feature.default}
    visible = (feature for feature in workspace.public_catalog.values() if feature.visible)
    for feature in sorted(visible, key=lambda item: (item.group, item.label)):
        implementation = workspace.implementations[feature.id]
        installed = bool(implementation.commands) and all(
            command in state.commands for command in implementation.commands
        )
        providers = {
            workspace.package_bindings[requirement].provider
            for requirement in implementation.package_requirements
        }
        trust = ""
        if "aur" in providers:
            trust = " [AUR]"
        elif "repository" in providers:
            trust = " [repository]"
        elif implementation.tools:
            trust = " [mise]"
        availability = (
            f" [unavailable: {implementation.unavailable_reason}]"
            if not implementation.available
            else ""
        )
        suffix = trust + (" [installed]" if installed else "") + availability
        label = f"{feature.group}: {feature.label}{suffix}"
        labels[label] = feature.id
        choices.append(label)
        if feature.id in defaults:
            selected_labels.append(label)
    command = [
        "gum",
        "choose",
        "--no-limit",
        "--height",
        "20",
        "--header",
        "Select programs and features",
    ]
    if selected_labels:
        command.extend(("--selected", ",".join(selected_labels)))
    output = subprocess.run(
        (*command, *choices), check=True, text=True, stdout=subprocess.PIPE
    ).stdout.splitlines()
    requested = {labels[label] for label in output}
    hardware, monitor_content = interactive_hardware()
    if hardware == "desktop-ultrawide-nvidia" and "core-desktop" in requested:
        requested.add("session-autostart")
    default_agent = subprocess.run(
        ("gum", "choose", "--header", "Choose the default AI agent", "claude", "codex", "opencode"),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()
    keys = reviewed_github_keys(workspace, requested)
    plan = plan_install(
        ROOT,
        workspace,
        facts,
        state,
        requested,
        PlanInputs(hardware, default_agent, monitor_content, keys),
    )
    plan_path = ROOT / ".bootstrap/plan.json"
    write_plan(plan_path, plan)
    print_plan(plan, workspace, hardware, default_agent)
    if not confirm("Apply this plan?"):
        print(f"Plan saved to {plan_path}")
        return 0
    result = apply_install(
        ROOT, workspace, plan, facts, system_changes=True, interactive=True
    )
    print(
        f"Changed: {result.changed}; unchanged: {result.unchanged}; "
        f"pending manual steps: {result.simulated}"
    )
    findings = audit_install(workspace, plan, facts)
    print_audit(findings)
    return 1 if any(finding.status == "FAIL" for finding in findings) else 0


def requested_features(workspace: Workspace, args: argparse.Namespace) -> set[str]:
    requested = set() if args.no_defaults else {
        feature.id for feature in workspace.public_catalog.values() if feature.default
    }
    for profile_id in split_values(args.profile):
        profile = workspace.profiles.get(profile_id)
        if profile is None:
            raise CatalogError(f"unknown profile: {profile_id}")
        requested.update(profile.features)
    requested.update(split_values(args.select))
    return requested


def reviewed_github_keys(
    workspace: Workspace, requested: set[str]
) -> dict[str, tuple[str, ...]]:
    selected = resolve_features(workspace, requested)
    usernames = sorted(
        {
            workspace.implementations[feature_id].github_ssh_user
            for feature_id in selected
            if workspace.implementations[feature_id].github_ssh_user
        }
    )
    result: dict[str, tuple[str, ...]] = {}
    for username in usernames:
        assert username is not None
        keys = fetch_github_keys(username)
        print(f"GitHub SSH keys for {username}:")
        for fingerprint in map(ssh_fingerprint, keys):
            print(f"  - {fingerprint}")
        if sys.stdin.isatty() and not confirm(f"Trust these {len(keys)} SSH keys?"):
            raise CatalogError(f"SSH keys were not approved for {username}")
        result[username] = keys
    return result


def resolve_hardware(args: argparse.Namespace, interactive: bool) -> tuple[str, str | None]:
    if args.hardware in {"desktop-ultrawide-nvidia", "generic"}:
        return args.hardware, None
    if args.monitor_output and args.monitor_mode:
        return "custom", render_monitor(
            args.monitor_output,
            args.monitor_mode,
            args.monitor_position,
            args.monitor_scale,
        )
    detected = detect_known_hardware()
    if detected:
        return detected, None
    if args.hardware == "wizard" or interactive:
        return interactive_hardware()
    raise CatalogError(
        "unknown monitor; use --hardware wizard in a terminal or provide monitor arguments"
    )


def interactive_hardware() -> tuple[str, str | None]:
    detected = detect_known_hardware()
    if detected:
        return detected, None
    monitors = monitor_facts()
    if not monitors:
        raise CatalogError("Hyprland did not report any monitors")
    labels = [f"{item['name']}: {item.get('description') or 'unknown display'}" for item in monitors]
    choice = subprocess.run(
        ("gum", "choose", "--header", "Choose the primary monitor", *labels),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()
    monitor = monitors[labels.index(choice)]
    mode = gum_input(
        "Resolution and refresh rate",
        f"{monitor['width']}x{monitor['height']}@{monitor['refreshRate']}",
    )
    scale = gum_input("Scale", str(monitor.get("scale", 1)))
    position = gum_input("Position", "0x0")
    content = render_monitor(str(monitor["name"]), mode, position, scale)
    if len(monitors) > 1:
        layout = subprocess.run(
            ("gum", "choose", "--header", "Choose the monitor layout", "Extend right", "Extend left", "Automatic"),
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()
        secondary_position = {
            "Extend right": "auto-right",
            "Extend left": "auto-left",
            "Automatic": "auto",
        }[layout]
        for secondary in monitors:
            if secondary["name"] != monitor["name"]:
                content += render_monitor(
                    str(secondary["name"]),
                    "preferred",
                    secondary_position,
                    "auto",
                    include_gdk=False,
                )
    return "custom", content


def detect_known_hardware() -> str | None:
    monitors = monitor_facts()
    descriptions = " ".join(str(item.get("description", "")) for item in monitors)
    gpu = ""
    if shutil.which("lspci"):
        gpu = subprocess.run(
            ("lspci",), text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        ).stdout
    if len(monitors) == 1 and "MAG 341C" in descriptions and "NVIDIA" in gpu:
        return "desktop-ultrawide-nvidia"
    return None


def monitor_facts() -> list[dict[str, object]]:
    if not shutil.which("hyprctl"):
        return []
    result = subprocess.run(
        ("hyprctl", "-j", "monitors", "all"),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode:
        return []
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def render_monitor(
    output: str, mode: str, position: str, scale: str, include_gdk: bool = True
) -> str:
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
    return (
        prefix
        + f'hl.monitor({{ output = "{output}", mode = "{mode}", '
        + f'position = "{position}", scale = {scale_value} }})\n'
    )


def detect_host_state(workspace: Workspace) -> HostState:
    packages = frozenset()
    package_versions: dict[str, str] = {}
    foreign_packages = frozenset()
    if shutil.which("pacman"):
        rows = subprocess.run(
            ("pacman", "-Q"), check=True, text=True, stdout=subprocess.PIPE
        ).stdout.splitlines()
        for row in rows:
            name, version = row.split(maxsplit=1)
            package_versions[name] = version
        packages = frozenset(package_versions)
        foreign_packages = frozenset(
            subprocess.run(
                ("pacman", "-Qmq"), check=True, text=True, stdout=subprocess.PIPE
            ).stdout.splitlines()
        )
    wanted = {
        command for implementation in workspace.implementations.values() for command in implementation.commands
    }
    return HostState(
        packages,
        frozenset(command for command in wanted if shutil.which(command)),
        package_versions,
        foreign_packages,
    )


def load_host_state(path: Path) -> HostState:
    value = json.loads(path.read_text())
    return HostState(
        frozenset(str(item) for item in value.get("packages", [])),
        frozenset(str(item) for item in value.get("commands", [])),
        {str(key): str(version) for key, version in value.get("package_versions", {}).items()},
        frozenset(str(item) for item in value.get("foreign_packages", [])),
    )


def read_plan(path: Path) -> ExecutionPlan:
    return parse_plan_json(path.read_bytes())


def write_plan(path: Path, plan: ExecutionPlan) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(plan.to_dict(), stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def print_plan(
    plan: ExecutionPlan, workspace: Workspace, hardware: str, default_agent: str
) -> None:
    print(f"{plan.platform.platform.value} bootstrap plan")
    print(f"Hardware: {hardware}")
    print(f"Default agent: {default_agent}")
    print("Selected features:")
    for feature_id in plan.selected:
        feature = workspace.public_catalog[feature_id]
        if feature.visible:
            suffix = f" [unavailable: {plan.unavailable[feature_id]}]" if feature_id in plan.unavailable else ""
            print(f"  - {feature.label}{suffix}")
    counts: dict[str, int] = {}
    for action in plan.actions:
        counts[action.kind.value] = counts.get(action.kind.value, 0) + 1
    print("Actions:")
    for kind, count in sorted(counts.items()):
        print(f"  - {kind}: {count}")
    repository_actions = [
        action for action in plan.actions if action.kind.value == "repository-packages"
    ]
    if repository_actions:
        print("Repository transactions:")
        for action in repository_actions:
            for package in action.data["transaction"]:
                print(
                    f"  - {package['repository']}/{package['name']} "
                    f"{package['version']} ({action.feature})"
                )
    aur_actions = [action for action in plan.actions if action.kind.value == "aur-build"]
    if aur_actions:
        print("AUR recipes requiring per-package approval during apply:")
        for action in aur_actions:
            print(
                f"  - {action.data['package_base']} {action.data['version']} "
                f"at {action.data['commit']} ({action.feature})"
            )
    print(f"Digest: {plan.digest}")


def print_audit(findings: tuple[AuditFinding, ...]) -> None:
    groups: dict[tuple[str, str], list[str]] = {}
    for finding in findings:
        groups.setdefault((finding.status, finding.feature), []).append(finding.message)
    order = {"FAIL": 0, "WARN": 1, "PASS": 2}
    for (status, feature), messages in sorted(
        groups.items(), key=lambda item: (order[item[0][0]], item[0][1])
    ):
        detail = messages[0]
        if len(messages) > 1:
            detail = f"{len(messages)} checks; " + "; ".join(messages[:3])
            if len(messages) > 3:
                detail += f"; and {len(messages) - 3} more"
        print(f"{status:<4} {feature:<24} {detail}")


def gum_input(header: str, value: str) -> str:
    return subprocess.run(
        ("gum", "input", "--header", header, "--value", value),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


def confirm(prompt: str) -> bool:
    if shutil.which("gum"):
        return subprocess.run(("gum", "confirm", prompt)).returncode == 0
    return input(f"{prompt} [y/N] ").lower() in {"y", "yes"}


def split_values(values: list[str]) -> set[str]:
    return {item.strip() for value in values for item in value.split(",") if item.strip()}


if __name__ == "__main__":
    raise SystemExit(main())
