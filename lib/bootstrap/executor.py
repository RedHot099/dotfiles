from __future__ import annotations

import fcntl
import base64
import hashlib
import json
import os
import pwd
import re
import secrets
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .catalog import CatalogError, SYSTEM_UNIT_ALLOWLIST, Workspace
from .domain import ActionKind, ExecutionPlan, PlannedAction, assert_plan_matches_host
from .files import FileBoundaryError, HomeFiles
from .tui.terminal import ask_yes_no
from .platform import PlatformFacts
from .packages import (
    LocalPackageProvider,
    bindings_from_action,
    clean_environment,
    clone_aur,
    installed_versions,
    recipe_from_action,
    snapshot_git_tree,
    transaction_from_action,
    verify_aur_snapshot,
    verify_transaction,
)


STATE_ROOT = ".local/state/arch-hypr-bootstrap"


@dataclass(frozen=True)
class ApplyResult:
    changed: int
    unchanged: int
    simulated: int
    skipped_features: tuple[str, ...]


def apply_install(
    root: Path,
    workspace: Workspace,
    plan: ExecutionPlan,
    facts: PlatformFacts,
    *,
    system_changes: bool,
    interactive: bool,
) -> ApplyResult:
    assert_plan_matches_host(plan, facts)
    if plan.workspace_digest != workspace.source_digest:
        raise CatalogError("workspace changed after planning; regenerate the plan")
    if workspace.platform != facts.platform:
        raise CatalogError("workspace platform differs from the host")
    if system_changes and os.geteuid() == 0:
        raise CatalogError("run bootstrap as the target user, not root")
    if system_changes and not interactive:
        raise CatalogError("real system changes require an interactive terminal")

    target_home = Path(plan.target_home)
    with HomeFiles(target_home) as home:
        home.ensure_directory(STATE_ROOT, 0o700)
        lock_descriptor = home.open_lock(f"{STATE_ROOT}/apply.lock")
        try:
            try:
                fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise CatalogError("another bootstrap apply is running") from error
            skipped = initialize_skipped_features(home)
            return _apply_locked(
                root,
                workspace,
                plan,
                facts,
                home,
                system_changes=system_changes,
                interactive=interactive,
                skipped=skipped,
            )
        finally:
            os.close(lock_descriptor)


def _apply_locked(
    root: Path,
    workspace: Workspace,
    plan: ExecutionPlan,
    facts: PlatformFacts,
    home: HomeFiles,
    *,
    system_changes: bool,
    interactive: bool,
    skipped: set[str],
) -> ApplyResult:
    environment = command_environment(plan.target_home)
    journal_target = f"{STATE_ROOT}/journals/{plan.digest}.json"
    journal = read_json(home.read_text(journal_target), {"completed": [], "skipped_features": []})
    completed = set(strings(journal.get("completed")))
    skipped.update(strings(journal.get("skipped_features")))
    if system_changes:
        review_aur_actions(plan, skipped)
        review_skill_collisions(plan, home)
        write_journal(home, journal_target, completed, skipped, plan.digest)
    sources = {
        (feature, entry.target, entry.sha256): entry
        for feature, entries in workspace.payload.items()
        for entry in entries
    }
    changed = unchanged = simulated = 0
    systemd_files_changed = False
    for item in plan.actions:
        if item.feature in skipped:
            continue
        action_id = action_digest(item)
        if item.kind in {ActionKind.USER_FILE, ActionKind.GENERATED_FILE}:
            did_change = apply_file_action(root, home, plan, item, sources)
            changed += int(did_change)
            unchanged += int(not did_change)
            systemd_files_changed |= did_change and str(item.data["target"]).startswith(
                ".config/systemd/user/"
            )
        elif not system_changes:
            simulated += 1
            continue
        elif item.kind is ActionKind.USER_DAEMON_RELOAD:
            if action_id in completed and not systemd_files_changed:
                unchanged += 1
            else:
                run(("/usr/bin/systemctl", "--user", "daemon-reload"))
                changed += 1
        elif item.kind is ActionKind.REPOSITORY_PACKAGES:
            did_change = apply_repository_packages(item, facts)
            changed += int(did_change)
            unchanged += int(not did_change)
        elif item.kind is ActionKind.AUR_BUILD:
            did_change = apply_aur_package(item)
            changed += int(did_change)
            unchanged += int(not did_change)
        elif action_satisfied(item, home, environment):
            unchanged += 1
        elif item.kind is ActionKind.PINNED_TOOL:
            run(("mise", "use", "-g", *strings(item.data["tools"])))
            changed += 1
        elif item.kind is ActionKind.USER_UNIT:
            probes = item.data.get("auth_probes", ())
            if not all(
                run_probe(
                    tuple(strings(probe["command"])),
                    optional_string(probe.get("contains")),
                    environment,
                )
                for probe in probes
            ):
                simulated += 1
                continue
            run(("/usr/bin/systemctl", "--user", "enable", "--now", str(item.data["name"])))
            changed += 1
        elif item.kind is ActionKind.SYSTEM_UNIT:
            name = str(item.data["name"])
            if name not in SYSTEM_UNIT_ALLOWLIST:
                raise CatalogError(f"system unit is not allowlisted: {name}")
            if name == "sshd.service":
                run(("/usr/bin/sudo", "/usr/bin/sshd", "-t"))
            run(("/usr/bin/sudo", "/usr/bin/systemctl", "enable", "--now", name))
            changed += 1
        elif item.kind is ActionKind.PINNED_GIT_ASSET:
            apply_repository(Path(plan.target_home), plan.digest, item)
            changed += 1
        elif item.kind is ActionKind.OMARCHY_THEME:
            theme_environment = dict(
                os.environ,
                HOME=plan.target_home,
                OMARCHY_THEME_HEADLESS="1",
            )
            run(
                ("omarchy", "theme", "set", str(item.data["name"])),
                environment=theme_environment,
            )
            changed += 1
        elif item.kind is ActionKind.MANUAL_AUTHENTICATION:
            if authenticate(item, environment):
                changed += 1
            else:
                simulated += 1
                continue
        elif item.kind is ActionKind.AUTHORIZED_SSH_KEYS:
            install_ssh(home, tuple(strings(item.data["keys"])))
            changed += 1
        elif item.kind is ActionKind.FIREWALL_RULE:
            if subprocess.run(
                ("/usr/bin/systemctl", "is-active", "ufw.service"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode:
                raise RuntimeError("UFW is not active; refusing to change firewall policy")
            run(("/usr/bin/sudo", "/usr/bin/ufw", "limit", "22/tcp"))
            changed += 1
        elif item.kind is ActionKind.HYPRLAND_RELOAD:
            if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
                simulated += 1
                continue
            run(("/usr/bin/hyprctl", "reload"), environment=environment)
            errors = capture(("/usr/bin/hyprctl", "configerrors"), environment=environment).strip()
            if errors:
                raise RuntimeError(f"Hyprland configuration errors after reload:\n{errors}")
            changed += 1
        else:
            raise CatalogError(f"executor does not implement action: {item.kind.value}")
        completed.add(action_id)
        write_journal(home, journal_target, completed, skipped, plan.digest)
    return ApplyResult(changed, unchanged, simulated, tuple(sorted(skipped)))


def review_aur_actions(plan: ExecutionPlan, skipped: set[str]) -> None:
    for item in plan.actions:
        if item.kind is not ActionKind.AUR_BUILD or item.feature in skipped:
            continue
        if aur_installed_exact(item):
            continue
        recipe = recipe_from_action(dict(item.data))
        print(
            f"\nAUR review: {recipe.package_base} {recipe.version} "
            f"at {item.data['commit']}"
        )
        for path, digest, encoded in recipe.files:
            content = base64.b64decode(encoded, validate=True)
            print(f"\n--- {path} (sha256 {digest}) ---")
            try:
                print(content.decode("utf-8"), end="" if content.endswith(b"\n") else "\n")
            except UnicodeDecodeError:
                print(f"[binary file, {len(content)} bytes]")
        if not ask_yes_no(f"Build and install reviewed AUR package {recipe.package_base}?"):
            skipped.update(dependent_feature_closure(plan, item.feature))


def review_skill_collisions(plan: ExecutionPlan, home: HomeFiles) -> None:
    collisions: list[str] = []
    for item in plan.actions:
        if item.feature != "user-skills" or item.kind is not ActionKind.USER_FILE:
            continue
        target = str(item.data["target"])
        kind = home.target_kind(target)
        if kind is None:
            continue
        try:
            matches = home.matches(
                target,
                str(item.data["sha256"]),
                integer(item.data["mode"]),
                optional_string(item.data.get("symlink")),
            )
        except FileBoundaryError:
            matches = False
        if not matches:
            collisions.append(target)
    if not collisions:
        return
    print("\nSkill paths that will be replaced without backup:")
    for target in sorted(collisions):
        print(f"  {target}")
    if not ask_yes_no("Replace exactly these selected skill paths?"):
        raise CatalogError("skill collision replacement was declined")
    for target in collisions:
        home.remove_exact(target)


def dependent_feature_closure(plan: ExecutionPlan, feature: str) -> set[str]:
    result = {feature}
    changed = True
    while changed:
        changed = False
        for candidate, dependencies in plan.dependencies.items():
            if candidate not in result and result.intersection(dependencies):
                result.add(candidate)
                changed = True
    return result


def apply_repository_packages(item: PlannedAction, facts: PlatformFacts) -> bool:
    planned = transaction_from_action(dict(item.data))
    bindings = bindings_from_action(dict(item.data))
    provider = LocalPackageProvider(facts.repositories)
    current = provider.resolve_repository(bindings)
    versions = installed_versions(package.name for package in planned)
    verify_transaction(planned, current, versions)
    direct = tuple(strings(item.data["packages"]))
    planned_versions = {package.name: package.version for package in planned}
    if all(versions.get(package) == planned_versions[package] for package in direct):
        return False
    print("Repository transaction:")
    for package in planned:
        print(f"  {package.repository}/{package.name} {package.version}")
    run(("/usr/bin/sudo", "/usr/bin/pacman", "-S", "--needed", "--", *direct))
    installed = installed_versions(direct)
    if any(installed.get(package) != planned_versions[package] for package in direct):
        raise CatalogError("repository package postcondition failed")
    return True


def apply_aur_package(item: PlannedAction) -> bool:
    if aur_installed_exact(item):
        return False
    recipe = recipe_from_action(dict(item.data))
    url = str(item.data["url"])
    revision = str(item.data["commit"])
    with tempfile.TemporaryDirectory(prefix="arch-hypr-aur-build-") as directory:
        build_root = Path(directory)
        build_root.chmod(0o700)
        checkout = build_root / "recipe"
        clone_aur(url, revision, checkout)
        verify_aur_snapshot(recipe, snapshot_git_tree(checkout))
        build_home = build_root / "home"
        build_home.mkdir(mode=0o700)
        account = pwd.getpwuid(os.getuid())
        environment = clean_environment(
            HOME=str(build_home),
            USER=account.pw_name,
            LOGNAME=account.pw_name,
            XDG_CACHE_HOME=str(build_home / ".cache"),
            XDG_CONFIG_HOME=str(build_home / ".config"),
            XDG_DATA_HOME=str(build_home / ".local/share"),
            XDG_STATE_HOME=str(build_home / ".local/state"),
        )
        run(
            ("/usr/bin/makepkg", "--cleanbuild", "--clean", "--force"),
            environment=environment,
            cwd=checkout,
        )
        package_paths = planned_package_paths(
            capture(
                ("/usr/bin/makepkg", "--packagelist"),
                environment=environment,
                cwd=checkout,
            ).splitlines(),
            tuple(strings(item.data["packages"])),
        )
        resolved_checkout = checkout.resolve()
        if not package_paths or any(
            path.is_symlink()
            or not path.is_file()
            or resolved_checkout not in path.resolve().parents
            for path in package_paths
        ):
            raise CatalogError(f"AUR build produced an unsafe package path: {recipe.package_base}")
        run(
            (
                "/usr/bin/sudo",
                "/usr/bin/pacman",
                "-U",
                "--needed",
                "--",
                *(str(path.resolve()) for path in package_paths),
            )
        )
    if not aur_installed_exact(item):
        raise CatalogError(f"AUR package postcondition failed: {recipe.package_base}")
    return True


def planned_package_paths(lines: Iterable[str], packages: tuple[str, ...]) -> tuple[Path, ...]:
    """Pick the reviewed packages from `makepkg --packagelist`.

    With `debug` in makepkg.conf OPTIONS the list also names a `-debug`
    package, which makepkg skips for packages without binaries. Only the
    planned packages are installed; each must appear exactly once.
    """
    paths: dict[str, list[Path]] = {}
    for line in lines:
        if line:
            path = Path(line)
            # <pkgname>-<[epoch:]pkgver>-<pkgrel>-<arch><PKGEXT>
            paths.setdefault(path.name.rsplit("-", 3)[0], []).append(path)
    if any(len(paths.get(package, ())) != 1 for package in packages):
        return ()
    return tuple(paths[package][0] for package in packages)


def aur_installed_exact(item: PlannedAction) -> bool:
    version = str(item.data["version"])
    for package in strings(item.data["packages"]):
        probe = subprocess.run(
            ("/usr/bin/pacman", "-Qm", "--", package),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if probe.returncode or probe.stdout.strip() != f"{package} {version}":
            return False
    return True


def apply_file_action(
    root: Path,
    home: HomeFiles,
    plan: ExecutionPlan,
    item: PlannedAction,
    sources: dict[tuple[str, str, str], object],
) -> bool:
    target = str(item.data["target"])
    expected = str(item.data["sha256"])
    mode = integer(item.data["mode"])
    symlink = optional_string(item.data.get("symlink"))
    if item.kind is ActionKind.GENERATED_FILE:
        content = str(item.data["content"]).encode()
    else:
        entry = sources.get((item.feature, target, expected))
        if entry is None:
            raise CatalogError(f"planned file no longer exists in workspace: {item.feature}:{target}")
        source = root / str(getattr(entry, "source"))
        content = None if symlink is not None else source.read_bytes()
        actual = hashlib.sha256(
            f"symlink:{symlink}".encode() if symlink is not None else content
        ).hexdigest()
        if actual != expected:
            raise CatalogError(f"workspace payload drifted: {source}")
    return home.install(
        target,
        content=content,
        symlink=symlink,
        mode=mode,
        expected_sha256=expected,
        backup_root=f"{STATE_ROOT}/backups/{plan.digest}",
    )


def initialize_skipped_features(home: HomeFiles) -> set[str]:
    marker = f"{STATE_ROOT}/legacy-skipped-features.json"
    current = home.read_text(marker)
    if current is not None:
        return set(strings(read_json(current, {}).get("skipped_features")))
    skipped: set[str] = set()
    for content in home.list_text_files(".local/state/omarchy-bootstrap", ".json").values():
        try:
            skipped.update(strings(read_json(content, {}).get("skipped_features")))
        except (json.JSONDecodeError, ValueError):
            continue
    payload = json_bytes({"skipped_features": sorted(skipped)})
    home.install(
        marker,
        content=payload,
        symlink=None,
        mode=0o600,
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        backup_root=f"{STATE_ROOT}/backups/state-migration",
    )
    return skipped


def write_journal(
    home: HomeFiles, target: str, completed: set[str], skipped: set[str], digest: str
) -> None:
    content = json_bytes(
        {"plan_digest": digest, "completed": sorted(completed), "skipped_features": sorted(skipped)}
    )
    home.install(
        target,
        content=content,
        symlink=None,
        mode=0o600,
        expected_sha256=hashlib.sha256(content).hexdigest(),
        backup_root=f"{STATE_ROOT}/backups/journals",
    )


def install_ssh(home: HomeFiles, keys: tuple[str, ...]) -> None:
    home.ensure_directory(".ssh", 0o700)
    current = home.read_text(".ssh/authorized_keys") or ""
    lines = current.splitlines()
    known = {line.strip() for line in lines if line.strip()}
    for key in keys:
        if key not in known:
            lines.append(key)
            known.add(key)
    content = ("\n".join(lines) + ("\n" if lines else "")).encode()
    home.install(
        ".ssh/authorized_keys",
        content=content,
        symlink=None,
        mode=0o600,
        expected_sha256=hashlib.sha256(content).hexdigest(),
        backup_root=f"{STATE_ROOT}/backups/ssh",
    )


def action_satisfied(
    item: PlannedAction,
    home: HomeFiles,
    environment: dict[str, str] | None = None,
) -> bool:
    if item.kind in {ActionKind.REPOSITORY_PACKAGES, ActionKind.AUR_BUILD}:
        return all(package_installed(name) for name in strings(item.data["packages"]))
    if item.kind is ActionKind.PINNED_TOOL:
        return all(tool_installed(name) for name in strings(item.data["tools"]))
    if item.kind is ActionKind.USER_UNIT:
        return not subprocess.run(
            ("/usr/bin/systemctl", "--user", "is-enabled", str(item.data["name"])),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
    if item.kind is ActionKind.SYSTEM_UNIT:
        return service_active(str(item.data["name"]))
    if item.kind is ActionKind.PINNED_GIT_ASSET:
        target = safe_target(home.path, str(item.data["target"]))
        return (
            git_output(target, "rev-parse", "HEAD") == item.data["revision"]
            and git_output(target, "remote", "get-url", "origin") == item.data["url"]
        )
    if item.kind is ActionKind.OMARCHY_THEME:
        current = home.read_text(".local/state/omarchy/current/theme.name")
        return current is not None and current.strip() == item.data["name"]
    if item.kind is ActionKind.MANUAL_AUTHENTICATION:
        return run_probe(
            tuple(strings(item.data["probe"])),
            optional_string(item.data.get("probe_contains")),
            environment,
        )
    if item.kind is ActionKind.AUTHORIZED_SSH_KEYS:
        current = set((home.read_text(".ssh/authorized_keys") or "").splitlines())
        return set(strings(item.data["keys"])).issubset(current) and service_active("sshd.service")
    if item.kind is ActionKind.FIREWALL_RULE:
        return ufw_rule_present()
    return False


def apply_repository(target_home: Path, plan_digest: str, item: PlannedAction) -> None:
    target = safe_target(target_home, str(item.data["target"]))
    url = str(item.data["url"])
    revision = str(item.data["revision"])
    if target.exists():
        if not (target / ".git").is_dir() or git_output(target, "status", "--porcelain"):
            raise RuntimeError(f"repository target is not a clean checkout: {target}")
        if git_output(target, "remote", "get-url", "origin") != url:
            raise RuntimeError(f"repository remote differs: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.bootstrap-", dir=target.parent))
    moved_target: Path | None = None
    try:
        run(("git", "clone", "--quiet", "--no-checkout", "--", url, str(staging)))
        run(("git", "-C", str(staging), "checkout", "--quiet", "--detach", revision))
        if (
            git_output(staging, "rev-parse", "HEAD") != revision
            or git_output(staging, "remote", "get-url", "origin") != url
            or git_output(staging, "status", "--porcelain")
        ):
            raise RuntimeError(f"staged repository verification failed: {target}")
        if target.exists():
            relative = target.relative_to(target_home.resolve())
            backup_root = target_home / STATE_ROOT / "backups" / plan_digest / "git"
            backup = backup_root / relative
            if backup.exists():
                backup = backup.with_name(f"{backup.name}.{secrets.token_hex(8)}")
            backup.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target, backup)
            moved_target = backup
        os.replace(staging, target)
        fsync_directory(target.parent)
    except Exception:
        if moved_target is not None and moved_target.exists() and not target.exists():
            os.replace(moved_target, target)
            fsync_directory(target.parent)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def safe_target(home: Path, relative: str) -> Path:
    lexical = Path(relative)
    if lexical.is_absolute() or ".." in lexical.parts or not lexical.parts:
        raise CatalogError(f"target escapes home: {relative}")
    resolved_home = home.resolve()
    target = resolved_home
    for part in lexical.parts:
        target = target / part
        if target.is_symlink():
            raise CatalogError(f"target path contains a symlink: {relative}")
    return target


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def package_installed(name: str) -> bool:
    return not subprocess.run(
        ("/usr/bin/pacman", "-Q", "--", name),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode


def tool_installed(selector: str) -> bool:
    return not subprocess.run(
        ("mise", "where", selector), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ).returncode


def command_environment(target_home: str) -> dict[str, str]:
    environment = dict(os.environ)
    shims = str(Path(target_home) / ".local/share/mise/shims")
    environment["PATH"] = f"{shims}:{environment.get('PATH', '')}"
    return environment


def authenticate(item: PlannedAction, environment: dict[str, str]) -> bool:
    label = str(item.data["label"])
    if not ask_yes_no(f"Authenticate {label} now?"):
        return False
    # A failed or cancelled login leaves it in the login queue; it must not
    # stop the remaining logins and services.
    try:
        run(tuple(strings(item.data["command"])), environment=environment)
    except KeyboardInterrupt:
        print(f"\n{label}: login cancelled; it stays in the login queue.")
        return False
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"{label}: login did not finish ({error}); it stays in the login queue.")
        return False
    if not run_probe(
        tuple(strings(item.data["probe"])),
        optional_string(item.data.get("probe_contains")),
        environment,
    ):
        print(f"{label}: login check did not pass; it stays in the login queue.")
        return False
    return True


def run_probe(
    argv: tuple[str, ...],
    contains: str | None,
    environment: dict[str, str] | None = None,
) -> bool:
    try:
        result = subprocess.run(
            argv,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=environment,
        )
    except OSError:
        return False
    return result.returncode == 0 and (contains is None or contains in result.stdout)


def service_active(name: str) -> bool:
    enabled = subprocess.run(
        ("/usr/bin/systemctl", "is-enabled", name),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode
    active = subprocess.run(
        ("/usr/bin/systemctl", "is-active", name),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode
    return not enabled and not active


def ufw_rule_present() -> bool:
    pattern = re.compile(r"^### tuple ### limit tcp 22(?:\s|$)")
    for path in (Path("/etc/ufw/user.rules"), Path("/etc/ufw/user6.rules")):
        try:
            if any(pattern.search(line) for line in path.read_text().splitlines()):
                return True
        except OSError:
            continue
    return False


def git_output(target: Path, *arguments: str) -> str:
    if not (target / ".git").is_dir():
        return ""
    result = subprocess.run(
        ("git", "-C", str(target), *arguments),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def action_digest(item: PlannedAction) -> str:
    encoded = json.dumps(item.to_dict(), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def read_json(content: str | None, default: dict[str, object]) -> dict[str, object]:
    if content is None:
        return dict(default)
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("state JSON must be an object")
    return value


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ValueError("expected an array of strings")
    return tuple(value)


def optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("expected a string")
    return value


def integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("expected an integer")
    return value


def run(
    argv: tuple[str, ...],
    *,
    environment: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> None:
    executable = shutil.which(argv[0]) if not argv[0].startswith("/") else argv[0]
    if not executable or not Path(executable).exists():
        raise RuntimeError(f"required command is unavailable: {argv[0]}")
    subprocess.run((executable, *argv[1:]), check=True, env=environment, cwd=cwd)


def capture(
    argv: tuple[str, ...],
    *,
    environment: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> str:
    executable = argv[0] if argv[0].startswith("/") else shutil.which(argv[0])
    if not executable or not Path(executable).exists():
        raise RuntimeError(f"required command is unavailable: {argv[0]}")
    return subprocess.run(
        (executable, *argv[1:]),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        env=environment,
        cwd=cwd,
    ).stdout
