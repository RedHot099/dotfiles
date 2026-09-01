from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from ..domain import PackagesRequest, PlannedAction, PlatformFingerprint, WorkflowId


@dataclass(frozen=True)
class PlanHeader:
    schema: int
    workflow: WorkflowId
    platform: PlatformFingerprint
    repository_digest: str
    target_home: str


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
