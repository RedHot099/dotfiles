from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Iterable


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class FileSpec:
    source: str
    target: str


@dataclass(frozen=True)
class AuthSpec:
    label: str
    command: str
    probe: str
    probe_contains: str | None


@dataclass(frozen=True)
class RepositorySpec:
    url: str
    revision: str
    target: str


@dataclass(frozen=True)
class Feature:
    id: str
    label: str
    description: str
    group: str
    default: bool
    visible: bool
    requires: tuple[str, ...]
    packages: tuple[str, ...]
    aur: tuple[str, ...]
    mise: tuple[str, ...]
    commands: tuple[str, ...]
    files: tuple[FileSpec, ...]
    reload_systemd: bool
    units: tuple[str, ...]
    auth: tuple[AuthSpec, ...]
    repositories: tuple[RepositorySpec, ...]
    theme: str | None

    def with_id(self, feature_id: str) -> "Feature":
        return replace(self, id=feature_id)


@dataclass(frozen=True)
class MachineFacts:
    omarchy_major: int
    packages: frozenset[str]
    commands: frozenset[str]


@dataclass(frozen=True)
class Action:
    id: str
    kind: str
    feature: str
    data: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "kind": self.kind, "feature": self.feature, "data": self.data}

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "Action":
        return cls(str(value["id"]), str(value["kind"]), str(value["feature"]), dict(value["data"]))


@dataclass(frozen=True)
class ExecutionPlan:
    schema: int
    omarchy_major: int
    target_home: str
    hardware: str
    selected: tuple[str, ...]
    dependencies: dict[str, tuple[str, ...]]
    default_agent: str
    actions: tuple[Action, ...]
    digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "omarchy_major": self.omarchy_major,
            "target_home": self.target_home,
            "hardware": self.hardware,
            "selected": list(self.selected),
            "dependencies": {key: list(value) for key, value in sorted(self.dependencies.items())},
            "default_agent": self.default_agent,
            "actions": [action.to_dict() for action in self.actions],
            "digest": self.digest,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "ExecutionPlan":
        return cls(
            schema=int(value["schema"]),
            omarchy_major=int(value["omarchy_major"]),
            target_home=str(value["target_home"]),
            hardware=str(value["hardware"]),
            selected=tuple(str(item) for item in value["selected"]),
            dependencies={str(key): tuple(str(item) for item in items) for key, items in dict(value["dependencies"]).items()},
            default_agent=str(value["default_agent"]),
            actions=tuple(Action.from_dict(item) for item in value["actions"]),
            digest=str(value["digest"]),
        )


@dataclass(frozen=True)
class ApplyResult:
    changed: int
    unchanged: int
    simulated: int
    skipped_features: tuple[str, ...]


@dataclass(frozen=True)
class AuditFinding:
    status: str
    kind: str
    feature: str
    message: str


def load_catalog(features_dir: Path) -> dict[str, Feature]:
    features: dict[str, Feature] = {}
    for path in sorted(features_dir.glob("*/feature.toml")):
        with path.open("rb") as stream:
            raw = tomllib.load(stream)
        feature = Feature(
            id=_required_string(raw, "id", path),
            label=_required_string(raw, "label", path),
            description=_required_string(raw, "description", path),
            group=str(raw.get("group", "Other")),
            default=bool(raw.get("default", False)),
            visible=bool(raw.get("visible", True)),
            requires=_strings(raw.get("requires", []), path, "requires"),
            packages=_strings(raw.get("packages", []), path, "packages"),
            aur=_strings(raw.get("aur", []), path, "aur"),
            mise=_strings(raw.get("mise", []), path, "mise"),
            commands=_strings(raw.get("commands", []), path, "commands"),
            files=tuple(FileSpec(_required_string(item, "source", path), _required_string(item, "target", path)) for item in raw.get("files", [])),
            reload_systemd=bool(raw.get("reload_systemd", False)),
            units=_strings(raw.get("units", []), path, "units"),
            auth=tuple(AuthSpec(_required_string(item, "label", path), _required_string(item, "command", path), _required_string(item, "probe", path), str(item["probe_contains"]) if "probe_contains" in item else None) for item in raw.get("auth", [])),
            repositories=tuple(RepositorySpec(_required_string(item, "url", path), _required_string(item, "revision", path), _required_string(item, "target", path)) for item in raw.get("repositories", [])),
            theme=str(raw["theme"]) if "theme" in raw else None,
        )
        if feature.id in features:
            raise CatalogError(f"duplicate feature id: {feature.id}")
        features[feature.id] = feature
    if not features:
        raise CatalogError(f"no features found in {features_dir}")
    for feature in features.values():
        missing = set(feature.requires) - features.keys()
        if missing:
            raise CatalogError(f"{feature.id} requires unknown features: {', '.join(sorted(missing))}")
    return features


def load_profiles(profiles_dir: Path) -> dict[str, tuple[str, ...]]:
    profiles: dict[str, tuple[str, ...]] = {}
    for path in sorted(profiles_dir.glob("*.toml")):
        with path.open("rb") as stream:
            raw = tomllib.load(stream)
        profile_id = _required_string(raw, "id", path)
        profiles[profile_id] = _strings(raw.get("features", []), path, "features")
    return profiles


def resolve_features(features: dict[str, Feature], requested: set[str]) -> tuple[str, ...]:
    unknown = requested - features.keys()
    if unknown:
        raise CatalogError(f"unknown features: {', '.join(sorted(unknown))}")
    resolved: set[str] = set()
    visiting: set[str] = set()

    def visit(feature_id: str) -> None:
        if feature_id in resolved:
            return
        if feature_id in visiting:
            raise CatalogError(f"dependency cycle at {feature_id}")
        visiting.add(feature_id)
        for dependency in features[feature_id].requires:
            visit(dependency)
        visiting.remove(feature_id)
        resolved.add(feature_id)

    for feature_id in sorted(requested):
        visit(feature_id)
    return tuple(sorted(resolved))


def build_plan(
    root: Path,
    features: dict[str, Feature],
    requested: set[str],
    hardware: str,
    target_home: Path,
    facts: MachineFacts,
    default_agent: str = "claude",
    monitor_content: str | None = None,
) -> ExecutionPlan:
    if facts.omarchy_major != 4:
        raise CatalogError(f"Omarchy 4 is required, found major version {facts.omarchy_major}")
    if default_agent not in {"claude", "codex", "opencode"}:
        raise CatalogError(f"unsupported default agent: {default_agent}")
    selected = resolve_features(features, requested)
    actions: list[Action] = []
    path_owners: dict[str, str] = {}
    for feature_id in selected:
        feature = features[feature_id]
        missing_packages = tuple(package for package in feature.packages if package not in facts.packages)
        missing_aur = tuple(package for package in feature.aur if package not in facts.packages)
        if missing_packages:
            actions.append(_action("packages", feature_id, {"packages": list(missing_packages)}))
        if missing_aur:
            actions.append(_action("aur", feature_id, {"packages": list(missing_aur)}))
        if feature.mise:
            actions.append(_action("mise", feature_id, {"tools": list(feature.mise), "commands": list(feature.commands)}))
        for spec in feature.files:
            actions.extend(_file_actions(root, feature_id, spec, path_owners))
        if feature.reload_systemd:
            actions.append(_action("daemon-reload", feature_id, {}))
        for unit in feature.units:
            actions.append(_action("unit", feature_id, {"name": unit, "auth_probes": [{"command": auth.probe, "contains": auth.probe_contains} for auth in feature.auth]}))
        for repository in feature.repositories:
            _claim_path(path_owners, repository.target, feature_id)
            actions.append(_action("git", feature_id, {"url": repository.url, "revision": repository.revision, "target": repository.target}))
        if feature.theme:
            actions.append(_action("theme", feature_id, {"name": feature.theme}))
        for auth in feature.auth:
            actions.append(_action("auth", feature_id, {"label": auth.label, "command": auth.command, "probe": auth.probe, "probe_contains": auth.probe_contains}))
    if "core-desktop" in selected:
        monitor_source = root / "payload" / "hardware" / hardware / ".config" / "hypr" / "monitors.lua"
        if monitor_content is None:
            if not monitor_source.is_file():
                raise CatalogError(f"unknown hardware profile: {hardware}")
            monitor_data = {"source": str(monitor_source.relative_to(root)), "target": ".config/hypr/monitors.lua", "sha256": _hash_file(monitor_source), "mode": monitor_source.stat().st_mode & 0o777}
        else:
            monitor_data = {"content": monitor_content, "target": ".config/hypr/monitors.lua", "sha256": _hash_bytes(monitor_content.encode()), "mode": 0o644}
        _claim_path(path_owners, str(monitor_data["target"]), "hardware")
        actions.append(_action("file", "hardware", monitor_data))
    if "ai-development" in selected:
        agent_content = f"{default_agent}\n"
        agent_target = ".config/omarchy/defaults/agent"
        _claim_path(path_owners, agent_target, "ai-development")
        actions.append(_action("file", "ai-development", {"content": agent_content, "target": agent_target, "sha256": _hash_bytes(agent_content.encode()), "mode": 0o644}))
    actions.sort(key=lambda action: ({"packages": 0, "aur": 1, "mise": 2, "file": 3, "daemon-reload": 4, "git": 5, "theme": 6, "auth": 7, "unit": 8}[action.kind], action.feature, action.id))
    body = {
        "schema": 1,
        "omarchy_major": 4,
        "target_home": str(target_home.resolve()),
        "hardware": hardware,
        "selected": list(selected),
        "dependencies": {feature_id: list(features[feature_id].requires) for feature_id in selected},
        "default_agent": default_agent,
        "actions": [action.to_dict() for action in actions],
    }
    digest = _hash_bytes(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
    return ExecutionPlan(1, 4, body["target_home"], hardware, selected, {key: tuple(value) for key, value in body["dependencies"].items()}, default_agent, tuple(actions), digest)


def detect_machine(features: Iterable[Feature]) -> MachineFacts:
    version = _capture(["omarchy", "version"])
    try:
        major = int(version.split(".", 1)[0])
    except (ValueError, IndexError) as error:
        raise CatalogError(f"cannot parse Omarchy version: {version!r}") from error
    packages = frozenset(_capture(["pacman", "-Qq"]).splitlines()) if shutil.which("pacman") else frozenset()
    wanted = {command for feature in features for command in feature.commands}
    commands = frozenset(command for command in wanted if shutil.which(command))
    return MachineFacts(major, packages, commands)


def apply_plan(root: Path, plan: ExecutionPlan, system_changes: bool, interactive: bool = False) -> ApplyResult:
    _validate_plan(plan)
    target_home = Path(plan.target_home)
    journal_path = target_home / ".local" / "state" / "omarchy-bootstrap" / f"{plan.digest}.json"
    journal = _read_json(journal_path, {"completed": [], "skipped_features": []})
    completed = set(journal["completed"])
    skipped_features = set(journal["skipped_features"])
    changed = unchanged = simulated = 0
    systemd_files_changed = False
    for action in plan.actions:
        if action.feature in skipped_features:
            continue
        try:
            if action.kind == "file":
                did_change = _apply_file(root, target_home, plan.digest, action)
                changed += int(did_change)
                unchanged += int(not did_change)
                systemd_files_changed = systemd_files_changed or (
                    did_change and str(action.data["target"]).startswith(".config/systemd/user/")
                )
            elif not system_changes:
                simulated += 1
                continue
            elif action.kind == "unit" and not all(_probe(str(probe["command"]), _optional_string(probe.get("contains"))) for probe in action.data.get("auth_probes", [])):
                simulated += 1
                continue
            elif action.kind == "daemon-reload":
                if action.id in completed and not systemd_files_changed:
                    unchanged += 1
                else:
                    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
                    changed += 1
            elif _action_satisfied(action):
                unchanged += 1
            elif action.kind == "packages":
                subprocess.run(["omarchy", "pkg", "add", *action.data["packages"]], check=True)
                changed += 1
            elif action.kind == "aur":
                subprocess.run(["omarchy", "pkg", "aur", "add", *action.data["packages"]], check=True)
                changed += 1
            elif action.kind == "mise":
                subprocess.run(["mise", "use", "-g", *action.data["tools"]], check=True)
                changed += 1
            elif action.kind == "unit":
                subprocess.run(["systemctl", "--user", "enable", "--now", str(action.data["name"])], check=True)
                changed += 1
            elif action.kind == "git":
                _apply_repository(target_home, action)
                changed += 1
            elif action.kind == "theme":
                environment = dict(os.environ, HOME=str(target_home), OMARCHY_THEME_HEADLESS="1")
                subprocess.run(["omarchy", "theme", "set", str(action.data["name"])], check=True, env=environment)
                changed += 1
            elif action.kind == "auth":
                if _probe(str(action.data["probe"]), _optional_string(action.data.get("probe_contains"))):
                    unchanged += 1
                elif interactive:
                    subprocess.run(shlex.split(str(action.data["command"])), check=True)
                    if not _probe(str(action.data["probe"]), _optional_string(action.data.get("probe_contains"))):
                        raise RuntimeError(f"authentication did not pass: {action.data['label']}")
                    changed += 1
                else:
                    simulated += 1
                    continue
            completed.add(action.id)
        except (OSError, subprocess.CalledProcessError, RuntimeError) as error:
            decision = _failure_decision(action, error) if interactive else "Abort"
            if decision == "Retry":
                return apply_plan(root, plan, system_changes, interactive)
            if decision == "Skip feature":
                skipped_features.update(_skip_closure(plan, action.feature))
            else:
                raise
        _write_json_if_changed(journal_path, {"completed": sorted(completed), "skipped_features": sorted(skipped_features)})
    return ApplyResult(changed, unchanged, simulated, tuple(sorted(skipped_features)))


def audit_plan(root: Path, plan: ExecutionPlan, facts: MachineFacts | None = None) -> tuple[AuditFinding, ...]:
    _validate_plan(plan)
    if facts is None:
        facts = detect_machine(load_catalog(root / "features").values())
    findings: list[AuditFinding] = []
    target_home = Path(plan.target_home)
    isolated = target_home.resolve() != Path.home().resolve()
    for action in plan.actions:
        if action.kind == "file":
            target = _target_path(target_home, str(action.data["target"]))
            actual = _hash_path(target) if target.exists() or target.is_symlink() else None
            expected = str(action.data["sha256"])
            status = "PASS" if actual == expected else "FAIL"
            findings.append(AuditFinding(status, "file", action.feature, f"{action.data['target']}: {'matches' if status == 'PASS' else 'missing or changed'}"))
        elif action.kind in {"packages", "aur"}:
            missing = sorted(set(action.data["packages"]) - facts.packages)
            status = "WARN" if missing and isolated else "FAIL" if missing else "PASS"
            findings.append(AuditFinding(status, action.kind, action.feature, "packages present" if not missing else f"missing packages: {', '.join(missing)}"))
        elif action.kind == "mise":
            missing = [str(tool) for tool in action.data["tools"] if not _mise_satisfied(str(tool))]
            status = "WARN" if missing and isolated else "FAIL" if missing else "PASS"
            findings.append(AuditFinding(status, "mise", action.feature, "tools present" if not missing else f"missing tools: {', '.join(missing)}"))
        elif action.kind == "unit":
            auth_ready = all(_probe(str(probe["command"]), _optional_string(probe.get("contains"))) for probe in action.data.get("auth_probes", []))
            enabled = subprocess.run(["systemctl", "--user", "is-enabled", str(action.data["name"])], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
            status = "WARN" if not auth_ready else "PASS" if enabled else "WARN" if isolated else "FAIL"
            detail = "waiting for manual authentication" if not auth_ready else "enabled" if enabled else "not enabled"
            findings.append(AuditFinding(status, "unit", action.feature, f"{action.data['name']}: {detail}"))
        elif action.kind == "git":
            target = _target_path(target_home, str(action.data["target"]))
            current = _git_output(target, "rev-parse", "HEAD")
            remote = _git_output(target, "remote", "get-url", "origin")
            matches = current == action.data["revision"] and remote == action.data["url"]
            status = "PASS" if matches else "WARN" if isolated else "FAIL"
            findings.append(AuditFinding(status, "git", action.feature, f"{action.data['target']}: {'pinned revision present' if matches else 'missing or at another revision'}"))
        elif action.kind == "theme":
            name_file = target_home / ".local" / "state" / "omarchy" / "current" / "theme.name"
            current = name_file.read_text().strip() if name_file.is_file() else ""
            expected = str(action.data["name"])
            status = "PASS" if current == expected else "WARN" if isolated else "FAIL"
            findings.append(AuditFinding(status, "theme", action.feature, f"theme: {current or 'unset'}; expected {expected}"))
        elif action.kind == "auth":
            authenticated = _probe(str(action.data["probe"]), _optional_string(action.data.get("probe_contains")))
            findings.append(AuditFinding("PASS" if authenticated else "WARN", "auth", action.feature, f"{action.data['label']}: {'authenticated' if authenticated else 'manual login required'}"))
    return tuple(findings)


def _file_actions(root: Path, feature_id: str, spec: FileSpec, owners: dict[str, str]) -> list[Action]:
    source = (root / spec.source).resolve()
    if not source.exists() and not source.is_symlink():
        raise CatalogError(f"missing payload for {feature_id}: {spec.source}")
    files = [source] if not source.is_dir() else sorted(path for path in source.rglob("*") if path.is_file() or path.is_symlink())
    actions: list[Action] = []
    for path in files:
        suffix = Path() if not source.is_dir() else path.relative_to(source)
        target = str((PurePosixPath(spec.target) / PurePosixPath(suffix.as_posix())).as_posix())
        target = target.removeprefix("./")
        _claim_path(owners, target, feature_id)
        actions.append(_action("file", feature_id, {"source": str(path.relative_to(root)), "target": target, "sha256": _hash_path(path), "mode": path.lstat().st_mode & 0o777, "symlink": os.readlink(path) if path.is_symlink() else None}))
    return actions


def _apply_file(root: Path, target_home: Path, plan_digest: str, action: Action) -> bool:
    target = _target_path(target_home, str(action.data["target"]))
    if _hash_path(target) == action.data["sha256"]:
        return False
    if target.exists() or target.is_symlink():
        backup = target_home / ".local" / "state" / "omarchy-bootstrap" / "backups" / plan_digest / str(action.data["target"])
        if not backup.exists() and not backup.is_symlink():
            backup.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                backup.symlink_to(os.readlink(target))
            else:
                shutil.copy2(target, backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.omarchy-bootstrap-tmp")
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    if action.data.get("symlink") is not None:
        temporary.symlink_to(str(action.data["symlink"]))
    elif "content" in action.data:
        temporary.write_text(str(action.data["content"]))
    else:
        shutil.copy2(root / str(action.data["source"]), temporary)
    if not temporary.is_symlink():
        temporary.chmod(int(action.data["mode"]))
    temporary.replace(target)
    return True


def _claim_path(owners: dict[str, str], target: str, feature_id: str) -> None:
    path = PurePosixPath(target)
    if path.is_absolute() or ".." in path.parts:
        raise CatalogError(f"unsafe target path: {target}")
    forbidden = {".config/waybar", ".config/mako", ".config/hypr/hypridle.conf", ".config/hypr/hyprlock.conf"}
    if any(path == PurePosixPath(item) or PurePosixPath(item) in path.parents for item in forbidden):
        raise CatalogError(f"legacy Omarchy target is forbidden: {target}")
    if target in owners:
        raise CatalogError(f"target {target} is owned by both {owners[target]} and {feature_id}")
    owners[target] = feature_id


def _action(kind: str, feature: str, data: dict[str, object]) -> Action:
    stable = json.dumps({"kind": kind, "feature": feature, "data": data}, sort_keys=True, separators=(",", ":"))
    return Action(_hash_bytes(stable.encode())[:16], kind, feature, data)


def _action_satisfied(action: Action) -> bool:
    if action.kind in {"packages", "aur"}:
        return all(subprocess.run(["pacman", "-Q", str(package)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0 for package in action.data["packages"])
    if action.kind == "mise":
        return all(_mise_satisfied(str(tool)) for tool in action.data["tools"])
    if action.kind == "unit":
        return subprocess.run(["systemctl", "--user", "is-enabled", str(action.data["name"])], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if action.kind == "git":
        target = _target_path(Path.home(), str(action.data["target"]))
        return _git_output(target, "rev-parse", "HEAD") == action.data["revision"] and _git_output(target, "remote", "get-url", "origin") == action.data["url"]
    if action.kind == "theme":
        name_file = Path.home() / ".local" / "state" / "omarchy" / "current" / "theme.name"
        return name_file.is_file() and name_file.read_text().strip() == action.data["name"]
    if action.kind == "auth":
        return _probe(str(action.data["probe"]), _optional_string(action.data.get("probe_contains")))
    return False


def _skip_closure(plan: ExecutionPlan, feature_id: str) -> set[str]:
    skipped = {feature_id}
    changed = True
    while changed:
        changed = False
        for candidate, dependencies in plan.dependencies.items():
            if candidate not in skipped and skipped.intersection(dependencies):
                skipped.add(candidate)
                changed = True
    return skipped


def _apply_repository(target_home: Path, action: Action) -> None:
    target = _target_path(target_home, str(action.data["target"]))
    url = str(action.data["url"])
    revision = str(action.data["revision"])
    if target.exists():
        if not (target / ".git").is_dir():
            raise RuntimeError(f"repository target exists and is not a git checkout: {target}")
        if _git_output(target, "status", "--porcelain"):
            raise RuntimeError(f"repository target has local changes: {target}")
        if _git_output(target, "remote", "get-url", "origin") != url:
            raise RuntimeError(f"repository remote differs: {target}")
        subprocess.run(["git", "-C", str(target), "fetch", "origin", revision], check=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", url, str(target)], check=True)
    subprocess.run(["git", "-C", str(target), "checkout", "--detach", revision], check=True)


def _git_output(target: Path, *args: str) -> str:
    if not (target / ".git").is_dir():
        return ""
    result = subprocess.run(["git", "-C", str(target), *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return result.stdout.strip() if result.returncode == 0 else ""


def _validate_plan(plan: ExecutionPlan) -> None:
    if plan.schema != 1 or plan.omarchy_major != 4:
        raise CatalogError("unsupported plan")
    body = plan.to_dict()
    body.pop("digest")
    expected = _hash_bytes(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
    if plan.digest != expected:
        raise CatalogError("plan digest does not match its contents")


def _target_path(home: Path, relative: str) -> Path:
    lexical = PurePosixPath(relative)
    if lexical.is_absolute() or ".." in lexical.parts:
        raise CatalogError(f"target escapes home: {relative}")
    resolved_home = home.resolve()
    parent = (resolved_home / lexical.parent).resolve(strict=False)
    if parent != resolved_home and resolved_home not in parent.parents:
        raise CatalogError(f"target parent escapes home: {relative}")
    return parent / lexical.name


def _hash_path(path: Path) -> str | None:
    if path.is_symlink():
        return _hash_bytes(f"symlink:{os.readlink(path)}".encode())
    if path.is_file():
        return _hash_file(path)
    return None


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _required_string(value: dict[str, object], key: str, path: Path) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise CatalogError(f"{path}: {key} must be a non-empty string")
    return result


def _strings(value: object, path: Path, key: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CatalogError(f"{path}: {key} must be a string array")
    return tuple(value)


def _capture(command: list[str]) -> str:
    return subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


def _probe(command: str, contains: str | None = None) -> bool:
    try:
        result = subprocess.run(shlex.split(command), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
        return result.returncode == 0 and (contains is None or contains.lower() in result.stdout.lower())
    except (OSError, subprocess.TimeoutExpired):
        return False


def _mise_satisfied(tool: str) -> bool:
    if not shutil.which("mise"):
        return False
    return subprocess.run(["mise", "where", tool], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _failure_decision(action: Action, error: Exception) -> str:
    if not shutil.which("gum"):
        return "Abort"
    prompt = f"{action.feature} failed: {error}"
    return subprocess.run(["gum", "choose", "--header", prompt, "Retry", "Skip feature", "Abort"], check=True, text=True, stdout=subprocess.PIPE).stdout.strip()


def _read_json(path: Path, fallback: dict[str, object]) -> dict[str, object]:
    if not path.is_file():
        return fallback
    return json.loads(path.read_text())


def _write_json_if_changed(path: Path, value: dict[str, object]) -> None:
    content = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if path.is_file() and path.read_text() == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(content)
    temporary.replace(path)
