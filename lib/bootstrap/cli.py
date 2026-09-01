from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from .catalog import CatalogError, Workspace
from .domain import (
    DesktopRequest,
    IntegrationsRequest,
    PackagesRequest,
    PlanHostMismatch,
    PlanSchemaError,
    WorkflowId,
)
from .execution import apply_workflow_plan, execution_workspace
from .host import LocalHostProbe
from .planner import HostState
from .planning.model import PackagesEvidence, WorkflowPlan, plan_from_dict
from .platform import PlatformDetectionError, detect_platform
from .repository import compile_repository
from .state import SelectionRecord, StateStore
from .tui.model import ChoiceRow, SelectorState
from .tui.screens import select
from .workflows import plan_desktop, plan_integrations, plan_packages


ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    try:
        if args.command == "setup":
            return setup_command()
        return workflow_command(WorkflowId(args.command), args.operation)
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
        if plan.header.platform != facts.fingerprint():
            raise PlanHostMismatch("plan does not match current host capabilities")
        print(f"{workflow.value.title()}: READY (plan {plan.digest[:12]} matches this host)")
        return 0
    if not confirm(f"Apply reviewed {workflow.value} plan {plan.digest[:12]}?"):
        print("Aborted.")
        return 1
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
    return int(status != "READY")


def setup_command() -> int:
    statuses: list[tuple[str, str]] = []
    for workflow in WorkflowId:
        print(f"\n{workflow.value.title()}")
        if not confirm(f"Configure {workflow.value} now?"):
            statuses.append((workflow.value, "SKIPPED"))
            continue
        code = workflow_command(workflow, "plan")
        if code == 0:
            code = workflow_command(workflow, "apply")
        statuses.append((workflow.value, "READY" if code == 0 else "FAIL"))
    print("\nSummary")
    for name, status in statuses:
        print(f"{name.title():14} {status}")
    return int(any(status == "FAIL" for _, status in statuses))


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
                bool(item.commands) and all(command in state.commands for command in item.commands),
                item.hardware_hint,
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
            plan = plan_desktop(ROOT, repository, facts, state, DesktopRequest(selected, "generic"), evidence)
        else:
            agents = frozenset(item for item in selected if item.startswith("agent."))
            plan = plan_integrations(
                ROOT,
                repository,
                facts,
                state,
                IntegrationsRequest(
                    selected - agents,
                    agents,
                    select_skills(),
                    select_harnesses(),
                ),
                evidence,
            )
    store.write_selection(SelectionRecord(workflow, selected, repository.source_digest))
    return plan


def select_skills() -> frozenset[str]:
    directory = ROOT / "integrations/common/skills/private"
    rows = tuple(ChoiceRow(path.name, "Skills", path.name, True) for path in sorted(directory.iterdir()) if path.is_dir())
    return select("Select skills for every chosen harness", SelectorState(rows)).selected_ids()


def select_harnesses() -> frozenset[str]:
    data = tomllib.loads((ROOT / "integrations/common/harnesses.toml").read_text())
    rows = tuple(
        ChoiceRow(item["id"], "Harnesses", item["label"], bool(item.get("default", False)))
        for item in data["harnesses"]
    )
    return select("Select agent harnesses", SelectorState(rows)).selected_ids()


def save_workflow_plan(plan: WorkflowPlan) -> Path:
    directory = Path(plan.header.target_home) / ".local/state/arch-hypr-bootstrap/plans" / plan.header.workflow.value
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"{plan.digest}.json"
    content = json.dumps(plan.to_dict(), indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text() != content:
            raise PlanSchemaError("digest-addressed plan content differs from existing plan")
        return path
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
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
    )


def query_foreign_packages() -> frozenset[str]:
    result = subprocess.run(("pacman", "-Qmq"), check=False, text=True, stdout=subprocess.PIPE)
    if result.returncode not in (0, 1):
        result.check_returncode()
    return frozenset(result.stdout.splitlines())


def confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        raise CatalogError("interactive mode requires a terminal")
    return input(f"{prompt} [y/N] ").strip().lower() in {"y", "yes"}


if __name__ == "__main__":
    raise SystemExit(main())
