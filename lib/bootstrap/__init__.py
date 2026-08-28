"""Schema 2 domain model and platform detection."""

from .domain import (
    ActionKind,
    ExecutionPlan,
    PlanHostMismatch,
    PlanSchemaError,
    PlatformFingerprint,
    PlatformId,
    PlannedAction,
    assert_plan_matches_host,
    parse_plan_json,
)
from .platform import HostProbe, PlatformDetectionError, PlatformFacts, detect_platform
from .host import LocalHostProbe

__all__ = [
    "ActionKind",
    "ExecutionPlan",
    "HostProbe",
    "LocalHostProbe",
    "PlanHostMismatch",
    "PlanSchemaError",
    "PlatformDetectionError",
    "PlatformFacts",
    "PlatformFingerprint",
    "PlatformId",
    "PlannedAction",
    "assert_plan_matches_host",
    "detect_platform",
    "parse_plan_json",
]
