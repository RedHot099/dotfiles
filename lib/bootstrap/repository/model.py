from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from ..catalog import PackageBinding, Workspace
from ..domain import PlatformId, WorkflowId


@dataclass(frozen=True)
class Application:
    id: str
    label: str
    group: str
    default: bool
    visible: bool
    requirements: tuple[str, ...]
    tools: tuple[str, ...]
    commands: tuple[str, ...]
    hardware_hint: str | None


@dataclass(frozen=True)
class WorkflowModel:
    id: WorkflowId
    workspace: Workspace | None


@dataclass(frozen=True)
class RepositoryModel:
    platform: PlatformId
    workflows: Mapping[WorkflowId, WorkflowModel]
    applications: Mapping[str, Application]
    package_bindings: Mapping[str, PackageBinding]
    source_digest: str

    def __post_init__(self) -> None:
        expected = frozenset(WorkflowId)
        if frozenset(self.workflows) != expected:
            raise ValueError("repository must contain every workflow")
        if any(item.workspace is not None and item.workspace.platform is not self.platform for item in self.workflows.values()):
            raise ValueError("workflow platform does not match repository platform")
        object.__setattr__(self, "workflows", MappingProxyType(dict(self.workflows)))
        object.__setattr__(self, "applications", MappingProxyType(dict(self.applications)))
        object.__setattr__(self, "package_bindings", MappingProxyType(dict(self.package_bindings)))

    def workflow(self, workflow: WorkflowId) -> WorkflowModel:
        return self.workflows[workflow]
