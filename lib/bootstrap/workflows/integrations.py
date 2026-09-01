from __future__ import annotations

from ..catalog import CatalogError
from ..domain import ActionKind, IntegrationsRequest, WorkflowId
from ..planner import HostState, PlanInputs, plan_install, resolve_features
from ..planning.model import IntegrationsPlan, PackagesEvidence, PlanHeader
from ..platform import PlatformFacts
from ..repository.model import RepositoryModel


ALLOWED_INTEGRATION_ACTIONS = frozenset(
    {
        ActionKind.USER_FILE,
        ActionKind.GENERATED_FILE,
        ActionKind.MANAGED_FRAGMENT,
        ActionKind.PINNED_GIT_ASSET,
        ActionKind.USER_DAEMON_RELOAD,
        ActionKind.USER_UNIT,
        ActionKind.SYSTEM_UNIT,
        ActionKind.MANUAL_AUTHENTICATION,
        ActionKind.AUTHORIZED_SSH_KEYS,
        ActionKind.REVOKED_SSH_KEY,
        ActionKind.FIREWALL_RULE,
        ActionKind.VERIFICATION_PROBE,
    }
)


def plan_integrations(
    root,
    repository: RepositoryModel,
    facts: PlatformFacts,
    state: HostState,
    request: IntegrationsRequest,
    evidence: PackagesEvidence,
    *,
    github_keys: dict[str, tuple[str, ...]] | None = None,
) -> IntegrationsPlan:
    workspace = repository.workflow(WorkflowId.INTEGRATIONS).workspace
    requested = set(request.integrations) | set(request.agents)
    selected = resolve_features(workspace, requested)
    legacy = plan_install(
        root,
        workspace,
        facts,
        state,
        selected,
        PlanInputs("generic", "claude", github_keys=github_keys),
    )
    actions = tuple(_selected_skill_action(item, request) for item in legacy.actions)
    actions = tuple(item for item in actions if item is not None)
    invalid = {item.kind for item in actions} - ALLOWED_INTEGRATION_ACTIONS
    if invalid:
        raise CatalogError(f"integrations plan contains forbidden actions: {', '.join(sorted(item.value for item in invalid))}")
    header = PlanHeader(3, WorkflowId.INTEGRATIONS, facts.fingerprint(), repository.source_digest, facts.target_home)
    return IntegrationsPlan.create(header, request, evidence, actions, tuple(sorted(legacy.unavailable)))


def _selected_skill_action(item, request: IntegrationsRequest):
    if item.feature != "user-skills" or item.kind is not ActionKind.USER_FILE:
        return item
    target = str(item.data["target"])
    canonical = ".local/share/arch-hypr-bootstrap/agent-skills/"
    harness_roots = {
        "agents": ".agents/skills/",
        "claude": ".claude/skills/",
        "codex": ".codex/skills/",
        "opencode": ".config/opencode/skills/",
        "cursor": ".cursor/skills/",
    }
    if target.startswith(canonical):
        skill = target[len(canonical):].split("/", 1)[0]
        return item if skill in request.skills else None
    for harness, prefix in harness_roots.items():
        if target.startswith(prefix):
            skill = target[len(prefix):].split("/", 1)[0]
            return item if harness in request.harnesses and skill in request.skills else None
    return item
