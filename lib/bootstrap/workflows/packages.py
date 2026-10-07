from __future__ import annotations

from ..catalog import CatalogError, PackageBinding
from ..domain import ActionKind, PackagesRequest, PlannedAction, WorkflowId
from ..packages import LocalPackageProvider, PlanningPackageProvider, repository_names
from ..planner import HostState, action, action_order, repository_action
from ..planning.model import PackagesPlan, PlanHeader
from ..platform import PlatformFacts
from ..repository.model import RepositoryModel


def plan_packages(
    repository: RepositoryModel,
    facts: PlatformFacts,
    state: HostState,
    request: PackagesRequest,
    package_provider: PlanningPackageProvider | None = None,
) -> PackagesPlan:
    if repository.platform is not facts.platform:
        raise CatalogError("repository platform differs from detected host")
    unknown = request.applications - repository.applications.keys()
    if unknown:
        raise CatalogError(f"unknown applications: {', '.join(sorted(unknown))}")
    provider = package_provider or LocalPackageProvider(facts.repositories)
    actions: list[PlannedAction] = []
    selected = tuple(repository.applications[item] for item in sorted(request.applications))
    requirements = {
        requirement
        for application in selected
        for requirement in (
            *application.requirements,
            *(
                item
                for vendor in sorted(state.gpu_vendors)
                for item in application.gpu_requirements.get(vendor, ())
            ),
        )
    }
    bindings = tuple(repository.package_bindings[item] for item in sorted(requirements))
    repository_bindings = tuple(
        binding
        for binding in bindings
        if binding.provider == "repository" and binding.package not in state.packages
    )
    if repository_bindings:
        actions.append(
            repository_action(
                "packages",
                repository_bindings,
                provider.resolve_repository(repository_bindings),
            )
        )
    for binding in (item for item in bindings if item.provider == "aur"):
        recipe = provider.inspect_aur(binding)
        if all(
            package in state.foreign_packages
            and state.package_versions.get(package) == recipe.version
            for package in recipe.package_names
        ):
            continue
        missing = tuple(
            sorted(
                set(provider.missing_dependencies(recipe.dependencies))
                | set(provider.missing_build_requirements())
            )
        )
        if missing:
            configured = repository_names(facts.repositories)
            dependency_bindings = tuple(
                PackageBinding(item, "repository", item, configured, None, None)
                for item in missing
            )
            actions.append(
                repository_action(
                    binding.requirement,
                    dependency_bindings,
                    provider.resolve_dependency_packages(missing),
                )
            )
        actions.append(
            action(
                ActionKind.AUR_BUILD,
                binding.requirement,
                {
                    "packages": recipe.package_names,
                    "package_base": recipe.package_base,
                    "version": recipe.version,
                    "url": binding.url,
                    "commit": binding.revision,
                    "files": recipe.files_as_dicts(),
                    "dependencies": recipe.dependencies,
                },
            )
        )
    for application in selected:
        if application.tools:
            actions.append(
                action(
                    ActionKind.PINNED_TOOL,
                    application.id,
                    {"tools": application.tools, "commands": application.commands},
                )
            )
    actions.sort(key=action_order)
    header = PlanHeader(
        schema=3,
        workflow=WorkflowId.PACKAGES,
        platform=facts.fingerprint(),
        repository_digest=repository.source_digest,
        target_home=facts.target_home,
    )
    return PackagesPlan.create(header, request, tuple(actions))
