from __future__ import annotations

import hashlib
import os
import posixpath
import re
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping

from .domain import PlatformId


IDENTIFIER_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")
PACKAGE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9@._+:-]*")
TOOL_RE = re.compile(
    r"(?:npm:)?(?:@[A-Za-z0-9_.-]+/)?[A-Za-z0-9_.-]+@"
    r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9_.-]+)?"
)
GIT_COMMIT_RE = re.compile(r"[0-9a-fA-F]{40}")
SYSTEM_UNIT_ALLOWLIST = frozenset({"sshd.service", "tailscaled.service"})
COMMON_PLATFORM_REFERENCE_RE = re.compile(
    rb"/usr/share/omarchy"
    rb"|(?:^|[/\s\"'])\.config/omarchy(?:[/\s\"']|$)"
    rb"|(?<![\w.-])omarchy-[A-Za-z0-9_.-]+"
    rb"|(?<![\w.])o\.[A-Za-z_]\w*",
    re.IGNORECASE | re.MULTILINE,
)


class CatalogError(ValueError):
    """The workspace catalog is incomplete or unsafe."""


@dataclass(frozen=True)
class PublicFeature:
    id: str
    label: str
    description: str
    group: str
    default: bool
    visible: bool
    requires: tuple[str, ...]


@dataclass(frozen=True)
class Profile:
    id: str
    label: str
    default: bool
    features: tuple[str, ...]


@dataclass(frozen=True)
class FileSpec:
    source: str
    target: str
    source_bundle: str | None


@dataclass(frozen=True)
class AuthenticationSpec:
    label: str
    command: tuple[str, ...]
    probe: tuple[str, ...]
    probe_contains: str | None


@dataclass(frozen=True)
class PayloadEntry:
    source: str
    target: str
    sha256: str
    mode: int
    symlink: str | None


@dataclass(frozen=True)
class RepositorySpec:
    url: str
    revision: str
    target: str


@dataclass(frozen=True)
class PackageBinding:
    requirement: str
    provider: str
    package: str
    repositories: tuple[str, ...]
    url: str | None
    revision: str | None


@dataclass(frozen=True)
class FeatureImplementation:
    id: str
    bundle: str
    package_requirements: tuple[str, ...]
    tools: tuple[str, ...]
    commands: tuple[str, ...]
    files: tuple[FileSpec, ...]
    repositories: tuple[RepositorySpec, ...]
    reload_user_daemon: bool
    user_units: tuple[str, ...]
    system_units: tuple[str, ...]
    authentication: tuple[AuthenticationSpec, ...]
    theme: str | None
    github_ssh_user: str | None
    firewall_rule: str | None
    monitor_profiles: bool
    default_agent_target: str | None
    monitor_target: str
    available: bool
    unavailable_reason: str | None
    listens: bool
    listening_ports: tuple[int, ...]

    @property
    def opens_listening_port(self) -> bool:
        return self.listens or bool(self.listening_ports)


@dataclass(frozen=True)
class Workspace:
    platform: PlatformId
    public_catalog: Mapping[str, PublicFeature]
    profiles: Mapping[str, Profile]
    implementations: Mapping[str, FeatureImplementation]
    package_bindings: Mapping[str, PackageBinding]
    payload: Mapping[str, tuple[PayloadEntry, ...]]
    source_digest: str


@dataclass(frozen=True)
class _Manifest:
    path: Path
    relative_path: str
    content: bytes
    data: dict[str, object]


@dataclass(frozen=True)
class _PayloadNode:
    path: Path
    relative_path: str
    kind: str
    content: bytes


def load_workspace(root: Path, platform: PlatformId | str) -> Workspace:
    """Load common plus one platform bundle and validate it before planning."""

    repository_root = root.resolve()
    selected_platform = _platform_id(platform)
    return load_workspace_from_roots(
        repository_root,
        selected_platform,
        repository_root / "common",
        repository_root / selected_platform.value,
        repository_root / selected_platform.value / "packages.toml",
    )


def load_workspace_from_roots(
    root: Path,
    platform: PlatformId | str,
    common_root: Path,
    platform_root: Path,
    package_path: Path | None = None,
) -> Workspace:
    repository_root = root.resolve()
    selected_platform = _platform_id(platform)

    feature_manifests = _read_manifests(
        common_root / "catalog" / "features", repository_root
    )
    profile_manifests = _read_manifests(
        common_root / "catalog" / "profiles", repository_root
    )
    common_manifests = _read_manifests(
        common_root / "implementations", repository_root
    )
    platform_manifests = _read_manifests(
        platform_root / "implementations", repository_root
    )
    package_manifest = (
        _read_optional_manifest(package_path, repository_root)
        if package_path is not None
        else None
    )
    if not feature_manifests:
        raise CatalogError("no public features found")

    _validate_common_purity(feature_manifests + common_manifests)
    features = _load_features(feature_manifests)
    _validate_dependencies(features)
    profiles = _load_profiles(profile_manifests, features)
    common = _load_implementations(common_manifests, "common")
    selected = _load_implementations(platform_manifests, selected_platform.value)
    implementations = _compose_implementations(features, common, selected)
    package_bindings = (
        _load_package_bindings(package_manifest)
        if package_manifest is not None
        else {}
    )

    payload_nodes, payload = _validate_implementations(
        repository_root,
        common_root,
        platform_root,
        features,
        implementations,
        package_bindings,
    )
    _validate_listening_service_defaults(features, implementations)
    _validate_common_payload_purity(payload_nodes, common_root)

    digest = _source_digest(
        selected_platform,
        feature_manifests
        + profile_manifests
        + common_manifests
        + platform_manifests
        + ([package_manifest] if package_manifest else []),
        payload_nodes,
    )
    return Workspace(
        platform=selected_platform,
        public_catalog=MappingProxyType(dict(sorted(features.items()))),
        profiles=MappingProxyType(dict(sorted(profiles.items()))),
        implementations=MappingProxyType(dict(sorted(implementations.items()))),
        package_bindings=MappingProxyType(dict(sorted(package_bindings.items()))),
        payload=MappingProxyType(payload),
        source_digest=digest,
    )


def load_package_bindings(path: Path, repository_root: Path) -> Mapping[str, PackageBinding]:
    manifest = _read_optional_manifest(path, repository_root.resolve())
    return MappingProxyType(dict(sorted(_load_package_bindings(manifest).items())))


def _platform_id(value: PlatformId | str) -> PlatformId:
    try:
        return value if isinstance(value, PlatformId) else PlatformId(value)
    except ValueError as error:
        raise CatalogError(f"unsupported platform: {value!r}") from error


def _read_manifests(directory: Path, repository_root: Path) -> list[_Manifest]:
    if not directory.is_dir():
        return []
    manifests: list[_Manifest] = []
    for path in sorted(directory.glob("*.toml")):
        if path.is_symlink() or not _within(path.resolve(), directory.resolve()):
            raise CatalogError(f"manifest escapes its bundle: {path}")
        content = path.read_bytes()
        try:
            parsed = tomllib.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise CatalogError(f"invalid TOML manifest: {path}") from error
        manifests.append(
            _Manifest(
                path=path,
                relative_path=path.relative_to(repository_root).as_posix(),
                content=content,
                data=parsed,
            )
        )
    return manifests


def _read_optional_manifest(path: Path, repository_root: Path) -> _Manifest | None:
    if not path.is_file():
        return None
    if path.is_symlink() or not _within(path.resolve(), path.parent.resolve()):
        raise CatalogError(f"manifest escapes its bundle: {path}")
    content = path.read_bytes()
    try:
        data = tomllib.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise CatalogError(f"invalid TOML manifest: {path}") from error
    return _Manifest(path, path.relative_to(repository_root).as_posix(), content, data)


def _load_features(manifests: list[_Manifest]) -> dict[str, PublicFeature]:
    features: dict[str, PublicFeature] = {}
    for manifest in manifests:
        raw = manifest.data
        _schema_two(
            raw,
            {"schema", "id", "label", "description", "group", "default", "visible", "requires"},
            manifest.path,
        )
        feature_id = _identifier(raw, "id", manifest.path)
        _matching_filename(feature_id, manifest.path)
        feature = PublicFeature(
            id=feature_id,
            label=_string(raw, "label", manifest.path),
            description=_string(raw, "description", manifest.path),
            group=_optional_string(raw, "group", "Other", manifest.path),
            default=_boolean(raw, "default", False, manifest.path),
            visible=_boolean(raw, "visible", True, manifest.path),
            requires=_strings(raw, "requires", manifest.path),
        )
        if feature_id in features:
            raise CatalogError(f"duplicate public feature: {feature_id}")
        features[feature_id] = feature
    return features


def _load_profiles(
    manifests: list[_Manifest], features: Mapping[str, PublicFeature]
) -> dict[str, Profile]:
    profiles: dict[str, Profile] = {}
    for manifest in manifests:
        raw = manifest.data
        _schema_two(raw, {"schema", "id", "label", "default", "features"}, manifest.path)
        profile_id = _identifier(raw, "id", manifest.path)
        _matching_filename(profile_id, manifest.path)
        profile = Profile(
            id=profile_id,
            label=_string(raw, "label", manifest.path),
            default=_boolean(raw, "default", False, manifest.path),
            features=_strings(raw, "features", manifest.path),
        )
        missing = set(profile.features) - set(features)
        if missing:
            raise CatalogError(
                f"{profile_id} profile selects unknown feature: {', '.join(sorted(missing))}"
            )
        if profile_id in profiles:
            raise CatalogError(f"duplicate profile: {profile_id}")
        profiles[profile_id] = profile
    return profiles


def _load_implementations(
    manifests: list[_Manifest], bundle: str
) -> dict[str, FeatureImplementation]:
    implementations: dict[str, FeatureImplementation] = {}
    for manifest in manifests:
        raw = manifest.data
        _schema_two(
            raw,
            {
                "schema", "id", "package_requirements", "tools", "commands", "files",
                "repositories", "reload_user_daemon", "user_units", "system_units", "authentication",
                "theme", "github_ssh_user", "firewall_rule", "monitor_profiles",
                "default_agent_target", "monitor_target", "available",
                "unavailable_reason", "listens", "listening_ports",
            },
            manifest.path,
        )
        feature_id = _identifier(raw, "id", manifest.path)
        _matching_filename(feature_id, manifest.path)
        files = tuple(FileSpec(*_file_table(item, manifest.path)) for item in _tables(raw, "files", manifest.path))
        repositories = tuple(RepositorySpec(*_repository_table(item, manifest.path)) for item in _tables(raw, "repositories", manifest.path))
        authentication = tuple(
            AuthenticationSpec(*_authentication_table(item, manifest.path))
            for item in _tables(raw, "authentication", manifest.path)
        )
        available = _boolean(raw, "available", True, manifest.path)
        unavailable_reason = _optional_nullable_string(raw, "unavailable_reason", manifest.path)
        if available == (unavailable_reason is not None):
            raise CatalogError(
                f"{feature_id} must set unavailable_reason exactly when available is false"
            )
        implementation = FeatureImplementation(
            id=feature_id,
            bundle=bundle,
            package_requirements=_strings(raw, "package_requirements", manifest.path),
            tools=_strings(raw, "tools", manifest.path),
            commands=_strings(raw, "commands", manifest.path),
            files=files,
            repositories=repositories,
            reload_user_daemon=_boolean(raw, "reload_user_daemon", False, manifest.path),
            user_units=_strings(raw, "user_units", manifest.path),
            system_units=_strings(raw, "system_units", manifest.path),
            authentication=authentication,
            theme=_optional_nullable_string(raw, "theme", manifest.path),
            github_ssh_user=_optional_nullable_string(raw, "github_ssh_user", manifest.path),
            firewall_rule=_optional_nullable_string(raw, "firewall_rule", manifest.path),
            monitor_profiles=_boolean(raw, "monitor_profiles", False, manifest.path),
            default_agent_target=_optional_nullable_string(raw, "default_agent_target", manifest.path),
            monitor_target=_optional_string(
                raw, "monitor_target", ".config/hypr/monitors.lua", manifest.path
            ),
            available=available,
            unavailable_reason=unavailable_reason,
            listens=_boolean(raw, "listens", False, manifest.path),
            listening_ports=_ports(raw, manifest.path),
        )
        if feature_id in implementations:
            raise CatalogError(f"duplicate implementation in {bundle}: {feature_id}")
        implementations[feature_id] = implementation
    return implementations


def _compose_implementations(
    features: Mapping[str, PublicFeature],
    common: Mapping[str, FeatureImplementation],
    selected: Mapping[str, FeatureImplementation],
) -> dict[str, FeatureImplementation]:
    unknown = (set(common) | set(selected)) - set(features)
    if unknown:
        raise CatalogError("implementation for unknown feature: " + ", ".join(sorted(unknown)))
    duplicates = set(common) & set(selected)
    if duplicates:
        raise CatalogError(
            "feature has two implementations instead of one complete record: "
            + ", ".join(sorted(duplicates))
        )
    implementations = {**common, **selected}
    missing = set(features) - set(implementations)
    if missing:
        raise CatalogError("missing implementation: " + ", ".join(sorted(missing)))
    return implementations


def _load_package_bindings(manifest: _Manifest | None) -> dict[str, PackageBinding]:
    if manifest is None:
        raise CatalogError("selected platform has no package bindings")
    raw = manifest.data
    _schema_two(raw, {"schema", "bindings"}, manifest.path)
    bindings: dict[str, PackageBinding] = {}
    for item in _tables(raw, "bindings", manifest.path):
        _table_fields(
            item,
            {"requirement", "provider", "package"},
            {"repositories", "url", "revision"},
            "bindings",
            manifest.path,
        )
        requirement = _table_string(item, "requirement", manifest.path)
        provider = _table_string(item, "provider", manifest.path)
        package = _table_string(item, "package", manifest.path)
        repositories = _table_strings(item, "repositories", manifest.path)
        url = _table_optional_string(item, "url", manifest.path)
        revision = _table_optional_string(item, "revision", manifest.path)
        if provider == "repository":
            valid = bool(repositories) and url is None and revision is None
        elif provider == "aur":
            valid = (
                not repositories
                and url == f"https://aur.archlinux.org/{package}.git"
                and revision is not None
                and GIT_COMMIT_RE.fullmatch(revision) is not None
            )
        else:
            raise CatalogError(f"unknown package provider: {provider}")
        if not valid:
            raise CatalogError(f"invalid {provider} binding: {requirement}")
        if not IDENTIFIER_RE.fullmatch(requirement) or not PACKAGE_RE.fullmatch(package):
            raise CatalogError(f"unsafe package binding: {requirement}")
        if any(not IDENTIFIER_RE.fullmatch(repository) for repository in repositories):
            raise CatalogError(f"unsafe package repository binding: {requirement}")
        if requirement in bindings:
            raise CatalogError(f"duplicate package binding: {requirement}")
        bindings[requirement] = PackageBinding(
            requirement, provider, package, repositories, url, revision
        )
    return bindings


def _validate_dependencies(features: Mapping[str, PublicFeature]) -> None:
    for feature in features.values():
        missing = set(feature.requires) - set(features)
        if missing:
            raise CatalogError(
                f"{feature.id} requires unknown feature: {', '.join(sorted(missing))}"
            )

    visited: set[str] = set()
    visiting: list[str] = []

    def visit(feature_id: str) -> None:
        if feature_id in visited:
            return
        if feature_id in visiting:
            cycle = visiting[visiting.index(feature_id) :] + [feature_id]
            raise CatalogError("dependency cycle: " + " -> ".join(cycle))
        visiting.append(feature_id)
        for dependency in features[feature_id].requires:
            visit(dependency)
        visiting.pop()
        visited.add(feature_id)

    for feature_id in sorted(features):
        visit(feature_id)


def _validate_implementations(
    repository_root: Path,
    common_root: Path,
    platform_root: Path,
    features: Mapping[str, PublicFeature],
    implementations: Mapping[str, FeatureImplementation],
    package_bindings: Mapping[str, PackageBinding],
) -> tuple[list[_PayloadNode], dict[str, tuple[PayloadEntry, ...]]]:
    resource_owners: dict[tuple[str, str], str] = {}
    target_owners: list[tuple[PurePosixPath, str]] = []
    payload_nodes: dict[str, _PayloadNode] = {}
    entries: dict[str, list[PayloadEntry]] = {feature_id: [] for feature_id in features}

    for feature_id in sorted(features):
        implementation = implementations[feature_id]
        if not implementation.available:
            owned_values = (
                implementation.package_requirements
                or implementation.tools
                or implementation.files
                or implementation.repositories
                or implementation.user_units
                or implementation.system_units
                or implementation.authentication
                or implementation.theme
                or implementation.github_ssh_user
                or implementation.firewall_rule
                or implementation.monitor_profiles
                or implementation.default_agent_target
            )
            if owned_values:
                raise CatalogError(f"unavailable implementation owns actions: {feature_id}")
            continue
        for kind, values in (
            ("package requirement", implementation.package_requirements),
            ("tool", implementation.tools),
        ):
            for value in values:
                if kind != "tool" and not IDENTIFIER_RE.fullmatch(value):
                    raise CatalogError(f"unsafe {kind} name in {feature_id}: {value}")
                if kind == "tool" and not TOOL_RE.fullmatch(value):
                    raise CatalogError(f"moving tool reference in {feature_id}: {value}")
                key = (kind, value)
                previous = resource_owners.get(key)
                if previous is not None:
                    raise CatalogError(
                        f"{kind} {value} is owned by both {previous} and {feature_id}"
                    )
                resource_owners[key] = feature_id

        for file_spec in implementation.files:
            source_bundle = file_spec.source_bundle or implementation.bundle
            if implementation.bundle == "common" and source_bundle != "common":
                raise CatalogError(f"common implementation cannot read {source_bundle} payload: {feature_id}")
            if source_bundle not in {"common", implementation.bundle}:
                raise CatalogError(f"invalid source bundle in {feature_id}: {source_bundle}")
            bundle_root = common_root if source_bundle == "common" else platform_root
            source = _confined_source(bundle_root, file_spec.source, feature_id)
            target = _target(file_spec.target)
            nodes = _payload_nodes(source, repository_root)
            if not nodes and not source.is_dir():
                raise CatalogError(f"source has no installable payload: {file_spec.source}")
            for node, relative in nodes:
                owned_target = target / relative if relative.parts else target
                if node.kind == "symlink":
                    _validate_installed_symlink(
                        owned_target, os.fsdecode(node.content), feature_id
                    )
                _claim_target(owned_target, feature_id, target_owners)
                payload_nodes[node.relative_path] = node
                symlink = os.fsdecode(node.content) if node.kind == "symlink" else None
                digest_content = (
                    f"symlink:{symlink}".encode() if symlink is not None else node.content
                )
                entries[feature_id].append(
                    PayloadEntry(
                        source=node.relative_path,
                        target=owned_target.as_posix(),
                        sha256=hashlib.sha256(digest_content).hexdigest(),
                        mode=node.path.lstat().st_mode & 0o777,
                        symlink=symlink,
                    )
                )

        for repository in implementation.repositories:
            if not repository.url.startswith("https://"):
                raise CatalogError(
                    f"repository URL must use HTTPS in {feature_id}: {repository.url}"
                )
            if not GIT_COMMIT_RE.fullmatch(repository.revision):
                raise CatalogError(
                    f"moving Git reference in {feature_id}: {repository.revision}"
                )
            _claim_target(_target(repository.target), feature_id, target_owners)

        for unit in implementation.user_units:
            if not re.fullmatch(
                r"[A-Za-z0-9@_.:-]+\.(?:service|target|timer|socket|path|mount|automount)",
                unit,
            ):
                raise CatalogError(f"unsafe user unit name in {feature_id}: {unit}")
        for unit in implementation.system_units:
            if unit not in SYSTEM_UNIT_ALLOWLIST:
                raise CatalogError(f"system unit is not allowlisted in {feature_id}: {unit}")
        if implementation.default_agent_target is not None:
            _claim_target(_target(implementation.default_agent_target), feature_id, target_owners)
        if implementation.firewall_rule not in {None, "ssh-limit"}:
            raise CatalogError(f"unknown firewall rule in {feature_id}: {implementation.firewall_rule}")

    required_packages = {
        requirement
        for implementation in implementations.values()
        if implementation.available
        for requirement in implementation.package_requirements
    }
    missing_bindings = required_packages - set(package_bindings)
    unused_bindings = set(package_bindings) - required_packages
    if missing_bindings:
        raise CatalogError("missing package binding: " + ", ".join(sorted(missing_bindings)))
    if unused_bindings:
        raise CatalogError("unused package binding: " + ", ".join(sorted(unused_bindings)))

    return (
        [payload_nodes[key] for key in sorted(payload_nodes)],
        {key: tuple(sorted(value, key=lambda item: item.target)) for key, value in sorted(entries.items())},
    )


def _confined_source(bundle_root: Path, source: str, feature_id: str) -> Path:
    source_path = PurePosixPath(source)
    if source_path.is_absolute() or not source_path.parts or ".." in source_path.parts:
        raise CatalogError(f"unsafe source in {feature_id}: {source}")
    candidate = bundle_root.joinpath(*source_path.parts)
    if not os.path.lexists(candidate):
        raise CatalogError(f"missing source in {feature_id}: {source}")
    return candidate


def _payload_nodes(
    source: Path, repository_root: Path
) -> list[tuple[_PayloadNode, PurePosixPath]]:
    result: list[tuple[_PayloadNode, PurePosixPath]] = []
    source_is_directory = source.is_dir() and not source.is_symlink()

    def walk(path: Path) -> None:
        metadata = path.lstat()
        relative = path.relative_to(source) if source_is_directory else Path()
        target_relative = PurePosixPath(relative.as_posix())
        repository_relative = path.relative_to(repository_root).as_posix()
        if stat.S_ISLNK(metadata.st_mode):
            link_target = os.readlink(path)
            result.append(
                (
                    _PayloadNode(path, repository_relative, "symlink", os.fsencode(link_target)),
                    target_relative,
                )
            )
        elif stat.S_ISREG(metadata.st_mode):
            result.append(
                (_PayloadNode(path, repository_relative, "file", path.read_bytes()), target_relative)
            )
        elif stat.S_ISDIR(metadata.st_mode):
            for child in sorted(path.iterdir(), key=lambda item: item.name):
                walk(child)
        else:
            raise CatalogError(f"unsupported payload node: {repository_relative}")

    walk(source)
    return result


def _target(value: str) -> PurePosixPath:
    target = PurePosixPath(value)
    if target.is_absolute() or ".." in target.parts:
        raise CatalogError(f"unsafe target path: {value}")
    return target


def _claim_target(
    target: PurePosixPath,
    feature_id: str,
    owners: list[tuple[PurePosixPath, str]],
) -> None:
    if target == PurePosixPath("."):
        raise CatalogError(f"unsafe target path for file owned by {feature_id}: .")
    for owned, owner in owners:
        if target == owned or target in owned.parents or owned in target.parents:
            raise CatalogError(
                f"target ownership conflict: {owner}:{owned} and {feature_id}:{target}"
            )
    owners.append((target, feature_id))


def _validate_listening_service_defaults(
    features: Mapping[str, PublicFeature],
    implementations: Mapping[str, FeatureImplementation],
) -> None:
    listening = {
        feature_id
        for feature_id, implementation in implementations.items()
        if implementation.opens_listening_port
    }
    hidden = sorted(feature_id for feature_id in listening if not features[feature_id].visible)
    if hidden:
        raise CatalogError("listening service must be visible: " + ", ".join(hidden))

    closure: set[str] = set()

    def include(feature_id: str) -> None:
        if feature_id in closure:
            return
        closure.add(feature_id)
        for dependency in features[feature_id].requires:
            include(dependency)

    for feature in features.values():
        if feature.default:
            include(feature.id)
    unsafe = sorted(listening & closure)
    if unsafe:
        raise CatalogError(
            "listening service is in the default dependency closure: " + ", ".join(unsafe)
        )


def _validate_common_purity(manifests: list[_Manifest]) -> None:
    for manifest in manifests:
        _reject_platform_reference(manifest.relative_path, manifest.content)


def _validate_common_payload_purity(nodes: list[_PayloadNode], common_root: Path) -> None:
    common_prefix = common_root.as_posix().rstrip("/") + "/"
    for node in nodes:
        if node.path.as_posix().startswith(common_prefix):
            _reject_platform_reference(node.relative_path, node.content)


def _reject_platform_reference(label: str, content: bytes) -> None:
    if COMMON_PLATFORM_REFERENCE_RE.search(content) or _platform_name_in_path(label):
        raise CatalogError(f"platform-specific reference in common source: {label}")


def _platform_name_in_path(value: str) -> bool:
    parts = PurePosixPath(value).parts
    return any(part.lower().startswith("omarchy-") for part in parts) or any(
        parts[index : index + 2] == (".config", "omarchy")
        for index in range(len(parts) - 1)
    )


def _source_digest(
    platform: PlatformId,
    manifests: list[_Manifest],
    payload_nodes: list[_PayloadNode],
) -> str:
    digest = hashlib.sha256()

    def add(kind: str, path: str, content: bytes) -> None:
        for part in (kind.encode(), path.encode(), content):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)

    add("platform", platform.value, platform.value.encode())
    for manifest in sorted(manifests, key=lambda item: item.relative_path):
        add("manifest", manifest.relative_path, manifest.content)
    for node in payload_nodes:
        add(node.kind, node.relative_path, node.content)
    return digest.hexdigest()


def _schema_two(raw: Mapping[str, object], allowed: set[str], path: Path) -> None:
    schema = raw.get("schema")
    if isinstance(schema, bool) or schema != 2:
        raise CatalogError(f"manifest must use schema 2: {path}")
    unknown = set(raw) - allowed
    if unknown:
        raise CatalogError(f"unknown manifest fields in {path}: {', '.join(sorted(unknown))}")


def _matching_filename(identifier: str, path: Path) -> None:
    if path.stem != identifier:
        raise CatalogError(f"manifest id does not match filename: {path}")


def _identifier(raw: Mapping[str, object], key: str, path: Path) -> str:
    value = _string(raw, key, path)
    if not IDENTIFIER_RE.fullmatch(value):
        raise CatalogError(f"invalid {key} in {path}: {value!r}")
    return value


def _string(raw: Mapping[str, object], key: str, path: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise CatalogError(f"{key} must be a non-empty string in {path}")
    return value


def _optional_string(
    raw: Mapping[str, object], key: str, default: str, path: Path
) -> str:
    if key not in raw:
        return default
    return _string(raw, key, path)


def _optional_nullable_string(
    raw: Mapping[str, object], key: str, path: Path
) -> str | None:
    if key not in raw:
        return None
    return _string(raw, key, path)


def _boolean(raw: Mapping[str, object], key: str, default: bool, path: Path) -> bool:
    if key not in raw:
        return default
    value = raw[key]
    if not isinstance(value, bool):
        raise CatalogError(f"{key} must be a boolean in {path}")
    return value


def _strings(raw: Mapping[str, object], key: str, path: Path) -> tuple[str, ...]:
    if key not in raw:
        return ()
    value = raw[key]
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise CatalogError(f"{key} must be an array of non-empty strings in {path}")
    if len(set(value)) != len(value):
        raise CatalogError(f"{key} contains duplicates in {path}")
    return tuple(value)


def _tables(
    raw: Mapping[str, object], key: str, path: Path
) -> tuple[Mapping[str, object], ...]:
    if key not in raw:
        return ()
    value = raw[key]
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise CatalogError(f"{key} must be an array of tables in {path}")
    return tuple(value)


def _table_string(item: Mapping[str, object], key: str, path: Path) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        raise CatalogError(f"{key} must be a non-empty string in {path}")
    return value


def _table_optional_string(
    item: Mapping[str, object], key: str, path: Path
) -> str | None:
    if key not in item:
        return None
    return _table_string(item, key, path)


def _table_strings(
    item: Mapping[str, object], key: str, path: Path
) -> tuple[str, ...]:
    if key not in item:
        return ()
    value = item[key]
    if not isinstance(value, list) or any(not isinstance(entry, str) or not entry for entry in value):
        raise CatalogError(f"{key} must be an array of non-empty strings in {path}")
    if len(set(value)) != len(value):
        raise CatalogError(f"{key} contains duplicates in {path}")
    return tuple(value)


def _file_table(item: Mapping[str, object], path: Path) -> tuple[str, str, str | None]:
    _table_fields(item, {"source", "target"}, {"bundle"}, "files", path)
    bundle = item.get("bundle")
    if bundle is not None and bundle not in {"common", "omarchy"}:
        raise CatalogError(f"invalid files bundle in {path}: {bundle!r}")
    return (
        _table_string(item, "source", path),
        _table_string(item, "target", path),
        bundle,
    )


def _repository_table(item: Mapping[str, object], path: Path) -> tuple[str, str, str]:
    _table_fields(item, {"url", "revision", "target"}, set(), "repositories", path)
    return (
        _table_string(item, "url", path),
        _table_string(item, "revision", path),
        _table_string(item, "target", path),
    )


def _authentication_table(
    item: Mapping[str, object], path: Path
) -> tuple[str, tuple[str, ...], tuple[str, ...], str | None]:
    _table_fields(
        item,
        {"label", "command", "probe"},
        {"probe_contains"},
        "authentication",
        path,
    )
    command = _table_argv(item, "command", path)
    probe = _table_argv(item, "probe", path)
    contains = item.get("probe_contains")
    if contains is not None and (not isinstance(contains, str) or not contains):
        raise CatalogError(f"probe_contains must be a non-empty string in {path}")
    return _table_string(item, "label", path), command, probe, contains


def _table_argv(item: Mapping[str, object], key: str, path: Path) -> tuple[str, ...]:
    value = item.get(key)
    if not isinstance(value, list) or not value or any(
        not isinstance(part, str) or not part or "\x00" in part for part in value
    ):
        raise CatalogError(f"{key} must be a non-empty argv array in {path}")
    return tuple(value)


def _table_fields(
    item: Mapping[str, object], required: set[str], optional: set[str], label: str, path: Path
) -> None:
    unknown = set(item) - required - optional
    missing = required - set(item)
    if unknown:
        raise CatalogError(f"unknown {label} fields in {path}: {', '.join(sorted(unknown))}")
    if missing:
        raise CatalogError(f"missing {label} fields in {path}: {', '.join(sorted(missing))}")


def _validate_installed_symlink(target: PurePosixPath, link: str, feature_id: str) -> None:
    link_path = PurePosixPath(link)
    if link_path.is_absolute() or "\x00" in link:
        raise CatalogError(f"unsafe payload symlink in {feature_id}: {target} -> {link}")
    installed = posixpath.normpath((target.parent / link_path).as_posix())
    if installed == ".." or installed.startswith("../") or installed.startswith("/"):
        raise CatalogError(
            f"payload symlink escapes target home in {feature_id}: {target} -> {link}"
        )


def _ports(raw: Mapping[str, object], path: Path) -> tuple[int, ...]:
    if "listening_ports" not in raw:
        return ()
    value = raw["listening_ports"]
    if not isinstance(value, list) or any(
        isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535
        for port in value
    ):
        raise CatalogError(f"listening_ports must contain valid ports in {path}")
    if len(set(value)) != len(value):
        raise CatalogError(f"listening_ports contains duplicates in {path}")
    return tuple(value)


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
