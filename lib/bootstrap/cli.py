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
    strings,
    UNIT_DIRECTORY,
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
        if args.json:
            return json_command(args)
    try:
        if args.command == "setup":
            return setup_command()
        workflow = WorkflowId(args.command)
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
    if (args.add or args.remove) and not (args.operation == "plan" and args.json):
        return "--add and --remove belong to plan --json"
    if args.plan and args.operation == "plan":
        return "plan creates a digest; --plan names an existing one"
    if args.operation in {"apply", "restore"} and (args.json or args.operation == "restore") and not args.plan:
        return f"{args.operation} needs --plan DIGEST here"
    if args.in_terminal and not (args.operation == "apply" and args.plan):
        return "--in-terminal needs apply --plan DIGEST"
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


def plan_for_selection(workflow, repository, facts, state, store, selected, *, interactive: bool, known=None) -> WorkflowPlan:
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
    if known is None:
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


STATE_PLANS = ".local/state/arch-hypr-bootstrap/plans"


def save_workflow_plan(plan: WorkflowPlan) -> Path:
    target = f"{STATE_PLANS}/{plan.header.workflow.value}/{plan.digest}.json"
    path = Path(plan.header.target_home) / target
    content = json.dumps(plan.to_dict(), indent=2, sort_keys=True) + "\n"
    with HomeFiles(Path(plan.header.target_home)) as home:
        existing = home.read_text(target)
        if existing is not None and existing != content:
            raise PlanSchemaError("digest-addressed plan content differs from existing plan")
        if existing is None:
            home.ensure_directory(f"{STATE_PLANS}/{plan.header.workflow.value}", 0o700)
            home.write_private_atomic(target, content.encode())
    return path


def load_latest_workflow_plan(workflow: WorkflowId) -> WorkflowPlan:
    directory = Path.home() / STATE_PLANS / workflow.value
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
ACTIVE_STATUSES = {"RUNNING", "HANDED_OFF"}


def bootstrap_command(*arguments: str) -> str:
    return shlex.join((str(ROOT / "bootstrap"), *arguments))


def step(who: str, why: str, command: str = "") -> dict[str, str]:
    return {"who": who, "why": why, "command": command}


def json_command(args: argparse.Namespace) -> int:
    workflow = WorkflowId(args.command)
    with agent.json_stdout() as descriptor:
        try:
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
        return "STALE", agent.EXIT_ACTION_NEEDED, [step("agent", "plan again")]
    if isinstance(error, ApplyLocked):
        return "BUSY", agent.EXIT_ACTION_NEEDED, [step("agent", "another apply is running; wait with status --wait, then retry")]
    if message.startswith("NEEDS PACKAGES: "):
        missing = message.removeprefix("NEEDS PACKAGES: ").replace(",", " ").split()
        arguments = [argument for item in missing for argument in ("--add", item)]
        return "NEEDS_PACKAGES", agent.EXIT_ACTION_NEEDED, [step("agent", "install the prerequisites first", bootstrap_command("packages", "plan", "--json", *arguments))]
    if message.startswith("package databases are stale or missing"):
        # The bootstrap never refreshes or updates the distribution itself.
        return "NEEDS_SYSTEM_UPDATE", agent.EXIT_ACTION_NEEDED, [step("user", "run omarchy update, then the agent plans again", "omarchy update")]
    if message.startswith("NEEDS SESSION: "):
        return "NEEDS_SESSION", agent.EXIT_ACTION_NEEDED, [step("user", "log in to the Hyprland session, then the agent plans again")]
    return "FAIL", agent.EXIT_FAIL, []


def agent_command(args: argparse.Namespace, workflow: WorkflowId) -> tuple[dict[str, object], int]:
    if args.operation == "plan":
        return agent_plan(workflow, frozenset(args.add), frozenset(args.remove)), agent.EXIT_READY
    if args.operation == "status":
        return status_command(workflow, args.plan, args.wait)
    if args.operation == "restore":
        return restore_command(workflow, args.plan, args.discard_local)
    if args.operation == "audit":
        return audit_command(workflow, args.plan)
    return approved_apply(
        workflow,
        args.plan,
        discard_local=args.discard_local,
        in_terminal=args.in_terminal,
        prompts=not args.json and sys.stdin.isatty(),
    )


def agent_plan(workflow: WorkflowId, add: frozenset[str], remove: frozenset[str]) -> dict[str, object]:
    """Plan without the selector: the saved selection, or the defaults, plus add/remove."""
    facts = detect_platform(LocalHostProbe(Path.home()))
    repository = compile_repository(ROOT, facts.platform)
    catalog = visible_catalog(repository, workflow)
    store = StateStore(Path(facts.target_home))
    previous = store.read_selection(workflow)
    base = previous.selected if previous else frozenset(item for item, (_, default) in catalog.items() if default)
    # IDs the repository dropped since the selection was saved fall away.
    workspace = execution_workspace(repository, workflow)
    existing = repository.applications.keys() if workflow is WorkflowId.PACKAGES else workspace.public_catalog.keys()
    selected = ((base & existing) | add) - remove
    new_items = sorted(catalog.keys() - previous.known) if previous and previous.known is not None else []
    # New items stay reported until someone changes the selection.
    keep_known = previous.known if previous is not None and not (add or remove) else None
    plan = plan_for_selection(
        workflow, repository, facts, detect_host_state(workspace), store, selected, interactive=False, known=keep_known
    )
    save_workflow_plan(plan)
    with HomeFiles(Path(facts.target_home)) as home:
        changes = agent.describe_changes(plan, home, read_managed(home, workflow.value))
    checkout = agent.checkout_state(ROOT)
    apply_command = bootstrap_command(workflow.value, "apply", "--plan", plan.digest, "--json")
    next_actions = []
    problem = agent.checkout_problem(checkout)
    if problem:
        next_actions.append(step("user", f"apply refuses this checkout: {problem}"))
    files = changes["files"]
    if files["local-edit"] or files["unmanaged"]:
        next_actions.append(step("user", "approve replacing the local-edit and unmanaged files (each is backed up)", f"{apply_command} --discard-local"))
    next_actions.append(step("agent", "apply the reviewed plan", apply_command))
    return {
        "schema": agent.REPORT_SCHEMA,
        "command": "plan",
        "workflow": workflow.value,
        "status": "PLANNED",
        "plan_digest": plan.digest,
        "checkout": checkout,
        "selection": {
            "selected": sorted(selected),
            "new_items": [{"id": item, "label": catalog[item][0], "default": catalog[item][1]} for item in new_items],
        },
        "changes": changes,
        "next_actions": next_actions,
    }


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
    """Apply the plan named by its digest; naming it is the approval.

    Without a terminal it never prompts: packages, system services, the
    firewall, and incoming SSH keys stop it with NEEDS_TERMINAL before any
    change, and logins stay queued. Every outcome is saved for `status`.
    """
    facts = detect_platform(LocalHostProbe(Path.home()))
    repository = compile_repository(ROOT, facts.platform)
    plan = load_workflow_plan(workflow, digest)
    if plan.header.repository_digest != repository.source_digest:
        raise StalePlan("the repository changed after planning; plan again")
    store = StateStore(Path(facts.target_home))
    checkout = agent.checkout_state(ROOT)
    terminal = [str(ROOT / "bootstrap"), workflow.value, "apply", "--plan", digest, *(("--discard-local",) if discard_local else ())]
    handoff = shlex.join([*terminal, "--json", "--in-terminal"])

    def finish(status: str, code: int, message: str = "", **extra: object) -> tuple[dict[str, object], int]:
        record = agent.result_record(workflow.value, digest, status, code, message=message, checkout=checkout, **extra)
        store.write_result(workflow, record)
        return {**record, "command": "apply"}, code

    problem = agent.checkout_problem(checkout)
    if problem:
        return finish("BLOCKED", agent.EXIT_ACTION_NEEDED, problem, next_actions=[step("user", problem)])
    try:
        with HomeFiles(Path(plan.header.target_home)) as home:
            conflicts = () if discard_local else local_conflicts(home, plan.actions, read_managed(home, workflow.value))
            pending = terminal_pending(execution_plan(repository, plan), home)
        if conflicts:
            return finish(
                "CONFLICT",
                agent.EXIT_ACTION_NEEDED,
                "files changed outside the bootstrap; ask the user before replacing them",
                conflicts=list(conflicts),
                next_actions=[step("user", "approve replacing these files (each is backed up)", bootstrap_command(workflow.value, "apply", "--plan", digest, "--json", "--discard-local"))],
            )
        if in_terminal:
            session = session_environment()
            if session is None:
                return finish("NEEDS_TERMINAL", agent.EXIT_ACTION_NEEDED, "no Hyprland session to open a terminal on", next_actions=[step("user", "run this in a terminal", shlex.join(terminal))])
            # Saved before the launch; the terminal run replaces it with RUNNING.
            report = finish(
                "HANDED_OFF",
                agent.EXIT_ACTION_NEEDED,
                "a terminal opened on the session; the user types the sudo password there",
                terminal_required=list(pending),
                next_actions=[step("agent", "wait for the terminal apply", bootstrap_command(workflow.value, "status", "--plan", digest, "--wait", "900", "--json"))],
            )
            agent.launch_terminal(terminal, session)
            return report
        # Saved before the password prompt: a terminal closed there reads as INTERRUPTED.
        store.write_result(workflow, agent.result_record(workflow.value, digest, "RUNNING", agent.EXIT_ACTION_NEEDED, checkout=checkout, pid=os.getpid()))
        keys = [key for item in plan.actions if item.kind is ActionKind.AUTHORIZED_SSH_KEYS for key in strings(item.data["fingerprints"])]
        if prompts and any(item.startswith(f"{ActionKind.AUTHORIZED_SSH_KEYS.value}:") for item in pending):
            # Incoming SSH access is granted only on a keypress in the user's terminal.
            if not confirm(f"Trust these SSH keys for incoming access? {', '.join(keys)}"):
                return finish("DECLINED", agent.EXIT_DRIFT, "SSH key trust was declined")
        result = apply_workflow_plan(
            ROOT, repository, plan, facts, system_changes=True, interactive=prompts, reviewed=True, discard_local=discard_local
        )
    except NeedsTerminal as error:
        return finish(
            "NEEDS_TERMINAL",
            agent.EXIT_ACTION_NEEDED,
            "nothing changed; packages, services, firewall or SSH keys need the user's terminal",
            terminal_required=list(error.pending),
            next_actions=[step("agent", "open a terminal where the user types the sudo password", handoff)],
        )
    except LocalEditConflict as error:
        return finish("CONFLICT", agent.EXIT_ACTION_NEEDED, str(error), conflicts=list(error.targets))
    except ApplyLocked:
        raise
    except KeyboardInterrupt:
        return finish("CANCELLED", 130, "interrupted; apply the same plan again to resume")
    except WORKFLOW_ERRORS as error:
        return finish("FAIL", agent.EXIT_FAIL, str(error), next_actions=[step("agent", "report the error to the user; the same plan resumes after a fix")])
    reasons = {item.reason for item in result.deferred}
    next_actions = []
    if reasons & {"needs-login", "waiting-for-login"}:
        next_actions.append(step("agent", "open a terminal where the user finishes the queued logins", handoff))
    if "needs-session" in reasons:
        next_actions.append(step("user", "log in to the Hyprland session, then the agent applies the same plan again"))
    ready = not result.deferred and not result.skipped_features
    return finish(
        "READY" if ready else "INCOMPLETE",
        agent.EXIT_READY if ready else agent.EXIT_ACTION_NEEDED,
        result=result,
        next_actions=next_actions,
    )


def status_command(workflow: WorkflowId, digest: str | None, wait: int) -> tuple[dict[str, object], int]:
    store = StateStore(Path.home())
    deadline = time.monotonic() + wait
    while True:
        record = store.read_result(workflow)
        if record is not None and digest and record.get("plan_digest") != digest:
            record = None
        if record is not None and record.get("status") == "RUNNING" and not _process_alive(record.get("pid")):
            record = {**record, "status": "INTERRUPTED", "exit_code": agent.EXIT_ACTION_NEEDED, "message": "the apply stopped before it finished; apply the same plan again to resume"}
        if record is None or record.get("status") not in ACTIVE_STATUSES or time.monotonic() >= deadline:
            break
        time.sleep(2)
    if record is None:
        return {"schema": agent.REPORT_SCHEMA, "command": "status", "workflow": workflow.value, "plan_digest": digest, "status": "NO_RESULT"}, agent.EXIT_ACTION_NEEDED
    code = record.get("exit_code")
    if record.get("status") in ACTIVE_STATUSES or not isinstance(code, int):
        code = agent.EXIT_ACTION_NEEDED
    return {**record, "command": "status"}, code


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
    try:
        result = restore_files(Path(facts.target_home), plan.actions, digest, workflow.value, discard_local=discard_local)
    except LocalEditConflict as error:
        report = agent.result_record(workflow.value, digest, "CONFLICT", agent.EXIT_ACTION_NEEDED, message=str(error), conflicts=list(error.targets))
        return {**report, "command": "restore"}, agent.EXIT_ACTION_NEEDED
    if any(str(item.data.get("target", "")).startswith(".config/systemd/user/") for item in plan.actions):
        run(("/usr/bin/systemctl", "--user", "daemon-reload"))
    # A running unit keeps its definition until it restarts.
    units = {str(item.data["name"]) for item in plan.actions if item.kind is ActionKind.USER_UNIT}
    for unit in sorted(units & {target.removeprefix(UNIT_DIRECTORY) for target in result.restored}):
        run(("/usr/bin/systemctl", "--user", "try-restart", unit))
    # Reloaded on every run, so a restore repeated after a failed reload finishes it.
    deferred = []
    if workflow is WorkflowId.DESKTOP and not reload_hyprland():
        deferred.append({"kind": "hyprland-reload", "feature": "core-desktop", "reason": "needs-session", "detail": ""})
    status, code = ("INCOMPLETE", agent.EXIT_ACTION_NEEDED) if deferred else ("RESTORED", agent.EXIT_READY)
    record = agent.result_record(
        workflow.value, digest, status, code, operation="restore", restored=list(result.restored), removed=list(result.removed), deferred=deferred
    )
    StateStore(Path(facts.target_home)).write_result(workflow, record)
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
