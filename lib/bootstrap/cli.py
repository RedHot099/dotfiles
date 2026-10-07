from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from .catalog import CatalogError, Workspace
from .audit import audit_install
from .domain import (
    DesktopRequest,
    IntegrationsRequest,
    PackagesRequest,
    PlanHostMismatch,
    PlanSchemaError,
    WorkflowId,
)
from .execution import apply_workflow_plan, execution_plan, execution_workspace
from .files import HomeFiles
from .host import LocalHostProbe
from .planner import HostState
from .planning.model import PackagesEvidence, WorkflowPlan, plan_from_dict
from .platform import PlatformDetectionError, detect_platform
from .repository import compile_repository
from .state import SelectionRecord, StateStore
from .ssh import fetch_github_keys, ssh_fingerprint
from .tui.model import ChoiceRow, SelectorState
from .tui.screens import select
from .tui.terminal import ask_yes_no
from .workflows import plan_desktop, plan_integrations, plan_packages


ROOT = Path(__file__).resolve().parents[2]
EXIT_READY = 0
EXIT_DECLINED = 1
EXIT_INCOMPLETE = 3
# INCOMPLETE means deferred logins or skipped AUR builds, not a failed change.
SETUP_STATUSES = {EXIT_READY: "READY", EXIT_DECLINED: "SKIPPED", EXIT_INCOMPLETE: "INCOMPLETE"}
WORKFLOW_ERRORS = (
    CatalogError,
    PlanHostMismatch,
    PlanSchemaError,
    PlatformDetectionError,
    OSError,
    RuntimeError,
    subprocess.CalledProcessError,
    json.JSONDecodeError,
    ValueError,
)


def main(argv: list[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    try:
        if args.command == "setup":
            return setup_command()
        return workflow_command(WorkflowId(args.command), args.operation)
    except WORKFLOW_ERRORS as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Cancelled.")
        return 130


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Configure a supported Arch Hyprland installation")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup", help="Run Packages, Desktop, and Integrations")
    for workflow in WorkflowId:
        command = commands.add_parser(workflow.value, help=f"Manage {workflow.value}")
        command.add_argument("operation", choices=("plan", "apply", "audit"))
    return parser


def workflow_command(workflow: WorkflowId, operation: str) -> int:
    facts = detect_platform(LocalHostProbe(Path.home()))
    repository = compile_repository(ROOT, facts.platform)
    if operation == "plan":
        plan = interactive_workflow_plan(workflow, repository, facts)
        save_workflow_plan(plan)
        print_workflow_plan(plan)
        return 0
    plan = load_latest_workflow_plan(workflow)
    if plan.header.repository_digest != repository.source_digest:
        raise CatalogError("repository changed after planning; run plan again")
    if operation == "audit":
        findings = audit_install(
            execution_workspace(repository, workflow),
            execution_plan(repository, plan),
            facts,
        )
        for finding in findings:
            print(f"{finding.status:4} {finding.feature}: {finding.message}")
        return int(any(finding.status == "FAIL" for finding in findings))
    if not confirm(f"Apply reviewed {workflow.value} plan {plan.digest[:12]}?"):
        print("Aborted.")
        return EXIT_DECLINED
    if workflow is WorkflowId.PACKAGES and plan.actions:
        subprocess.run(("/usr/bin/sudo", "-v"), check=True)
    result = apply_workflow_plan(
        ROOT,
        repository,
        plan,
        facts,
        system_changes=True,
        interactive=sys.stdin.isatty(),
    )
    status = "READY" if not result.skipped_features and not result.simulated else "INCOMPLETE"
    print(f"{workflow.value.title()}: {status}")
    print(f"Changed: {result.changed}; unchanged: {result.unchanged}; deferred: {result.simulated}")
    return EXIT_READY if status == "READY" else EXIT_INCOMPLETE


def setup_command() -> int:
    statuses: list[tuple[str, str]] = []
    for workflow in WorkflowId:
        print(f"\n{workflow.value.title()}")
        if not confirm(f"Configure {workflow.value} now?"):
            statuses.append((workflow.value, "SKIPPED"))
            continue
        # A failed workflow must not stop the later ones.
        try:
            code = workflow_command(workflow, "plan")
            if code == 0:
                code = workflow_command(workflow, "apply")
        except WORKFLOW_ERRORS as error:
            print(f"FAIL: {error}", file=sys.stderr)
            code = 2
        statuses.append((workflow.value, SETUP_STATUSES.get(code, "FAIL")))
    print("\nSummary")
    for name, status in statuses:
        print(f"{name.title():14} {status}")
    return int(any(status in {"FAIL", "INCOMPLETE"} for _, status in statuses))


def _usb_vendor_present(vendor: str, root: Path = Path("/sys/bus/usb/devices")) -> bool:
    for path in root.glob("*/idVendor"):
        try:
            if path.read_text().strip() == vendor:
                return True
        except OSError:
            continue
    return False


def _fan_control_present(root: Path = Path("/sys/class/hwmon")) -> bool:
    return any(root.glob("hwmon*/pwm[0-9]"))


# A catalog hardware hint is shown only when its hardware is present.
HARDWARE_PROBES = {
    "solaar": lambda: _usb_vendor_present("046d"),
    "cooler-control": _fan_control_present,
}


def hardware_hint(application_id: str, hint: str | None) -> str | None:
    probe = HARDWARE_PROBES.get(application_id)
    return hint if hint and probe is not None and probe() else None


def interactive_workflow_plan(workflow, repository, facts) -> WorkflowPlan:
    workspace = execution_workspace(repository, workflow)
    state = detect_host_state(workspace)
    store = StateStore(Path(facts.target_home))
    previous = store.read_selection(workflow)
    if workflow is WorkflowId.PACKAGES:
        rows = tuple(
            ChoiceRow(
                item.id,
                item.group,
                item.label,
                item.id in previous.selected if previous else item.default,
                bool(item.commands) and all(shutil.which(command) for command in item.commands),
                hardware_hint(item.id, item.hardware_hint),
            )
            for item in repository.applications.values()
            if item.visible
        )
        selected = select("Select applications", SelectorState(rows)).selected_ids()
        selected |= frozenset(
            item.id for item in repository.applications.values() if item.default and not item.visible
        )
        plan = plan_packages(repository, facts, state, PackagesRequest(selected))
    else:
        actual = repository.workflow(workflow).workspace
        assert actual is not None
        rows = tuple(
            ChoiceRow(item.id, item.group, item.label, item.id in previous.selected if previous else item.default)
            for item in actual.public_catalog.values()
            if item.visible
        )
        selected = select(f"Select {workflow.value}", SelectorState(rows)).selected_ids()
        package_selection = store.read_selection(WorkflowId.PACKAGES)
        evidence = PackagesEvidence.create(
            package_selection.selected if package_selection else frozenset(),
            frozenset(state.packages | state.commands),
        )
        if workflow is WorkflowId.DESKTOP:
            monitor = detect_monitor_content()
            plan = plan_desktop(
                ROOT,
                repository,
                facts,
                state,
                DesktopRequest(selected, "detected" if monitor else "generic"),
                evidence,
                monitor_content=monitor,
            )
        else:
            agents = frozenset(item for item in selected if item.startswith("agent."))
            github_keys = reviewed_github_keys(actual, selected)
            plan = plan_integrations(
                ROOT,
                repository,
                facts,
                state,
                IntegrationsRequest(
                    selected - agents,
                    agents,
                    select_skills(previous),
                    select_harnesses(previous),
                ),
                evidence,
                github_keys=github_keys,
            )
    saved = selected
    if workflow is WorkflowId.INTEGRATIONS:
        saved |= frozenset(f"skill:{item}" for item in plan.request.skills)
        saved |= frozenset(f"harness:{item}" for item in plan.request.harnesses)
    store.write_selection(SelectionRecord(workflow, saved, repository.source_digest))
    return plan


def select_skills(previous: SelectionRecord | None) -> frozenset[str]:
    directory = ROOT / "integrations/common/skills/private"
    saved = {item.removeprefix("skill:") for item in previous.selected if item.startswith("skill:")} if previous else set()
    rows = tuple(
        ChoiceRow(path.name, "Skills", path.name, path.name in saved if saved else True)
        for path in sorted(directory.iterdir()) if path.is_dir()
    )
    return select("Select skills for every chosen harness", SelectorState(rows)).selected_ids()


def select_harnesses(previous: SelectionRecord | None) -> frozenset[str]:
    data = tomllib.loads((ROOT / "integrations/common/harnesses.toml").read_text())
    saved = {item.removeprefix("harness:") for item in previous.selected if item.startswith("harness:")} if previous else set()
    rows = tuple(
        ChoiceRow(item["id"], "Harnesses", item["label"], item["id"] in saved if saved else bool(item.get("default", False)))
        for item in data["harnesses"]
    )
    return select("Select agent harnesses", SelectorState(rows)).selected_ids()


def reviewed_github_keys(workspace: Workspace, selected: frozenset[str]) -> dict[str, tuple[str, ...]]:
    usernames = {
        workspace.implementations[feature].github_ssh_user
        for feature in selected
        if feature in workspace.implementations
        and workspace.implementations[feature].github_ssh_user
    }
    reviewed: dict[str, tuple[str, ...]] = {}
    for username in sorted(usernames):
        assert username is not None
        keys = fetch_github_keys(username)
        print(f"\nGitHub public keys for {username}:")
        for key in keys:
            print(f"  {ssh_fingerprint(key)}")
        if not confirm("Trust these public keys for incoming SSH access?"):
            raise CatalogError("SSH key approval was declined")
        reviewed[username] = keys
    return reviewed


def detect_monitor_content() -> str | None:
    if not shutil.which("hyprctl") or not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return None
    result = subprocess.run(
        ("hyprctl", "monitors", "all", "-j"),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    monitors = json.loads(result.stdout)
    if not isinstance(monitors, list) or not monitors:
        return None
    lines = ['hl.env("GDK_SCALE", "2")']
    for monitor in monitors:
        if not isinstance(monitor, dict) or monitor.get("disabled"):
            continue
        name = monitor.get("name")
        values = (monitor.get("width"), monitor.get("height"), monitor.get("refreshRate"), monitor.get("x"), monitor.get("y"), monitor.get("scale"))
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", name):
            raise CatalogError("Hyprland returned an unsafe monitor name")
        width, height, refresh, x, y, scale = values
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
            raise CatalogError(f"Hyprland returned invalid geometry for {name}")
        if width <= 0 or height <= 0 or refresh <= 0 or scale <= 0:
            raise CatalogError(f"Hyprland returned invalid monitor values for {name}")
        lines.append(
            f'hl.monitor({{ output = "{name}", mode = "{int(width)}x{int(height)}@{float(refresh):.2f}", '
            f'position = "{int(x)}x{int(y)}", scale = {float(scale):g} }})'
        )
    return "\n".join(lines) + "\n" if len(lines) > 1 else None


def save_workflow_plan(plan: WorkflowPlan) -> Path:
    target = f".local/state/arch-hypr-bootstrap/plans/{plan.header.workflow.value}/{plan.digest}.json"
    path = Path(plan.header.target_home) / target
    content = json.dumps(plan.to_dict(), indent=2, sort_keys=True) + "\n"
    with HomeFiles(Path(plan.header.target_home)) as home:
        existing = home.read_text(target)
        if existing is not None and existing != content:
            raise PlanSchemaError("digest-addressed plan content differs from existing plan")
        if existing is None:
            home.ensure_directory(f".local/state/arch-hypr-bootstrap/plans/{plan.header.workflow.value}", 0o700)
            home.write_private_atomic(target, content.encode())
    return path


def load_latest_workflow_plan(workflow: WorkflowId) -> WorkflowPlan:
    directory = Path.home() / ".local/state/arch-hypr-bootstrap/plans" / workflow.value
    paths = sorted(directory.glob("*.json"), key=lambda item: item.stat().st_mtime_ns, reverse=True)
    if not paths:
        raise CatalogError(f"no reviewed {workflow.value} plan; run './bootstrap {workflow.value} plan'")
    plan = plan_from_dict(json.loads(paths[0].read_text()))
    if plan.header.workflow is not workflow:
        raise PlanSchemaError("saved plan workflow mismatch")
    return plan


def print_workflow_plan(plan: WorkflowPlan) -> None:
    print(f"\nWorkflow: {plan.header.workflow.value}\nPlan: {plan.digest}")
    for item in plan.actions:
        print(f"  {item.kind.value}: {item.feature}")
    if plan.header.workflow is WorkflowId.INTEGRATIONS and "bitbucket" in plan.request.integrations:
        print("  Bitbucket: the login queue adds your SSH key to Bitbucket; no token is stored.")


def detect_host_state(workspace: Workspace) -> HostState:
    versions: dict[str, str] = {}
    foreign = frozenset()
    if shutil.which("pacman"):
        for row in subprocess.run(("pacman", "-Q"), check=True, text=True, stdout=subprocess.PIPE).stdout.splitlines():
            name, version = row.split(maxsplit=1)
            versions[name] = version
        foreign = query_foreign_packages()
    wanted = {command for implementation in workspace.implementations.values() for command in implementation.commands}
    return HostState(
        frozenset(versions),
        frozenset(command for command in wanted if shutil.which(command)),
        versions,
        foreign,
        detect_gpu_vendors(),
    )


PCI_GPU_VENDORS = {"0x1002": "amd", "0x8086": "intel", "0x10de": "nvidia"}


def detect_gpu_vendors(root: Path = Path("/sys/bus/pci/devices")) -> frozenset[str]:
    vendors: set[str] = set()
    for device in root.glob("*"):
        try:
            if not (device / "class").read_text().startswith("0x03"):
                continue
            vendor = PCI_GPU_VENDORS.get((device / "vendor").read_text().strip())
        except OSError:
            continue
        if vendor:
            vendors.add(vendor)
    return frozenset(vendors)


def query_foreign_packages() -> frozenset[str]:
    result = subprocess.run(("pacman", "-Qmq"), check=False, text=True, stdout=subprocess.PIPE)
    if result.returncode not in (0, 1):
        result.check_returncode()
    return frozenset(result.stdout.splitlines())


def confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        raise CatalogError("interactive mode requires a terminal")
    return ask_yes_no(prompt)


if __name__ == "__main__":
    raise SystemExit(main())
