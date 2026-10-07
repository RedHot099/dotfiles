from __future__ import annotations

import hashlib
import base64
import binascii
import json
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath
from types import MappingProxyType
from typing import Mapping, TypeAlias


SHA256_RE = re.compile(r"[0-9a-f]{64}")
IDENTIFIER_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")


class PlanSchemaError(ValueError):
    """The serialized plan does not match the supported schema."""


class PlanHostMismatch(RuntimeError):
    """The plan is bound to a different host state."""


class PlatformId(StrEnum):
    OMARCHY = "omarchy"


class WorkflowId(StrEnum):
    PACKAGES = "packages"
    DESKTOP = "desktop"
    INTEGRATIONS = "integrations"


@dataclass(frozen=True)
class FeatureId:
    workflow: WorkflowId
    name: str

    def __post_init__(self) -> None:
        if not IDENTIFIER_RE.fullmatch(self.name):
            raise ValueError(f"invalid feature id: {self.name!r}")


@dataclass(frozen=True)
class PackagesRequest:
    applications: frozenset[str]


@dataclass(frozen=True)
class DesktopRequest:
    features: frozenset[str]
    hardware: str


@dataclass(frozen=True)
class IntegrationsRequest:
    integrations: frozenset[str]
    agents: frozenset[str]
    skills: frozenset[str]
    harnesses: frozenset[str]


@dataclass(frozen=True)
class PlatformFingerprint:
    platform: PlatformId
    contract_major: int
    os_id: str
    architecture: str
    uid: int
    target_home: str
    omarchy_major: int | None
    hyprland_version: str | None
    uwsm_version: str | None
    shell_name: str
    shell_version: str | None
    pacman_config_digest: str
    repositories: tuple[str, ...]
    capabilities: frozenset[str]

    def __post_init__(self) -> None:
        if self.contract_major < 1:
            raise ValueError("platform contract_major must be positive")
        if self.uid < 0:
            raise ValueError("uid must not be negative")
        _validate_absolute_path(self.target_home, "platform.target_home")
        _validate_sha256(self.pacman_config_digest, "platform.pacman_config_digest")
        if not self.os_id or not self.architecture or not self.shell_name:
            raise ValueError("platform identity fields must not be empty")
        if len(set(self.repositories)) != len(self.repositories):
            raise ValueError("platform repositories must not contain duplicates")

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.platform.value,
            "contract_major": self.contract_major,
            "os_id": self.os_id,
            "architecture": self.architecture,
            "uid": self.uid,
            "target_home": self.target_home,
            "omarchy_major": self.omarchy_major,
            "hyprland_version": self.hyprland_version,
            "uwsm_version": self.uwsm_version,
            "shell_name": self.shell_name,
            "shell_version": self.shell_version,
            "pacman_config_digest": self.pacman_config_digest,
            "repositories": list(self.repositories),
            "capabilities": sorted(self.capabilities),
        }

    @classmethod
    def from_dict(cls, value: object) -> PlatformFingerprint:
        data = _mapping(value, "platform")
        _exact_fields(
            data,
            {
                "id",
                "contract_major",
                "os_id",
                "architecture",
                "uid",
                "target_home",
                "omarchy_major",
                "hyprland_version",
                "uwsm_version",
                "shell_name",
                "shell_version",
                "pacman_config_digest",
                "repositories",
                "capabilities",
            },
            "platform",
        )
        try:
            platform = PlatformId(_string(data["id"], "platform.id"))
        except ValueError as error:
            raise PlanSchemaError(f"unsupported platform id: {data['id']!r}") from error
        return cls(
            platform=platform,
            contract_major=_integer(data["contract_major"], "platform.contract_major"),
            os_id=_string(data["os_id"], "platform.os_id"),
            architecture=_string(data["architecture"], "platform.architecture"),
            uid=_integer(data["uid"], "platform.uid"),
            target_home=_string(data["target_home"], "platform.target_home"),
            omarchy_major=_optional_integer(data["omarchy_major"], "platform.omarchy_major"),
            hyprland_version=_optional_string(data["hyprland_version"], "platform.hyprland_version"),
            uwsm_version=_optional_string(data["uwsm_version"], "platform.uwsm_version"),
            shell_name=_string(data["shell_name"], "platform.shell_name"),
            shell_version=_optional_string(data["shell_version"], "platform.shell_version"),
            pacman_config_digest=_string(data["pacman_config_digest"], "platform.pacman_config_digest"),
            repositories=_strings(data["repositories"], "platform.repositories"),
            capabilities=frozenset(_strings(data["capabilities"], "platform.capabilities")),
        )


class ActionKind(StrEnum):
    REPOSITORY_PACKAGES = "repository-packages"
    AUR_BUILD = "aur-build"
    PINNED_TOOL = "pinned-tool"
    USER_FILE = "user-file"
    GENERATED_FILE = "generated-file"
    PINNED_GIT_ASSET = "pinned-git"
    USER_DAEMON_RELOAD = "user-daemon-reload"
    USER_UNIT = "user-unit"
    SYSTEM_UNIT = "system-unit"
    MANUAL_AUTHENTICATION = "manual-authentication"
    OMARCHY_THEME = "omarchy-theme"
    AUTHORIZED_SSH_KEYS = "authorized-ssh-keys"
    REVOKED_SSH_KEY = "revoked-ssh-key"
    FIREWALL_RULE = "firewall-rule"
    VERIFICATION_PROBE = "verification-probe"
    HYPRLAND_RELOAD = "hyprland-reload"


_ACTION_DATA_FIELDS: dict[ActionKind, tuple[frozenset[str], frozenset[str]]] = {
    ActionKind.REPOSITORY_PACKAGES: (
        frozenset({"packages", "sources", "transaction"}),
        frozenset(),
    ),
    ActionKind.AUR_BUILD: (
        frozenset(
            {"packages", "package_base", "version", "url", "commit", "files", "dependencies"}
        ),
        frozenset(),
    ),
    ActionKind.PINNED_TOOL: (
        frozenset({"tools", "commands"}),
        frozenset({"artifact_checksums"}),
    ),
    ActionKind.USER_FILE: (
        frozenset({"target", "sha256", "mode"}),
        frozenset({"symlink", "seed"}),
    ),
    ActionKind.GENERATED_FILE: (
        frozenset({"target", "sha256", "mode", "content"}),
        frozenset(),
    ),
    ActionKind.PINNED_GIT_ASSET: (
        frozenset({"url", "revision", "target"}),
        frozenset({"sha256"}),
    ),
    ActionKind.USER_UNIT: (
        frozenset({"name"}),
        frozenset({"auth_probes", "enabled", "start"}),
    ),
    ActionKind.USER_DAEMON_RELOAD: (frozenset(), frozenset()),
    ActionKind.SYSTEM_UNIT: (
        frozenset({"name", "enabled", "start"}),
        frozenset(),
    ),
    ActionKind.MANUAL_AUTHENTICATION: (
        frozenset({"label", "command", "probe", "probe_contains"}),
        frozenset({"order"}),
    ),
    ActionKind.OMARCHY_THEME: (frozenset({"name"}), frozenset({"revision"})),
    ActionKind.AUTHORIZED_SSH_KEYS: (
        frozenset({"username", "keys", "fingerprints"}),
        frozenset(),
    ),
    ActionKind.REVOKED_SSH_KEY: (frozenset({"fingerprint"}), frozenset()),
    ActionKind.FIREWALL_RULE: (
        frozenset({"backend", "port", "rule"}),
        frozenset({"protocol"}),
    ),
    ActionKind.VERIFICATION_PROBE: (
        frozenset({"label", "command", "expected_exit"}),
        frozenset({"contains"}),
    ),
    ActionKind.HYPRLAND_RELOAD: (frozenset(), frozenset()),
}


JsonScalar: TypeAlias = str | int | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
FrozenJsonValue: TypeAlias = JsonScalar | tuple["FrozenJsonValue", ...] | Mapping[str, "FrozenJsonValue"]


@dataclass(frozen=True)
class PlannedAction:
    """A discriminated action with a closed kind and validated payload."""

    kind: ActionKind
    feature: str
    data: Mapping[str, FrozenJsonValue]

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ActionKind):
            raise ValueError(f"invalid action kind: {self.kind!r}")
        if not IDENTIFIER_RE.fullmatch(self.feature):
            raise ValueError(f"invalid feature id: {self.feature!r}")
        normalized = _json_object(self.data, f"action {self.kind.value}.data")
        _validate_action_data(self.kind, normalized)
        object.__setattr__(self, "data", _freeze_object(normalized))

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind.value, "feature": self.feature, "data": _thaw_object(self.data)}

    @classmethod
    def from_dict(cls, value: object) -> PlannedAction:
        data = _mapping(value, "action")
        _exact_fields(data, {"kind", "feature", "data"}, "action")
        raw_kind = _string(data["kind"], "action.kind")
        try:
            kind = ActionKind(raw_kind)
        except ValueError as error:
            raise PlanSchemaError(f"unknown action kind: {raw_kind!r}") from error
        feature = _string(data["feature"], "action.feature")
        if not IDENTIFIER_RE.fullmatch(feature):
            raise PlanSchemaError(f"invalid action.feature: {feature!r}")
        try:
            return cls(kind=kind, feature=feature, data=_json_object(data["data"], f"action {raw_kind}.data"))
        except ValueError as error:
            if isinstance(error, PlanSchemaError):
                raise
            raise PlanSchemaError(str(error)) from error


@dataclass(frozen=True)
class ExecutionPlan:
    schema: int
    platform: PlatformFingerprint
    workspace_digest: str
    target_home: str
    selected: tuple[str, ...]
    dependencies: Mapping[str, tuple[str, ...]]
    unavailable: Mapping[str, str]
    actions: tuple[PlannedAction, ...]
    digest: str

    def __post_init__(self) -> None:
        if self.schema != 3:
            raise ValueError("ExecutionPlan accepts only schema 3")
        _validate_sha256(self.workspace_digest, "workspace_digest")
        _validate_sha256(self.digest, "digest")
        _validate_absolute_path(self.target_home, "target_home")
        if self.target_home != self.platform.target_home:
            raise ValueError("plan target_home differs from its platform fingerprint")
        selected = tuple(self.selected)
        for feature in selected:
            if not isinstance(feature, str) or not IDENTIFIER_RE.fullmatch(feature):
                raise ValueError(f"invalid selected feature id: {feature!r}")
        if len(set(selected)) != len(selected):
            raise ValueError("selected features must not contain duplicates")
        normalized_dependencies: dict[str, tuple[str, ...]] = {}
        for feature, required in self.dependencies.items():
            if not isinstance(feature, str) or not IDENTIFIER_RE.fullmatch(feature):
                raise ValueError(f"invalid dependency feature id: {feature!r}")
            values = tuple(required)
            if any(not IDENTIFIER_RE.fullmatch(item) for item in values):
                raise ValueError(f"invalid dependency id for {feature}")
            normalized_dependencies[feature] = values
        if set(normalized_dependencies) != set(selected):
            raise ValueError("dependencies must contain exactly the selected features")
        unknown_dependencies = {
            required
            for values in normalized_dependencies.values()
            for required in values
            if required not in selected
        }
        if unknown_dependencies:
            raise ValueError("dependencies refer to unselected features: " + ", ".join(sorted(unknown_dependencies)))
        unavailable = dict(self.unavailable)
        if set(unavailable) - set(selected):
            raise ValueError("unavailable reasons refer to unselected features")
        if any(not isinstance(reason, str) or not reason for reason in unavailable.values()):
            raise ValueError("unavailable reasons must be non-empty strings")
        actions = tuple(self.actions)
        if any(not isinstance(action, PlannedAction) for action in actions):
            raise ValueError("actions must contain PlannedAction values")
        unknown_action_features = {action.feature for action in actions if action.feature not in selected}
        if unknown_action_features:
            raise ValueError("actions refer to unselected features: " + ", ".join(sorted(unknown_action_features)))
        object.__setattr__(self, "selected", selected)
        object.__setattr__(self, "dependencies", MappingProxyType(normalized_dependencies))
        object.__setattr__(self, "unavailable", MappingProxyType(unavailable))
        object.__setattr__(self, "actions", actions)

    @classmethod
    def create(
        cls,
        *,
        platform: PlatformFingerprint,
        workspace_digest: str,
        target_home: str,
        selected: tuple[str, ...],
        dependencies: Mapping[str, tuple[str, ...]],
        unavailable: Mapping[str, str] | None = None,
        actions: tuple[PlannedAction, ...],
    ) -> ExecutionPlan:
        content = _plan_content(
            platform=platform,
            workspace_digest=workspace_digest,
            target_home=target_home,
            selected=selected,
            dependencies=dependencies,
            unavailable=unavailable or {},
            actions=actions,
        )
        digest = _digest(content)
        return cls(3, platform, workspace_digest, target_home, selected, dependencies, unavailable or {}, actions, digest)

    def to_dict(self) -> dict[str, object]:
        content = _plan_content(
            platform=self.platform,
            workspace_digest=self.workspace_digest,
            target_home=self.target_home,
            selected=self.selected,
            dependencies=self.dependencies,
            unavailable=self.unavailable,
            actions=self.actions,
        )
        return {**content, "digest": self.digest}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def parse_plan_json(serialized: str | bytes) -> ExecutionPlan:
    try:
        raw = json.loads(serialized, object_pairs_hook=_unique_json_object)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise PlanSchemaError("plan is not valid JSON") from error
    data = _mapping(raw, "plan")
    if data.get("schema") == 1:
        raise PlanSchemaError("schema 1 plans are unsupported; regenerate the plan")
    _exact_fields(
        data,
        {"schema", "platform", "workspace_digest", "target_home", "selected", "dependencies", "unavailable", "actions", "digest"},
        "plan",
    )
    schema = _integer(data["schema"], "schema")
    if schema != 3:
        raise PlanSchemaError(f"unsupported plan schema: {schema}")
    try:
        platform = PlatformFingerprint.from_dict(data["platform"])
        workspace_digest = _string(data["workspace_digest"], "workspace_digest")
        target_home = _string(data["target_home"], "target_home")
        selected = _identifiers(data["selected"], "selected")
        dependencies = _dependencies(data["dependencies"])
        unavailable = _string_mapping(data["unavailable"], "unavailable")
        actions = tuple(PlannedAction.from_dict(item) for item in _list(data["actions"], "actions"))
        digest = _string(data["digest"], "digest")
        plan = ExecutionPlan(2, platform, workspace_digest, target_home, selected, dependencies, unavailable, actions, digest)
    except ValueError as error:
        if isinstance(error, PlanSchemaError):
            raise
        raise PlanSchemaError(str(error)) from error
    expected = _digest({key: value for key, value in plan.to_dict().items() if key != "digest"})
    if plan.digest != expected:
        raise PlanSchemaError("plan digest does not match its content")
    return plan


def _unique_json_object(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise PlanSchemaError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def assert_plan_matches_host(plan: ExecutionPlan, host: object) -> None:
    """Fail before an executor is allowed to mutate the target host."""

    fingerprint_method = getattr(host, "fingerprint", None)
    if not callable(fingerprint_method):
        raise TypeError("host facts must provide fingerprint()")
    actual = fingerprint_method()
    if not isinstance(actual, PlatformFingerprint):
        raise TypeError("host fingerprint() returned an invalid value")
    if plan.platform != actual:
        differing = [
            name
            for name in PlatformFingerprint.__dataclass_fields__
            if getattr(plan.platform, name) != getattr(actual, name)
        ]
        raise PlanHostMismatch("plan does not match host: " + ", ".join(differing))
    if plan.target_home != actual.target_home:
        raise PlanHostMismatch("plan target_home does not match host")


def _plan_content(
    *,
    platform: PlatformFingerprint,
    workspace_digest: str,
    target_home: str,
    selected: tuple[str, ...],
    dependencies: Mapping[str, tuple[str, ...]],
    unavailable: Mapping[str, str],
    actions: tuple[PlannedAction, ...],
) -> dict[str, object]:
    return {
        "schema": 3,
        "platform": platform.to_dict(),
        "workspace_digest": workspace_digest,
        "target_home": target_home,
        "selected": list(selected),
        "dependencies": {feature: list(required) for feature, required in sorted(dependencies.items())},
        "unavailable": dict(sorted(unavailable.items())),
        "actions": [action.to_dict() for action in actions],
    }


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise PlanSchemaError(f"{field} must be an object")
    return dict(value)


def _exact_fields(value: Mapping[str, object], expected: set[str], field: str) -> None:
    unknown = sorted(value.keys() - expected)
    missing = sorted(expected - value.keys())
    if unknown:
        raise PlanSchemaError(f"unknown {field} fields: {', '.join(unknown)}")
    if missing:
        raise PlanSchemaError(f"missing {field} fields: {', '.join(missing)}")


def _string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise PlanSchemaError(f"{field} must be a string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise PlanSchemaError(f"{field} must be an integer")
    return value


def _optional_integer(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field)


def _list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise PlanSchemaError(f"{field} must be an array")
    return value


def _strings(value: object, field: str) -> tuple[str, ...]:
    return tuple(_string(item, f"{field}[]") for item in _list(value, field))


def _identifiers(value: object, field: str) -> tuple[str, ...]:
    result = _strings(value, field)
    for item in result:
        if not IDENTIFIER_RE.fullmatch(item):
            raise PlanSchemaError(f"invalid {field} id: {item!r}")
    return result


def _dependencies(value: object) -> dict[str, tuple[str, ...]]:
    data = _mapping(value, "dependencies")
    return {feature: _identifiers(required, f"dependencies.{feature}") for feature, required in data.items()}


def _string_mapping(value: object, field: str) -> dict[str, str]:
    data = _mapping(value, field)
    return {key: _string(item, f"{field}.{key}") for key, item in data.items()}


def _json_object(value: object, field: str) -> dict[str, JsonValue]:
    data = _mapping(value, field)
    normalized: dict[str, JsonValue] = {}
    for key, item in data.items():
        normalized[key] = _json_value(item, f"{field}.{key}")
    return normalized


def _json_value(value: object, field: str) -> JsonValue:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, list):
        return [_json_value(item, f"{field}[]") for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _json_value(item, f"{field}.{key}") for key, item in value.items()}
    raise PlanSchemaError(f"{field} is not a JSON value")


def _freeze_object(value: Mapping[str, JsonValue]) -> Mapping[str, FrozenJsonValue]:
    return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})


def _freeze_json(value: JsonValue) -> FrozenJsonValue:
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, dict):
        return _freeze_object(value)
    return value


def _thaw_object(value: Mapping[str, FrozenJsonValue]) -> dict[str, JsonValue]:
    return {key: _thaw_json(item) for key, item in value.items()}


def _thaw_json(value: FrozenJsonValue) -> JsonValue:
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    if isinstance(value, Mapping):
        return _thaw_object(value)
    return value


def _validate_action_data(kind: ActionKind, data: Mapping[str, JsonValue]) -> None:
    required, optional = _ACTION_DATA_FIELDS[kind]
    unknown = sorted(data.keys() - required - optional)
    missing = sorted(required - data.keys())
    if unknown:
        raise PlanSchemaError(f"unknown {kind.value} data fields: {', '.join(unknown)}")
    if missing:
        raise PlanSchemaError(f"missing {kind.value} data fields: {', '.join(missing)}")

    string_fields = {
        "package_base",
        "version",
        "commit",
        "target",
        "sha256",
        "begin_marker",
        "end_marker",
        "preimage_sha256",
        "content_sha256",
        "url",
        "name",
        "label",
        "revision",
        "username",
        "fingerprint",
        "backend",
        "rule",
        "protocol",
        "contains",
    }
    sequence_fields = {"packages", "dependencies", "tools", "commands", "keys", "fingerprints"}
    boolean_fields = {"enabled", "start", "seed"}
    integer_fields = {"mode", "port", "expected_exit", "order"}
    nullable_string_fields = {"symlink", "probe_contains"}
    for field, value in data.items():
        if field in string_fields and not isinstance(value, str):
            raise ValueError(f"{kind.value} data.{field} must be a string")
        if field in sequence_fields and (
            not isinstance(value, list) or any(not isinstance(item, str) for item in value)
        ):
            raise ValueError(f"{kind.value} data.{field} must be an array of strings")
        if field in boolean_fields and not isinstance(value, bool):
            raise ValueError(f"{kind.value} data.{field} must be a boolean")
        if field in integer_fields and (not isinstance(value, int) or isinstance(value, bool)):
            raise ValueError(f"{kind.value} data.{field} must be an integer")
        if field in nullable_string_fields and value is not None and not isinstance(value, str):
            raise ValueError(f"{kind.value} data.{field} must be a string or null")

    for field in ("sha256", "preimage_sha256", "content_sha256"):
        if field in data:
            _validate_sha256(str(data[field]), f"{kind.value} data.{field}")
    for field in ("commit", "revision"):
        if field in data and not re.fullmatch(r"[0-9a-f]{40}", str(data[field])):
            raise ValueError(f"{kind.value} data.{field} must be a full Git commit")
    if kind is ActionKind.REPOSITORY_PACKAGES:
        _validate_package_sources(data["sources"])
        _validate_package_transaction(data["transaction"])
    if kind is ActionKind.AUR_BUILD:
        package_base = str(data["package_base"])
        if data["url"] != f"https://aur.archlinux.org/{package_base}.git":
            raise ValueError("aur-build data.url must be the package base AUR HTTPS URL")
        _validate_aur_files(data["files"])


def _validate_package_sources(value: JsonValue) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError("repository-packages data.sources must be a non-empty array")
    for item in value:
        if not isinstance(item, dict) or set(item) != {"package", "repositories"}:
            raise ValueError("repository-packages source must have package and repositories")
        package = item["package"]
        repositories = item["repositories"]
        if not isinstance(package, str) or not IDENTIFIER_RE.fullmatch(package):
            raise ValueError("repository-packages source has an unsafe package")
        if (
            not isinstance(repositories, list)
            or not repositories
            or any(not isinstance(repo, str) or not IDENTIFIER_RE.fullmatch(repo) for repo in repositories)
        ):
            raise ValueError("repository-packages source has unsafe repositories")


def _validate_package_transaction(value: JsonValue) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError("repository-packages data.transaction must be a non-empty array")
    for item in value:
        if not isinstance(item, dict) or set(item) != {"repository", "name", "version"}:
            raise ValueError("repository-packages transaction row is invalid")
        if any(not isinstance(item[field], str) or not item[field] for field in item):
            raise ValueError("repository-packages transaction values must be strings")


def _validate_aur_files(value: JsonValue) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError("aur-build data.files must be a non-empty array")
    for item in value:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "content_base64"}:
            raise ValueError("aur-build file record is invalid")
        path = item["path"]
        digest = item["sha256"]
        encoded = item["content_base64"]
        if not isinstance(path, str) or PurePath(path).is_absolute() or ".." in PurePath(path).parts:
            raise ValueError("aur-build file path is unsafe")
        if not isinstance(digest, str):
            raise ValueError("aur-build file digest must be a string")
        _validate_sha256(digest, "aur-build file digest")
        if not isinstance(encoded, str):
            raise ValueError("aur-build file content must be base64")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError("aur-build file content must be base64") from error
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("aur-build file content digest differs")


def _validate_sha256(value: str, field: str) -> None:
    if not SHA256_RE.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")


def _validate_absolute_path(value: str, field: str) -> None:
    path = PurePath(value)
    if not path.is_absolute() or os.path.normpath(value) != value:
        raise ValueError(f"{field} must be a normalized absolute path")
