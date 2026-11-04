from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import agent
from .catalog import CatalogError, Workspace
from .audit import audit_install
from .domain import (
    ActionKind,
    DesktopRequest,
    IntegrationsRequest,
    PackagesRequest,
    PlanHostMismatch,
    PlanSchemaError,
    WorkflowId,
)
from .execution import apply_workflow_plan, execution_plan, execution_workspace
from .executor import (
    ApplyLocked,
    Declined,
    LocalEditConflict,
    NeedsTerminal,
    local_conflicts,
    reload_hyprland,
    restore_files,
    run,
    terminal_pending,
)
from .files import HomeFiles
from .host import LocalHostProbe
from .planner import HostState
from .planning.model import PackagesEvidence, WorkflowPlan, plan_from_dict
from .platform import PlatformDetectionError, detect_platform
from .repository import compile_repository
from .session import session_environment
from .state import SelectionRecord, StateStore, read_managed
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
# Skills and global agent instructions belong to fleet; dotfiles never runs it.
FLEET_HINT = (
    "Agent skills and instructions come from RedHot099/fleet: "
    "gh repo clone RedHot099/fleet ~/projects/fleet, "
    "then ~/projects/fleet/bin/fleet plan and ~/projects/fleet/bin/fleet apply."
)
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
    parser = create_parser()
    args = parser.parse_args(argv)
    if args.command != "setup":
        problem = option_problem(args)
        if problem:
            parser.error(problem)
    if args.command != "setup" and args.json:
        return json_command(args)
    try:
        if args.command == "setup":
            return setup_command()
        workflow = WorkflowId(args.command)
        if args.operation == "plan" and (args.add or args.remove):
            plan, report = agent_plan(workflow, frozenset(args.add), frozenset(args.remove))
            print_workflow_plan(plan)
            print_change_summary(report)
            return 0
        if args.operation in {"status", "restore"} or args.plan:
            report, code = agent_command(args, workflow)
            print_report(report)
            return code
        return workflow_command(workflow, args.operation)
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
        command.add_argument("operation", choices=("plan", "apply", "audit", "status", "restore"))
        command.add_argument("--json", action="store_true", help="never prompt; print one JSON report on stdout")
        command.add_argument("--plan", metavar="DIGEST", help="the full digest of a saved plan; naming it approves it")
        command.add_argument("--add", action="append", default=[], metavar="ID", help="plan: select ID (no selector)")
        command.add_argument("--remove", action="append", default=[], metavar="ID", help="plan: clear ID (no selector)")
        command.add_argument("--discard-local", action="store_true", help="apply/restore: replace files changed outside the bootstrap")
        command.add_argument("--in-terminal", action="store_true", help="apply: run the approved plan in a terminal on the user's session")
        command.add_argument("--wait", type=int, default=0, metavar="SECONDS", help="status: wait for a running or handed-off apply")
    return parser


def option_problem(args: argparse.Namespace) -> str | None:
    operation = args.operation
    if (args.add or args.remove) and operation != "plan":
        return "--add and --remove belong to plan"
    if args.plan and operation == "plan":
        return "plan creates a digest; --plan names an existing one"
    if operation == "restore" and not args.plan:
        return "restore needs --plan DIGEST"
    if args.discard_local and operation not in {"apply", "restore"}:
        return "--discard-local belongs to apply and restore"
    if args.in_terminal and (operation != "apply" or not args.plan):
        return "--in-terminal needs apply --plan DIGEST"
    if args.wait and operation != "status":
        return "--wait belongs to status"
    if args.wait < 0:
        return "--wait must not be negative"
    return None


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
    code = EXIT_READY if status == "READY" else EXIT_INCOMPLETE
    StateStore(Path(facts.target_home)).write_result_locked(
        workflow, agent.result_record(workflow.value, plan.digest, status, code, result=result)
    )
    print(f"{workflow.value.title()}: {status}")
    print(f"Changed: {result.changed}; unchanged: {result.unchanged}; deferred: {result.simulated}")
    return code


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
    print(f"\n{FLEET_HINT}")
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


def visible_catalog(repository, workflow: WorkflowId) -> dict[str, tuple[str, bool]]:
    """Visible catalog ID -> (label, default) for one workflow."""
    if workflow is WorkflowId.PACKAGES:
        items = repository.applications.values()
    else:
        actual = repository.workflow(workflow).workspace
        assert actual is not None
        items = actual.public_catalog.values()
    return {item.id: (item.label, item.default) for item in items if item.visible}


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
    else:
        actual = repository.workflow(workflow).workspace
        assert actual is not None
        rows = tuple(
            ChoiceRow(item.id, item.group, item.label, item.id in previous.selected if previous else item.default)
            for item in actual.public_catalog.values()
            if item.visible
        )
        selected = select(f"Select {workflow.value}", SelectorState(rows)).selected_ids()
    return plan_for_selection(workflow, repository, facts, state, store, selected, interactive=True)


def plan_for_selection(workflow, repository, facts, state, store, selected, *, interactive: bool) -> WorkflowPlan:
    """Plan one workflow for a selection and save that selection."""
    if workflow is WorkflowId.PACKAGES:
        selected |= frozenset(
            item.id for item in repository.applications.values() if item.default and not item.visible
        )
        plan = plan_packages(repository, facts, state, PackagesRequest(selected))
    else:
        actual = repository.workflow(workflow).workspace
        assert actual is not None
        package_selection = store.read_selection(WorkflowId.PACKAGES)
        evidence = PackagesEvidence.create(
            package_selection.selected if package_selection else frozenset(),
            frozenset(state.packages | state.commands),
        )
        if workflow is WorkflowId.DESKTOP:
            session = session_environment()
            # Without the session the monitor falls back to a generic layout;
            # an agent must not replace a real monitor setup with it.
            if session is None and not interactive:
                raise CatalogError("NEEDS SESSION: desktop planning reads the monitors from a running Hyprland session")
            monitor = detect_monitor_content(session)
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
            github_keys = reviewed_github_keys(actual, selected, interactive=interactive)
            plan = plan_integrations(
                ROOT,
                repository,
                facts,
                state,
                IntegrationsRequest(selected - agents, agents),
                evidence,
                github_keys=github_keys,
            )
    known = frozenset(visible_catalog(repository, workflow))
    store.write_selection(SelectionRecord(workflow, selected, repository.source_digest, known))
    return plan


def reviewed_github_keys(
    workspace: Workspace, selected: frozenset[str], *, interactive: bool = True
) -> dict[str, tuple[str, ...]]:
    """Fetch the GitHub keys to trust for incoming SSH.

    Without a terminal the keys go into the plan unasked: the plan report
    lists their fingerprints, and only a terminal apply installs them.
    """
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
        if interactive:
            print(f"\nGitHub public keys for {username}:")
            for key in keys:
                print(f"  {ssh_fingerprint(key)}")
            if not confirm("Trust these public keys for incoming SSH access?"):
                raise CatalogError("SSH key approval was declined")
        reviewed[username] = keys
    return reviewed


def detect_monitor_content(environment: dict[str, str] | None = None) -> str | None:
    if environment is None and os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        environment = dict(os.environ)
    if not shutil.which("hyprctl") or environment is None:
        return None
    result = subprocess.run(
        ("hyprctl", "monitors", "all", "-j"),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        env=environment,
    )
    monitors = json.loads(result.stdout)
    if not isinstance(monitors, list) or not monitors:
        return None
    entries: list[tuple[str, str, str, float]] = []
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
        entries.append((name, f"{int(width)}x{int(height)}@{float(refresh):.2f}", f"{int(x)}x{int(y)}", float(scale)))
    if not entries:
        return None
    # `omarchy hyprland monitor scaling` persists a new scale only by rewriting
    # these locals, so a single monitor reads its scale from them.
    single = len(entries) == 1
    lines = ["local omarchy_gdk_scale = 2"]
    if single:
        lines.append(f"local omarchy_monitor_scale = {entries[0][3]:g}")
    lines += ["", 'hl.env("GDK_SCALE", tostring(omarchy_gdk_scale))']
    for name, mode, position, scale in entries:
        value = "omarchy_monitor_scale" if single else f"{scale:g}"
        lines.append(f'hl.monitor({{ output = "{name}", mode = "{mode}", position = "{position}", scale = {value} }})')
    return "\n".join(lines) + "\n"


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


class StalePlan(CatalogError):
    pass


DIGEST_RE = re.compile(r"[0-9a-f]{64}")
STATE_PLANS = ".local/state/arch-hypr-bootstrap/plans"
ACTIVE_STATUSES = {"RUNNING", "HANDED_OFF"}


def bootstrap_command(*arguments: str) -> str:
    return " ".join((str(ROOT / "bootstrap"), *arguments))


def json_command(args: argparse.Namespace) -> int:
    workflow = WorkflowId(args.command)
    with agent.json_stdout() as descriptor:
        try:
            if args.operation == "plan":
                _, report = agent_plan(workflow, frozenset(args.add), frozenset(args.remove))
                code = agent.EXIT_READY
            else:
                report, code = agent_command(args, workflow)
        except WORKFLOW_ERRORS as error:
            status, code, next_actions = classify_error(error)
            report = {
                "schema": agent.REPORT_SCHEMA,
                "command": args.operation,
                "workflow": workflow.value,
                "plan_digest": args.plan,
                "status": status,
                "message": str(error),
                "next_actions": next_actions,
            }
        except KeyboardInterrupt:
            report = {"schema": agent.REPORT_SCHEMA, "command": args.operation, "workflow": workflow.value, "status": "CANCELLED"}
            code = 130
        agent.emit(descriptor, report)
    return code


def classify_error(error: Exception) -> tuple[str, int, list[dict[str, str]]]:
    message = str(error)
    if isinstance(error, StalePlan):
        return "STALE", agent.EXIT_ACTION_NEEDED, [{"who": "agent", "why": "plan again", "command": ""}]
    if message.startswith("NEEDS PACKAGES: "):
        missing = message.removeprefix("NEEDS PACKAGES: ").replace(",", " ").split()
        command = bootstrap_command("packages", "plan", "--json", *(f"--add {item}" for item in missing))
        return "NEEDS_PACKAGES", agent.EXIT_ACTION_NEEDED, [{"who": "agent", "why": "install the prerequisites first", "command": command}]
    if message.startswith("package databases are stale or missing"):
        # The bootstrap never refreshes or updates the distribution itself.
        return "NEEDS_SYSTEM_UPDATE", agent.EXIT_ACTION_NEEDED, [{"who": "user", "why": "run omarchy update, then plan again", "command": "omarchy update"}]
    if message.startswith("NEEDS SESSION: "):
        return "NEEDS_SESSION", agent.EXIT_ACTION_NEEDED, [{"who": "user", "why": "log in to the Hyprland session, then plan again", "command": ""}]
    return "FAIL", agent.EXIT_FAIL, []


def agent_command(args: argparse.Namespace, workflow: WorkflowId) -> tuple[dict[str, object], int]:
    if args.operation == "status":
        return status_command(workflow, args.plan, args.wait)
    if args.operation == "restore":
        return restore_command(workflow, args.plan, args.discard_local)
    if args.operation == "audit":
        return audit_command(workflow, args.plan)
    if args.operation == "apply":
        if not args.plan:
            raise CatalogError("apply --json needs --plan DIGEST from a reviewed plan report")
        return approved_apply(
            workflow,
            args.plan,
            discard_local=args.discard_local,
            in_terminal=args.in_terminal,
            prompts=not args.json and sys.stdin.isatty(),
        )
    raise CatalogError(f"unsupported operation: {args.operation}")


def agent_plan(
    workflow: WorkflowId, add: frozenset[str], remove: frozenset[str]
) -> tuple[WorkflowPlan, dict[str, object]]:
    """Plan without the selector: the saved selection, or the defaults, plus add/remove."""
    facts = detect_platform(LocalHostProbe(Path.home()))
    repository = compile_repository(ROOT, facts.platform)
    catalog = visible_catalog(repository, workflow)
    unknown = (add | remove) - catalog.keys()
    if unknown:
        raise CatalogError(f"unknown {workflow.value} IDs: {', '.join(sorted(unknown))}")
    if add & remove:
        raise CatalogError(f"IDs both added and removed: {', '.join(sorted(add & remove))}")
    store = StateStore(Path(facts.target_home))
    previous = store.read_selection(workflow)
    if workflow is WorkflowId.PACKAGES:
        every = frozenset(repository.applications)
    else:
        workspace = repository.workflow(workflow).workspace
        assert workspace is not None
        every = frozenset(workspace.public_catalog)
    base = previous.selected if previous else frozenset(item for item, (_, default) in catalog.items() if default)
    selected = ((base & every) | add) - remove
    new_items = sorted(catalog.keys() - previous.known) if previous and previous.known is not None else []
    state = detect_host_state(execution_workspace(repository, workflow))
    plan = plan_for_selection(workflow, repository, facts, state, store, selected, interactive=False)
    path = save_workflow_plan(plan)
    with HomeFiles(Path(facts.target_home)) as home:
        changes = agent.describe_changes(plan, home, read_managed(home, workflow.value))
    checkout = agent.checkout_state(ROOT)
    next_actions: list[dict[str, object]] = []
    problem = agent.checkout_problem(checkout)
    if problem:
        next_actions.append({"who": "user", "why": f"apply refuses this checkout: {problem}", "command": ""})
    files = changes["files"]
    assert isinstance(files, dict)
    conflicts = [*files["local-edit"], *files["unmanaged"]]
    apply_command = bootstrap_command(workflow.value, "apply", "--plan", plan.digest, "--json")
    if conflicts:
        next_actions.append(
            {
                "who": "user",
                "why": "approve replacing files changed outside the bootstrap (each is backed up); then apply with --discard-local",
                "command": f"{apply_command} --discard-local",
                "files": conflicts,
            }
        )
    next_actions.append({"who": "agent", "why": "apply the reviewed plan", "command": apply_command})
    report: dict[str, object] = {
        "schema": agent.REPORT_SCHEMA,
        "command": "plan",
        "workflow": workflow.value,
        "status": "PLANNED",
        "plan_digest": plan.digest,
        "plan_path": str(path),
        "checkout": checkout,
        "selection": {
            "selected": sorted(selected),
            "new_items": [{"id": item, "label": catalog[item][0], "default": catalog[item][1]} for item in new_items],
            "dropped_items": sorted(base - every),
        },
        "changes": changes,
        "unavailable": list(getattr(plan, "unavailable", ())),
        "next_actions": next_actions,
    }
    return plan, report


def load_workflow_plan(workflow: WorkflowId, digest: str) -> WorkflowPlan:
    if not DIGEST_RE.fullmatch(digest):
        raise CatalogError("--plan needs the full 64-character plan digest")
    path = Path.home() / STATE_PLANS / workflow.value / f"{digest}.json"
    if not path.is_file():
        raise StalePlan(f"no saved {workflow.value} plan {digest[:12]}; plan again")
    plan = plan_from_dict(json.loads(path.read_text()))
    if plan.header.workflow is not workflow or plan.digest != digest:
        raise PlanSchemaError("saved plan does not match its digest or workflow")
    return plan


def approved_apply(
    workflow: WorkflowId, digest: str, *, discard_local: bool, in_terminal: bool, prompts: bool
) -> tuple[dict[str, object], int]:
    try:
        return _approved_apply(workflow, digest, discard_local=discard_local, in_terminal=in_terminal, prompts=prompts)
    except WORKFLOW_ERRORS as error:
        # Saved also when the run fails before it takes the lock, so a
        # handed-off terminal reports its real cause instead of HANDOFF_LOST.
        status, code, next_actions = classify_error(error)
        # Only for a saved plan: a mistyped digest keeps the last real outcome.
        if DIGEST_RE.fullmatch(digest) and (Path.home() / STATE_PLANS / workflow.value / f"{digest}.json").is_file():
            StateStore(Path.home()).write_result_locked(
                workflow,
                agent.result_record(workflow.value, digest, status, code, message=str(error), next_actions=next_actions),
            )
        raise


def _approved_apply(
    workflow: WorkflowId, digest: str, *, discard_local: bool, in_terminal: bool, prompts: bool
) -> tuple[dict[str, object], int]:
    """Apply the plan named by its digest; naming it is the approval.

    Without a terminal it never prompts: packages, system services, the
    firewall, and incoming SSH keys stop it with NEEDS_TERMINAL before any
    change, and logins stay queued. Every outcome is saved for `status`.
    """
    facts = detect_platform(LocalHostProbe(Path.home()))
    repository = compile_repository(ROOT, facts.platform)
    plan = load_workflow_plan(workflow, digest)
    store = StateStore(Path(facts.target_home))
    checkout = agent.checkout_state(ROOT)
    terminal = agent.terminal_command(ROOT, workflow.value, digest, discard_local)
    handoff = bootstrap_command(workflow.value, "apply", "--plan", digest, "--json", "--in-terminal", *(("--discard-local",) if discard_local else ()))

    def finish(status: str, code: int, message: str = "", **extra: object) -> tuple[dict[str, object], int]:
        record = agent.result_record(workflow.value, digest, status, code, message=message, checkout=checkout, **extra)
        store.write_result_locked(workflow, record)
        return {**record, "command": "apply"}, code

    if plan.header.repository_digest != repository.source_digest:
        raise StalePlan("the repository changed after planning; plan again")
    current = store.read_result(workflow)
    if current is not None and current.get("status") == "RUNNING" and _process_alive(current.get("pid")):
        return busy(workflow, digest)
    problem = agent.checkout_problem(checkout)
    if problem:
        return finish("BLOCKED", agent.EXIT_ACTION_NEEDED, f"{problem}; ask the user", next_actions=[{"who": "user", "why": problem, "command": ""}])
    try:
        execution = execution_plan(repository, plan)
        with HomeFiles(Path(plan.header.target_home)) as home:
            conflicts = () if discard_local else local_conflicts(home, plan.actions, read_managed(home, workflow.value))
            pending = terminal_pending(execution, home)
            changes = agent.describe_changes(plan, home, {}) if prompts and pending else None
        if conflicts:
            return finish(
                "CONFLICT",
                agent.EXIT_ACTION_NEEDED,
                "files changed outside the bootstrap; ask the user before replacing them",
                conflicts=list(conflicts),
                next_actions=[{"who": "user", "why": "approve replacing these files (each is backed up)", "command": f"{bootstrap_command(workflow.value, 'apply', '--plan', digest, '--json')} --discard-local"}],
            )
        if in_terminal:
            session = session_environment()
            if session is None:
                return finish(
                    "NEEDS_TERMINAL",
                    agent.EXIT_ACTION_NEEDED,
                    "no Hyprland session to open a terminal on",
                    terminal_required=list(pending),
                    next_actions=[{"who": "user", "why": "run this in a terminal", "command": shlex.join(terminal)}],
                )
            # Saved before the launch: the terminal run overwrites it with
            # RUNNING as soon as it starts.
            handed_off = finish(
                "HANDED_OFF",
                agent.EXIT_ACTION_NEEDED,
                "a terminal opened on the session; the user types the sudo password there",
                terminal_required=list(pending),
                handed_off_epoch=time.time(),
                next_actions=[{"who": "agent", "why": "wait for the terminal apply", "command": bootstrap_command(workflow.value, "status", "--plan", digest, "--wait", "900", "--json")}],
            )
            try:
                agent.launch_terminal(terminal, session)
            except (OSError, CatalogError) as error:
                return finish(
                    "NEEDS_TERMINAL",
                    agent.EXIT_ACTION_NEEDED,
                    f"could not open a terminal: {error}",
                    terminal_required=list(pending),
                    next_actions=[{"who": "user", "why": "run this in a terminal", "command": shlex.join(terminal)}],
                )
            return handed_off
        def locked() -> None:
            # Saved once the lock is held and before any prompt: a terminal
            # closed at the password prompt reads as INTERRUPTED, and a second
            # apply that loses the lock never overwrites this record.
            store.write_result(workflow, agent.result_record(workflow.value, digest, "RUNNING", agent.EXIT_ACTION_NEEDED, checkout=checkout, pid=os.getpid()))
            if not (prompts and pending):
                return
            print(f"\n{workflow.value.title()} plan {digest[:12]} needs your authority for:")
            for item in pending:
                print(f"  {item}")
            assert changes is not None
            for user, fingerprints in dict(changes["new_ssh_keys"]).items():
                print(f"  incoming SSH keys from {user}: {', '.join(fingerprints)}")
            if any(not item.startswith(f"{ActionKind.AUTHORIZED_SSH_KEYS.value}:") for item in pending):
                print("sudo asks for your password now; pacman may ask before its transaction.")
                subprocess.run(("/usr/bin/sudo", "-v"), check=True)
            elif not confirm("Trust these SSH keys for incoming access?"):
                raise Declined("SSH key trust was declined")

        result = apply_workflow_plan(
            ROOT,
            repository,
            plan,
            facts,
            system_changes=True,
            interactive=prompts,
            reviewed=True,
            discard_local=discard_local,
            on_locked=locked,
        )
    except ApplyLocked:
        return busy(workflow, digest)
    except Declined as error:
        return finish("DECLINED", agent.EXIT_DRIFT, str(error))
    except NeedsTerminal as error:
        return finish(
            "NEEDS_TERMINAL",
            agent.EXIT_ACTION_NEEDED,
            "nothing changed; packages, services, firewall or SSH keys need the user's terminal",
            terminal_required=list(error.pending),
            next_actions=[{"who": "agent", "why": "open a terminal where the user types the sudo password", "command": handoff}],
        )
    except LocalEditConflict as error:
        return finish("CONFLICT", agent.EXIT_ACTION_NEEDED, str(error), conflicts=list(error.targets))
    except KeyboardInterrupt:
        return finish("CANCELLED", 130, "interrupted; apply the same plan again to resume")
    except WORKFLOW_ERRORS as error:
        return finish("FAIL", agent.EXIT_FAIL, str(error), next_actions=[{"who": "agent", "why": "report the error to the user; the same plan resumes after a fix", "command": ""}])
    next_actions: list[dict[str, object]] = []
    reasons = {item.reason for item in result.deferred}
    if "needs-login" in reasons or "waiting-for-login" in reasons:
        next_actions.append({"who": "agent", "why": "open a terminal where the user finishes the queued logins", "command": handoff})
    if "needs-session" in reasons:
        next_actions.append({"who": "user", "why": "log in to the Hyprland session, then the agent applies the same plan again", "command": bootstrap_command(workflow.value, "apply", "--plan", digest, "--json")})
    if result.skipped_features:
        next_actions.append({"who": "user", "why": "declined AUR builds stay skipped for this plan", "command": ""})
    ready = not result.deferred and not result.skipped_features
    return finish(
        "READY" if ready else "INCOMPLETE",
        agent.EXIT_READY if ready else agent.EXIT_ACTION_NEEDED,
        result=result,
        next_actions=next_actions,
    )



def busy(workflow: WorkflowId, digest: str) -> tuple[dict[str, object], int]:
    """Another apply holds the lock; its saved status stays untouched."""
    return {
        "schema": agent.REPORT_SCHEMA,
        "command": "apply",
        "workflow": workflow.value,
        "plan_digest": digest,
        "status": "BUSY",
        "message": "another bootstrap apply is running; nothing changed",
        "next_actions": [{"who": "agent", "why": "wait for it, then plan again", "command": bootstrap_command(workflow.value, "status", "--wait", "900", "--json")}],
    }, agent.EXIT_ACTION_NEEDED


def status_command(workflow: WorkflowId, digest: str | None, wait: int) -> tuple[dict[str, object], int]:
    store = StateStore(Path.home())
    deadline = time.monotonic() + wait
    while True:
        record = store.read_result(workflow)
        if record is not None and digest and record.get("plan_digest") != digest:
            # A handoff saves HANDED_OFF for its plan before the terminal
            # starts, so nothing for this plan means nothing to wait for.
            record = None
        if record is not None and record.get("status") == "RUNNING" and not _process_alive(record.get("pid")):
            record = {**record, "status": "INTERRUPTED", "exit_code": agent.EXIT_ACTION_NEEDED, "message": "the apply stopped before it finished; apply the same plan again to resume"}
        if record is not None and record.get("status") == "HANDED_OFF" and _handoff_lost(record):
            record = {**record, "status": "HANDOFF_LOST", "exit_code": agent.EXIT_ACTION_NEEDED, "message": "the terminal never started the apply; ask the user to run the command in a terminal"}
        waiting = record is not None and record.get("status") in ACTIVE_STATUSES
        if not waiting or time.monotonic() >= deadline:
            break
        time.sleep(2)
    if record is None:
        return {"schema": agent.REPORT_SCHEMA, "command": "status", "workflow": workflow.value, "plan_digest": digest, "status": "NO_RESULT"}, agent.EXIT_ACTION_NEEDED
    code = record.get("exit_code")
    if record.get("status") in ACTIVE_STATUSES or not isinstance(code, int):
        code = agent.EXIT_ACTION_NEEDED
    return {**record, "command": "status"}, code


HANDOFF_START_SECONDS = 120


def _handoff_lost(record: dict[str, object]) -> bool:
    """The terminal run saves RUNNING at its start, before any prompt."""
    started = record.get("handed_off_epoch")
    return isinstance(started, (int, float)) and time.time() - started > HANDOFF_START_SECONDS


def _process_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def restore_command(workflow: WorkflowId, digest: str, discard_local: bool) -> tuple[dict[str, object], int]:
    """Put back the files one applied plan replaced and remove those it created."""
    facts = detect_platform(LocalHostProbe(Path.home()))
    plan = load_workflow_plan(workflow, digest)
    if plan.header.target_home != facts.target_home:
        raise PlanHostMismatch("plan target home differs from the current home")
    store = StateStore(Path(facts.target_home))
    try:
        result = restore_files(Path(facts.target_home), plan.actions, digest, workflow.value, discard_local=discard_local)
    except ApplyLocked:
        return {**busy(workflow, digest)[0], "command": "restore"}, agent.EXIT_ACTION_NEEDED
    except LocalEditConflict as error:
        report = agent.result_record(workflow.value, digest, "CONFLICT", agent.EXIT_ACTION_NEEDED, message=str(error), operation="restore", conflicts=list(error.targets))
        return {**report, "command": "restore"}, agent.EXIT_ACTION_NEEDED
    deferred: list[dict[str, str]] = []
    # Reload on every run, not only when files changed now: a restore resumed
    # after an interruption or a failed reload must still finish both.
    targets = [str(item.data.get("target", "")) for item in plan.actions]
    if any(target.startswith(".config/systemd/user/") for target in targets):
        run(("/usr/bin/systemctl", "--user", "daemon-reload"))
    if workflow is WorkflowId.DESKTOP and not reload_hyprland():
        deferred.append({"kind": "hyprland-reload", "feature": "core-desktop", "reason": "needs-session", "detail": ""})
    status, code = ("INCOMPLETE", agent.EXIT_ACTION_NEEDED) if deferred else ("RESTORED", agent.EXIT_READY)
    record = agent.result_record(
        workflow.value,
        digest,
        status,
        code,
        operation="restore",
        restored=list(result.restored),
        removed=list(result.removed),
        deferred=deferred,
    )
    store.write_result_locked(workflow, record)
    return {**record, "command": "restore"}, code


def audit_command(workflow: WorkflowId, digest: str | None) -> tuple[dict[str, object], int]:
    facts = detect_platform(LocalHostProbe(Path.home()))
    repository = compile_repository(ROOT, facts.platform)
    plan = load_workflow_plan(workflow, digest) if digest else load_latest_workflow_plan(workflow)
    if plan.header.repository_digest != repository.source_digest:
        raise StalePlan("the repository changed after planning; plan again and audit that plan")
    findings = audit_install(execution_workspace(repository, workflow), execution_plan(repository, plan), facts)
    drift = any(item.status == "FAIL" for item in findings)
    return {
        "schema": agent.REPORT_SCHEMA,
        "command": "audit",
        "workflow": workflow.value,
        "plan_digest": plan.digest,
        "status": "DRIFT" if drift else "CLEAN",
        "findings": [
            {"status": item.status, "kind": item.kind, "feature": item.feature, "message": item.message}
            for item in findings
        ],
    }, agent.EXIT_DRIFT if drift else agent.EXIT_READY


def print_change_summary(report: dict[str, object]) -> None:
    changes = report["changes"]
    assert isinstance(changes, dict)
    files = changes["files"]
    assert isinstance(files, dict)
    print(f"Files: {len(files['create'])} new, {len(files['update'])} updated, {files['unchanged']} unchanged")
    for kind in ("local-edit", "unmanaged"):
        for target in files[kind]:
            print(f"  {kind}: {target}")
    for item in changes["terminal_required"]:
        print(f"  needs a terminal: {item}")
    for item in changes["logins_pending"]:
        print(f"  login queued: {item}")


def print_report(report: dict[str, object]) -> None:
    print(f"{str(report.get('workflow', '')).title()}: {report.get('status')}")
    if report.get("message"):
        print(report["message"])
    for name in ("conflicts", "terminal_required", "restored", "removed"):
        for item in report.get(name, ()) or ():
            print(f"  {name}: {item}")
    for item in report.get("deferred", ()) or ():
        print(f"  deferred: {item['feature']} ({item['reason']})")
    for item in report.get("findings", ()) or ():
        print(f"{item['status']:4} {item['feature']}: {item['message']}")
    for item in report.get("next_actions", ()) or ():
        print(f"  next ({item['who']}): {item['why']}" + (f": {item['command']}" if item.get("command") else ""))


if __name__ == "__main__":
    raise SystemExit(main())
