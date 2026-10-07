from __future__ import annotations

from dataclasses import replace

from .catalog import Workspace
from .domain import ExecutionPlan, WorkflowId
from .executor import ApplyResult, apply_install
from .planning.model import WorkflowPlan
from .platform import PlatformFacts
from .repository.model import RepositoryModel


def apply_workflow_plan(
    root,
    repository: RepositoryModel,
    plan: WorkflowPlan,
    facts: PlatformFacts,
    *,
    system_changes: bool,
    interactive: bool,
) -> ApplyResult:
    workspace = execution_workspace(repository, plan.header.workflow)
    legacy = execution_plan(repository, plan)
    return apply_install(
        root,
        workspace,
        legacy,
        facts,
        system_changes=system_changes,
        interactive=interactive,
    )


def execution_plan(repository: RepositoryModel, plan: WorkflowPlan) -> ExecutionPlan:
    # Actions name the feature that owns them: a package transaction, an AUR
    # requirement, or a feature pulled in through `requires`, not only the
    # requested IDs. Every one must be selected and have a dependency entry.
    selected = tuple(sorted(set(_selected(plan)) | {item.feature for item in plan.actions}))
    catalog = execution_workspace(repository, plan.header.workflow).public_catalog
    dependencies = {
        feature: tuple(
            required
            for required in (catalog[feature].requires if feature in catalog else ())
            if required in selected
        )
        for feature in selected
    }
    return ExecutionPlan.create(
        platform=plan.header.platform,
        workspace_digest=repository.source_digest,
        target_home=plan.header.target_home,
        selected=selected,
        dependencies=dependencies,
        unavailable={item: "unavailable on this platform" for item in getattr(plan, "unavailable", ())},
        actions=plan.actions,
    )


def execution_workspace(repository: RepositoryModel, workflow: WorkflowId) -> Workspace:
    workspace = repository.workflow(workflow).workspace
    if workspace is None:
        workspace = repository.workflow(WorkflowId.DESKTOP).workspace
    assert workspace is not None
    return replace(
        workspace,
        package_bindings=repository.package_bindings,
        source_digest=repository.source_digest,
    )


def _selected(plan: WorkflowPlan) -> tuple[str, ...]:
    request = plan.request
    if plan.header.workflow is WorkflowId.PACKAGES:
        return tuple(sorted(request.applications))
    if plan.header.workflow is WorkflowId.DESKTOP:
        return tuple(sorted(request.features))
    return tuple(sorted(request.integrations | request.agents))
