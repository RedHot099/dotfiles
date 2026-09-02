from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from ..domain import (
    DesktopRequest,
    IntegrationsRequest,
    PackagesRequest,
    PlannedAction,
    PlatformFingerprint,
    WorkflowId,
)
from ..domain import PlanSchemaError


@dataclass(frozen=True)
class PlanHeader:
    schema: int
    workflow: WorkflowId
    platform: PlatformFingerprint
    repository_digest: str
    target_home: str


@dataclass(frozen=True)
class PackagesEvidence:
    selection_digest: str
    selected: tuple[str, ...]
    installed: tuple[str, ...]

    @classmethod
    def create(cls, selected: frozenset[str], installed: frozenset[str]) -> "PackagesEvidence":
        selection_digest = hashlib.sha256(
            json.dumps(sorted(selected), separators=(",", ":")).encode()
        ).hexdigest()
        return cls(selection_digest, tuple(sorted(selected)), tuple(sorted(installed)))


@dataclass(frozen=True)
class PackagesPlan:
    header: PlanHeader
    request: PackagesRequest
    actions: tuple[PlannedAction, ...]
    digest: str

    @classmethod
    def create(
        cls,
        header: PlanHeader,
        request: PackagesRequest,
        actions: tuple[PlannedAction, ...],
    ) -> "PackagesPlan":
        content = {
            "schema": header.schema,
            "workflow": header.workflow.value,
            "platform": header.platform.to_dict(),
            "repository_digest": header.repository_digest,
            "target_home": header.target_home,
            "applications": sorted(request.applications),
            "actions": [item.to_dict() for item in actions],
        }
        digest = hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return cls(header, request, actions, digest)

    def to_dict(self) -> dict[str, object]:
        return _plan_dict(self.header, {"applications": sorted(self.request.applications)}, self.actions, self.digest)


@dataclass(frozen=True)
class DesktopPlan:
    header: PlanHeader
    request: DesktopRequest
    package_evidence: PackagesEvidence
    actions: tuple[PlannedAction, ...]
    unavailable: tuple[str, ...]
    digest: str

    @classmethod
    def create(
        cls,
        header: PlanHeader,
        request: DesktopRequest,
        package_evidence: PackagesEvidence,
        actions: tuple[PlannedAction, ...],
        unavailable: tuple[str, ...] = (),
    ) -> "DesktopPlan":
        digest = _workflow_digest(
            header,
            {
                "features": sorted(request.features),
                "hardware": request.hardware,
                "package_evidence": _evidence_dict(package_evidence),
                "unavailable": list(unavailable),
            },
            actions,
        )
        return cls(header, request, package_evidence, actions, unavailable, digest)

    def to_dict(self) -> dict[str, object]:
        return _plan_dict(
            self.header,
            {
                "features": sorted(self.request.features),
                "hardware": self.request.hardware,
                "package_evidence": _evidence_dict(self.package_evidence),
                "unavailable": list(self.unavailable),
            },
            self.actions,
            self.digest,
        )


@dataclass(frozen=True)
class IntegrationsPlan:
    header: PlanHeader
    request: IntegrationsRequest
    package_evidence: PackagesEvidence
    actions: tuple[PlannedAction, ...]
    unavailable: tuple[str, ...]
    digest: str

    @classmethod
    def create(
        cls,
        header: PlanHeader,
        request: IntegrationsRequest,
        package_evidence: PackagesEvidence,
        actions: tuple[PlannedAction, ...],
        unavailable: tuple[str, ...] = (),
    ) -> "IntegrationsPlan":
        digest = _workflow_digest(
            header,
            {
                "integrations": sorted(request.integrations),
                "agents": sorted(request.agents),
                "skills": sorted(request.skills),
                "harnesses": sorted(request.harnesses),
                "package_evidence": _evidence_dict(package_evidence),
                "unavailable": list(unavailable),
            },
            actions,
        )
        return cls(header, request, package_evidence, actions, unavailable, digest)

    def to_dict(self) -> dict[str, object]:
        return _plan_dict(
            self.header,
            {
                "integrations": sorted(self.request.integrations),
                "agents": sorted(self.request.agents),
                "skills": sorted(self.request.skills),
                "harnesses": sorted(self.request.harnesses),
                "package_evidence": _evidence_dict(self.package_evidence),
                "unavailable": list(self.unavailable),
            },
            self.actions,
            self.digest,
        )


def _evidence_dict(evidence: PackagesEvidence) -> dict[str, object]:
    return {
        "selection_digest": evidence.selection_digest,
        "selected": list(evidence.selected),
        "installed": list(evidence.installed),
    }


def _workflow_digest(
    header: PlanHeader,
    request: dict[str, object],
    actions: tuple[PlannedAction, ...],
) -> str:
    content = {
        "schema": header.schema,
        "workflow": header.workflow.value,
        "platform": header.platform.to_dict(),
        "repository_digest": header.repository_digest,
        "target_home": header.target_home,
        "request": request,
        "actions": [item.to_dict() for item in actions],
    }
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


WorkflowPlan = PackagesPlan | DesktopPlan | IntegrationsPlan


def plan_from_dict(value: object) -> WorkflowPlan:
    if not isinstance(value, dict):
        raise PlanSchemaError("workflow plan must be an object")
    required = {"schema", "workflow", "platform", "repository_digest", "target_home", "request", "actions", "digest"}
    if set(value) != required or value.get("schema") != 3:
        raise PlanSchemaError("invalid workflow plan schema")
    try:
        workflow = WorkflowId(str(value["workflow"]))
        platform = PlatformFingerprint.from_dict(value["platform"])
        header = PlanHeader(3, workflow, platform, str(value["repository_digest"]), str(value["target_home"]))
        request = value["request"]
        if not isinstance(request, dict) or not isinstance(value["actions"], list):
            raise PlanSchemaError("invalid workflow plan request or actions")
        actions = tuple(PlannedAction.from_dict(item) for item in value["actions"])
        if workflow is WorkflowId.PACKAGES:
            parsed: WorkflowPlan = PackagesPlan.create(header, PackagesRequest(_string_set(request, "applications")), actions)
        elif workflow is WorkflowId.DESKTOP:
            evidence = _parse_evidence(request)
            parsed = DesktopPlan.create(
                header,
                DesktopRequest(_string_set(request, "features"), _required_string(request, "hardware")),
                evidence,
                actions,
                tuple(sorted(_string_set(request, "unavailable"))),
            )
        else:
            evidence = _parse_evidence(request)
            parsed = IntegrationsPlan.create(
                header,
                IntegrationsRequest(
                    _string_set(request, "integrations"),
                    _string_set(request, "agents"),
                    _string_set(request, "skills"),
                    _string_set(request, "harnesses"),
                ),
                evidence,
                actions,
                tuple(sorted(_string_set(request, "unavailable"))),
            )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, PlanSchemaError):
            raise
        raise PlanSchemaError(f"invalid workflow plan: {error}") from error
    if parsed.digest != value["digest"]:
        raise PlanSchemaError("workflow plan digest mismatch")
    return parsed


def _plan_dict(header: PlanHeader, request: dict[str, object], actions: tuple[PlannedAction, ...], digest: str) -> dict[str, object]:
    return {
        "schema": header.schema,
        "workflow": header.workflow.value,
        "platform": header.platform.to_dict(),
        "repository_digest": header.repository_digest,
        "target_home": header.target_home,
        "request": request,
        "actions": [item.to_dict() for item in actions],
        "digest": digest,
    }


def _string_set(data: dict[object, object], key: str) -> frozenset[str]:
    value = data.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PlanSchemaError(f"request.{key} must be a string list")
    if value != sorted(set(value)):
        raise PlanSchemaError(f"request.{key} must be sorted and unique")
    return frozenset(value)


def _required_string(data: dict[object, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise PlanSchemaError(f"request.{key} must be a non-empty string")
    return value


def _parse_evidence(request: dict[object, object]) -> PackagesEvidence:
    value = request.get("package_evidence")
    if not isinstance(value, dict):
        raise PlanSchemaError("request.package_evidence must be an object")
    digest = _required_string(value, "selection_digest")
    selected = tuple(sorted(_string_set(value, "selected")))
    installed = tuple(sorted(_string_set(value, "installed")))
    return PackagesEvidence(digest, selected, installed)
