from __future__ import annotations

from ..catalog import CatalogError
from ..domain import ActionKind, DesktopRequest, WorkflowId
from ..planner import HostState, PlanInputs, plan_install, resolve_features
from ..planning.model import DesktopPlan, PackagesEvidence, PlanHeader
from ..platform import PlatformFacts
from ..repository.model import RepositoryModel


ALLOWED_DESKTOP_ACTIONS = frozenset(
    {
        ActionKind.USER_FILE,
        ActionKind.GENERATED_FILE,
        ActionKind.PINNED_GIT_ASSET,
        ActionKind.OMARCHY_THEME,
        ActionKind.USER_DAEMON_RELOAD,
        ActionKind.HYPRLAND_RELOAD,
    }
)


def plan_desktop(
    root,
    repository: RepositoryModel,
    facts: PlatformFacts,
    state: HostState,
    request: DesktopRequest,
    evidence: PackagesEvidence,
    *,
    monitor_content: str | None = None,
) -> DesktopPlan:
    workspace = repository.workflow(WorkflowId.DESKTOP).workspace
    if "session-autostart" in request.features:
        required = {"google-chrome", "chromium", "caprine", "t3-code"}
        missing = required - set(evidence.selected)
        if missing:
            raise CatalogError("NEEDS PACKAGES: " + ", ".join(sorted(missing)))
    selected = resolve_features(workspace, set(request.features))
    legacy = plan_install(
        root,
        workspace,
        facts,
        state,
        selected,
        PlanInputs(request.hardware, "claude", monitor_content),
    )
    actions = (*legacy.actions, _reload_action())
    invalid = {item.kind for item in actions} - ALLOWED_DESKTOP_ACTIONS
    if invalid:
        raise CatalogError(f"desktop plan contains forbidden actions: {', '.join(sorted(item.value for item in invalid))}")
    header = PlanHeader(3, WorkflowId.DESKTOP, facts.fingerprint(), repository.source_digest, facts.target_home)
    return DesktopPlan.create(header, request, evidence, actions, tuple(sorted(legacy.unavailable)))


def _reload_action():
    from ..planner import action

    return action(ActionKind.HYPRLAND_RELOAD, "core-desktop", {})
