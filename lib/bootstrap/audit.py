from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .catalog import CatalogError, Workspace
from .domain import ActionKind, ExecutionPlan, PlannedAction, assert_plan_matches_host
from .executor import (
    action_satisfied,
    aur_installed_exact,
    command_environment,
    optional_string,
    run_probe,
    strings,
    tool_installed,
)
from .packages import installed_versions, transaction_from_action
from .files import FileBoundaryError, HomeFiles
from .platform import PlatformFacts


@dataclass(frozen=True)
class AuditFinding:
    status: str
    kind: str
    feature: str
    message: str


def audit_install(
    workspace: Workspace,
    plan: ExecutionPlan,
    facts: PlatformFacts,
) -> tuple[AuditFinding, ...]:
    assert_plan_matches_host(plan, facts)
    if plan.workspace_digest != workspace.source_digest:
        raise CatalogError("workspace changed after planning; regenerate the plan")
    target_home = Path(plan.target_home)
    isolated = target_home.resolve() != Path.home().resolve()
    if not target_home.is_dir():
        return (AuditFinding("FAIL", "home", "workspace", "target home does not exist"),)
    findings: list[AuditFinding] = []
    for feature, reason in plan.unavailable.items():
        findings.append(AuditFinding("WARN", "unavailable", feature, reason))
    try:
        with HomeFiles(target_home, create=False) as home:
            for item in plan.actions:
                findings.append(audit_action(item, home, isolated))
    except FileBoundaryError as error:
        return (AuditFinding("FAIL", "home", "workspace", str(error)),)
    return tuple(findings)


def audit_action(item: PlannedAction, home: HomeFiles, isolated: bool) -> AuditFinding:
    kind = item.kind.value
    if item.kind in {ActionKind.USER_FILE, ActionKind.GENERATED_FILE}:
        symlink = optional_string(item.data.get("symlink"))
        matches = home.matches(
            str(item.data["target"]),
            str(item.data["sha256"]),
            int(item.data["mode"]),
            symlink,
        )
        return finding(matches, kind, item, f"{item.data['target']}: {'matches' if matches else 'missing, changed, or wrong mode'}")
    if item.kind is ActionKind.MANAGED_FRAGMENT:
        matches = home.matches(
            str(item.data["target"]),
            str(item.data["result_sha256"]),
            int(item.data["mode"]),
            None,
        )
        return finding(matches, kind, item, "managed fragment matches" if matches else "managed fragment or surrounding file changed")
    if item.kind is ActionKind.REPOSITORY_PACKAGES:
        expected = {entry.name: entry.version for entry in transaction_from_action(dict(item.data))}
        direct = strings(item.data["packages"])
        actual = installed_versions(direct)
        mismatched = tuple(
            package for package in direct if actual.get(package) != expected[package]
        )
        status = "WARN" if mismatched and isolated else "FAIL" if mismatched else "PASS"
        message = "planned package versions present" if not mismatched else "missing or changed packages: " + ", ".join(mismatched)
        return AuditFinding(status, kind, item.feature, message)
    if item.kind is ActionKind.AUR_BUILD:
        matches = aur_installed_exact(item)
        status = "WARN" if isolated and not matches else "PASS" if matches else "FAIL"
        return AuditFinding(status, kind, item.feature, "reviewed AUR version present" if matches else "reviewed AUR version missing")
    if item.kind is ActionKind.PINNED_TOOL:
        missing = tuple(name for name in strings(item.data["tools"]) if not tool_installed(name))
        status = "WARN" if missing and isolated else "FAIL" if missing else "PASS"
        return AuditFinding(status, kind, item.feature, "tools present" if not missing else "missing tools: " + ", ".join(missing))
    if item.kind is ActionKind.MANUAL_AUTHENTICATION:
        ready = run_probe(
            tuple(strings(item.data["probe"])),
            optional_string(item.data.get("probe_contains")),
            command_environment(str(home.path)),
        )
        return AuditFinding(
            "PASS" if ready else "WARN",
            kind,
            item.feature,
            "authentication ready" if ready else f"manual login required: {item.data['label']}",
        )
    if item.kind in {ActionKind.USER_DAEMON_RELOAD, ActionKind.HYPRLAND_RELOAD}:
        return AuditFinding("PASS", kind, item.feature, "daemon reload is an apply transition")
    satisfied = action_satisfied(item, home, command_environment(str(home.path)))
    status = "WARN" if isolated and not satisfied else "PASS" if satisfied else "FAIL"
    return AuditFinding(status, kind, item.feature, "matches" if satisfied else "not converged")


def finding(matches: bool, kind: str, item: PlannedAction, message: str) -> AuditFinding:
    return AuditFinding("PASS" if matches else "FAIL", kind, item.feature, message)
