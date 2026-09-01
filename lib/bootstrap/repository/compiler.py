from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

from ..catalog import (
    CatalogError,
    load_package_bindings,
    load_workspace,
    load_workspace_from_roots,
)
from ..domain import PlatformId, WorkflowId
from .model import Application, RepositoryModel, WorkflowModel


def compile_repository(root: Path, platform: PlatformId | str) -> RepositoryModel:
    selected = platform if isinstance(platform, PlatformId) else PlatformId(platform)
    legacy = load_workspace(root, selected)
    desktop = load_workspace_from_roots(
        root,
        selected,
        root / "desktop/common",
        root / f"desktop/{selected.value}",
    )
    integrations = load_workspace_from_roots(
        root,
        selected,
        root / "integrations/common",
        root / f"integrations/{selected.value}",
    )
    workflows = {
        WorkflowId.PACKAGES: WorkflowModel(WorkflowId.PACKAGES, legacy),
        WorkflowId.DESKTOP: WorkflowModel(WorkflowId.DESKTOP, desktop),
        WorkflowId.INTEGRATIONS: WorkflowModel(WorkflowId.INTEGRATIONS, integrations),
    }
    digest = _repository_digest(root, selected, legacy.source_digest)
    applications = _load_applications(root / "packages/common/catalog/applications")
    bindings = load_package_bindings(
        root / f"packages/{selected.value}/packages.toml",
        root,
    )
    repository = RepositoryModel(selected, workflows, applications, bindings, digest)
    _validate_repository(repository)
    return repository


def _validate_repository(repository: RepositoryModel) -> None:
    for workflow, model in repository.workflows.items():
        if model.id is not workflow:
            raise CatalogError(f"workflow key does not match model: {workflow.value}")
    visible_defaults = {item.id for item in repository.applications.values() if item.default}
    if not visible_defaults:
        raise CatalogError("packages catalog has no defaults")
    required = {
        requirement
        for application in repository.applications.values()
        for requirement in application.requirements
    }
    missing = required - set(repository.package_bindings)
    if missing:
        raise CatalogError(f"unbound package requirements: {', '.join(sorted(missing))}")


def _repository_digest(root: Path, platform: PlatformId, legacy_digest: str) -> str:
    digest = hashlib.sha256()
    digest.update(f"{platform.value}\0{legacy_digest}\0".encode())
    paths = [
        *sorted((root / "packages/common").rglob("*")),
        *sorted((root / "desktop/common").rglob("*")),
        *sorted((root / f"desktop/{platform.value}").rglob("*")),
        *sorted((root / "integrations/common").rglob("*")),
        *sorted((root / f"integrations/{platform.value}").rglob("*")),
        root / f"packages/{platform.value}/packages.toml",
    ]
    for path in paths:
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _load_applications(directory: Path) -> dict[str, Application]:
    applications: dict[str, Application] = {}
    for path in sorted(directory.glob("*.toml")):
        if path.is_symlink() or path.resolve().parent != directory.resolve():
            raise CatalogError(f"application manifest escapes catalog: {path}")
        try:
            data = tomllib.loads(path.read_text())
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise CatalogError(f"invalid application manifest: {path}") from error
        required = {
            "schema", "id", "label", "group", "default", "requirements",
            "tools", "commands",
        }
        allowed = required | {"hardware_hint", "visible"}
        fields = set(data)
        if not required <= fields or not fields <= allowed or data["schema"] != 1:
            raise CatalogError(f"invalid application schema: {path}")
        identifier = data["id"]
        if not isinstance(identifier, str) or not identifier or identifier in applications:
            raise CatalogError(f"invalid or duplicate application id: {path}")
        values = (data["requirements"], data["tools"], data["commands"])
        if not all(isinstance(value, list) and all(isinstance(item, str) for item in value) for value in values):
            raise CatalogError(f"invalid application lists: {path}")
        hint = data.get("hardware_hint")
        if hint is not None and not isinstance(hint, str):
            raise CatalogError(f"invalid application hardware_hint: {path}")
        applications[identifier] = Application(
            identifier,
            str(data["label"]),
            str(data["group"]),
            bool(data["default"]),
            bool(data.get("visible", True)),
            tuple(data["requirements"]),
            tuple(data["tools"]),
            tuple(data["commands"]),
            hint,
        )
    if not applications:
        raise CatalogError("no package applications found")
    return applications
