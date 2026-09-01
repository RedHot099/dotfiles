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
    invalid = {item.kind for item in legacy.actions} - ALLOWED_INTEGRATION_ACTIONS
    if invalid:
        raise CatalogError(f"integrations plan contains forbidden actions: {', '.join(sorted(item.value for item in invalid))}")
    header = PlanHeader(3, WorkflowId.INTEGRATIONS, facts.fingerprint(), repository.source_digest, facts.target_home)
    return IntegrationsPlan.create(header, request, evidence, legacy.actions, tuple(sorted(legacy.unavailable)))
