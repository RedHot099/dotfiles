from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import field
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .catalog import CatalogError, PackageBinding, Workspace
from .domain import ActionKind, ExecutionPlan, PlannedAction
from .platform import PlatformFacts
from .packages import (
    LocalPackageProvider,
    PlanningPackageProvider,
    RepositoryPackage,
    repository_names,
)


@dataclass(frozen=True)
class HostState:
    packages: frozenset[str]
    commands: frozenset[str]
    package_versions: Mapping[str, str] = field(default_factory=dict)
    foreign_packages: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PlanInputs:
    hardware: str
    default_agent: str
    monitor_content: str | None = None
    github_keys: Mapping[str, tuple[str, ...]] | None = None


def resolve_features(workspace: Workspace, requested: set[str]) -> tuple[str, ...]:
    unknown = requested - workspace.public_catalog.keys()
    if unknown:
        raise CatalogError(f"unknown features: {', '.join(sorted(unknown))}")
    resolved: set[str] = set()
    visiting: list[str] = []

    def visit(feature_id: str) -> None:
        if feature_id in resolved:
            return
        if feature_id in visiting:
            cycle = visiting[visiting.index(feature_id) :] + [feature_id]
            raise CatalogError("dependency cycle: " + " -> ".join(cycle))
        visiting.append(feature_id)
        for dependency in workspace.public_catalog[feature_id].requires:
            visit(dependency)
        visiting.pop()
        resolved.add(feature_id)

    for feature_id in sorted(requested):
        visit(feature_id)
    return tuple(sorted(resolved))


def plan_install(
    root: Path,
    workspace: Workspace,
    facts: PlatformFacts,
    state: HostState,
    requested: set[str],
    inputs: PlanInputs,
    package_provider: PlanningPackageProvider | None = None,
) -> ExecutionPlan:
    if workspace.platform != facts.platform:
        raise CatalogError("workspace platform differs from detected host")
    if inputs.default_agent not in {"claude", "codex", "opencode"}:
        raise CatalogError(f"unsupported default agent: {inputs.default_agent}")
    selected = resolve_features(workspace, requested)
    for feature_id in selected:
        username = workspace.implementations[feature_id].github_ssh_user
        if username and not (inputs.github_keys or {}).get(username):
            raise CatalogError(f"reviewed GitHub SSH keys are required for {username}")
    actions: list[PlannedAction] = []
    unavailable: dict[str, str] = {}
    provider = package_provider or LocalPackageProvider(facts.platform, facts.repositories)
    for feature_id in selected:
        implementation = workspace.implementations[feature_id]
        if not implementation.available:
            assert implementation.unavailable_reason is not None
            unavailable[feature_id] = implementation.unavailable_reason
            continue
        bindings = tuple(
            workspace.package_bindings[requirement]
            for requirement in implementation.package_requirements
        )
        repository_bindings = tuple(
            binding
            for binding in bindings
            if binding.provider == "repository" and binding.package not in state.packages
        )
        if repository_bindings:
            transaction = provider.resolve_repository(repository_bindings)
            actions.append(
                repository_action(feature_id, repository_bindings, transaction)
            )
        for binding in (item for item in bindings if item.provider == "aur"):
            recipe = provider.inspect_aur(binding)
            if all(
                package in state.foreign_packages
                and state.package_versions.get(package) == recipe.version
                for package in recipe.package_names
            ):
                continue
            missing_dependencies = tuple(
                sorted(
                    set(provider.missing_dependencies(recipe.dependencies))
                    | set(provider.missing_build_requirements())
                )
            )
            if missing_dependencies:
                dependency_transaction = provider.resolve_dependency_packages(
                    missing_dependencies
                )
                configured = repository_names(facts.repositories)
                dependency_bindings = tuple(
                    PackageBinding(
                        package,
                        "repository",
                        package,
                        configured,
                        None,
                        None,
                    )
                    for package in missing_dependencies
                )
                actions.append(
                    repository_action(
                        feature_id, dependency_bindings, dependency_transaction
                    )
                )
            actions.append(
                action(
                    ActionKind.AUR_BUILD,
                    feature_id,
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
        if implementation.tools:
            actions.append(
                action(
                    ActionKind.PINNED_TOOL,
                    feature_id,
                    {"tools": implementation.tools, "commands": implementation.commands},
                )
            )
        for entry in workspace.payload[feature_id]:
            actions.append(
                action(
                    ActionKind.USER_FILE,
                    feature_id,
                    {
                        "target": entry.target,
                        "sha256": entry.sha256,
                        "mode": entry.mode,
                        "symlink": entry.symlink,
                    },
                )
            )
        if implementation.reload_user_daemon:
            actions.append(action(ActionKind.USER_DAEMON_RELOAD, feature_id, {}))
        for repository in implementation.repositories:
            actions.append(
                action(
                    ActionKind.PINNED_GIT_ASSET,
                    feature_id,
                    {"url": repository.url, "revision": repository.revision, "target": repository.target},
                )
            )
        if implementation.theme:
            kind = ActionKind.OMARCHY_THEME if workspace.platform.value == "omarchy" else ActionKind.NOCTALIA_THEME
            data = {"name": implementation.theme}
            if kind is ActionKind.NOCTALIA_THEME:
                raise CatalogError("Noctalia themes require a reviewed checksum")
            actions.append(action(kind, feature_id, data))
        for authentication in implementation.authentication:
            actions.append(
                action(
                    ActionKind.MANUAL_AUTHENTICATION,
                    feature_id,
                    {
                        "label": authentication.label,
                        "command": authentication.command,
                        "probe": authentication.probe,
                        "probe_contains": authentication.probe_contains,
                    },
                )
            )
        for unit in implementation.user_units:
            actions.append(
                action(
                    ActionKind.USER_UNIT,
                    feature_id,
                    {
                        "name": unit,
                        "enabled": True,
                        "start": True,
                        "auth_probes": tuple(
                            {"command": item.probe, "contains": item.probe_contains}
                            for item in implementation.authentication
                        ),
                    },
                )
            )
        for unit in implementation.system_units:
            actions.append(
                action(
                    ActionKind.SYSTEM_UNIT,
                    feature_id,
                    {"name": unit, "enabled": True, "start": True},
                )
            )
        if implementation.github_ssh_user:
            keys = (inputs.github_keys or {}).get(implementation.github_ssh_user)
            if not keys:
                raise CatalogError(
                    f"reviewed GitHub SSH keys are required for {implementation.github_ssh_user}"
                )
            actions.append(
                action(
                    ActionKind.AUTHORIZED_SSH_KEYS,
                    feature_id,
                    {
                        "username": implementation.github_ssh_user,
                        "keys": keys,
                        "fingerprints": tuple(ssh_fingerprint(key) for key in keys),
                    },
                )
            )
        if implementation.firewall_rule == "ssh-limit":
            actions.append(
                action(
                    ActionKind.FIREWALL_RULE,
                    feature_id,
                    {"backend": "ufw", "rule": "limit", "port": 22, "protocol": "tcp"},
                )
            )
        if implementation.monitor_profiles:
            content = inputs.monitor_content
            if content is None:
                monitor = root / "common/hardware" / inputs.hardware / ".config/hypr/monitors.lua"
                if not monitor.is_file():
                    raise CatalogError(f"unknown hardware profile: {inputs.hardware}")
                content = monitor.read_text()
            actions.append(generated_file(feature_id, implementation.monitor_target, content))
        for fragment in implementation.fragments:
            target = Path(facts.target_home) / fragment.target
            if target.is_symlink() or not target.is_file():
                raise CatalogError(
                    f"managed fragment prerequisite is missing: {fragment.target}; "
                    "seed the CachyOS account configuration first"
                )
            preimage = target.read_bytes()
            result = render_fragment(
                preimage.decode(),
                fragment.begin_marker,
                fragment.end_marker,
                fragment.content,
            ).encode()
            actions.append(
                action(
                    ActionKind.MANAGED_FRAGMENT,
                    feature_id,
                    {
                        "target": fragment.target,
                        "begin_marker": fragment.begin_marker,
                        "end_marker": fragment.end_marker,
                        "preimage_sha256": hashlib.sha256(preimage).hexdigest(),
                        "content_sha256": hashlib.sha256(fragment.content.encode()).hexdigest(),
                        "result_sha256": hashlib.sha256(result).hexdigest(),
                        "mode": target.stat().st_mode & 0o777,
                        "content": fragment.content,
                    },
                )
            )
        if implementation.default_agent_target:
            actions.append(
                generated_file(
                    feature_id,
                    implementation.default_agent_target,
                    f"{inputs.default_agent}\n",
                )
            )
    actions.sort(key=action_order)
    dependencies = {
        feature_id: workspace.public_catalog[feature_id].requires for feature_id in selected
    }
    return ExecutionPlan.create(
        platform=facts.fingerprint(),
        workspace_digest=workspace.source_digest,
        target_home=facts.target_home,
        selected=selected,
        dependencies=dependencies,
        unavailable=unavailable,
        actions=tuple(actions),
    )


def generated_file(feature: str, target: str, content: str) -> PlannedAction:
    return action(
        ActionKind.GENERATED_FILE,
        feature,
        {
            "target": target,
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
            "mode": 0o644,
            "content": content,
        },
    )


def repository_action(
    feature: str,
    bindings: tuple[PackageBinding, ...],
    transaction: tuple[RepositoryPackage, ...],
) -> PlannedAction:
    return action(
        ActionKind.REPOSITORY_PACKAGES,
        feature,
        {
            "packages": tuple(item.package for item in bindings),
            "sources": tuple(
                {
                    "package": item.package,
                    "repositories": item.repositories,
                }
                for item in bindings
            ),
            "transaction": tuple(item.to_dict() for item in transaction),
        },
    )


def render_fragment(original: str, begin: str, end: str, content: str) -> str:
    if original.count(begin) != original.count(end):
        raise CatalogError("managed fragment markers are unbalanced")
    if original.count(begin) > 1:
        raise CatalogError("managed fragment markers are duplicated")
    block = f"{begin}\n{content.rstrip()}\n{end}"
    if begin not in original:
        separator = "" if not original or original.endswith("\n") else "\n"
        return f"{original}{separator}{block}\n"
    start = original.index(begin)
    finish = original.index(end, start) + len(end)
    return original[:start] + block + original[finish:]


def action(kind: ActionKind, feature: str, data: dict[str, object]) -> PlannedAction:
    return PlannedAction(kind=kind, feature=feature, data=_json_ready(data))


def _json_ready(value: object) -> object:
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    return value


def action_order(item: PlannedAction) -> tuple[int, str, str, str]:
    order = {
        ActionKind.REPOSITORY_PACKAGES: 0,
        ActionKind.AUR_BUILD: 1,
        ActionKind.PINNED_TOOL: 2,
        ActionKind.USER_FILE: 3,
        ActionKind.GENERATED_FILE: 3,
        ActionKind.MANAGED_FRAGMENT: 3,
        ActionKind.USER_DAEMON_RELOAD: 4,
        ActionKind.PINNED_GIT_ASSET: 5,
        ActionKind.OMARCHY_THEME: 6,
        ActionKind.NOCTALIA_THEME: 6,
        ActionKind.MANUAL_AUTHENTICATION: 7,
        ActionKind.USER_UNIT: 8,
        ActionKind.AUTHORIZED_SSH_KEYS: 9,
        ActionKind.REVOKED_SSH_KEY: 9,
        ActionKind.SYSTEM_UNIT: 10,
        ActionKind.FIREWALL_RULE: 11,
        ActionKind.VERIFICATION_PROBE: 12,
    }
    target = str(item.data.get("target", ""))
    return order[item.kind], item.feature, target, item.kind.value


def ssh_fingerprint(key: str) -> str:
    try:
        blob = base64.b64decode(key.split()[1], validate=True)
    except (IndexError, ValueError, binascii.Error) as error:
        raise CatalogError("invalid reviewed SSH public key") from error
    digest = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    return f"SHA256:{digest}"
