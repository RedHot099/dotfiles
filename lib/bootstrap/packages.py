from __future__ import annotations

import base64
import hashlib
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Mapping, Protocol

from .catalog import CatalogError, PackageBinding


PACKAGE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9@._+:-]*")
VERSION_RE = re.compile(r"[^\t\r\n]+")
DEPENDENCY_RE = re.compile(r"([A-Za-z0-9][A-Za-z0-9@._+:-]*)(?:[<>=].*)?")
MAX_AUR_FILE_SIZE = 2 * 1024 * 1024
SYNC_DATABASE_DIRECTORY = Path("/var/lib/pacman/sync")
MIRROR_TIMEOUT_SECONDS = 15


@dataclass(frozen=True, order=True)
class RepositoryPackage:
    repository: str
    name: str
    version: str

    def to_dict(self) -> dict[str, str]:
        return {
            "repository": self.repository,
            "name": self.name,
            "version": self.version,
        }


@dataclass(frozen=True)
class AurRecipe:
    package_base: str
    package_names: tuple[str, ...]
    version: str
    dependencies: tuple[str, ...]
    files: tuple[tuple[str, str, str], ...]

    def files_as_dicts(self) -> tuple[dict[str, str], ...]:
        return tuple(
            {"path": path, "sha256": digest, "content_base64": content}
            for path, digest, content in self.files
        )


class PlanningPackageProvider(Protocol):
    def resolve_repository(
        self, bindings: tuple[PackageBinding, ...]
    ) -> tuple[RepositoryPackage, ...]: ...

    def inspect_aur(self, binding: PackageBinding) -> AurRecipe: ...

    def missing_dependencies(self, dependencies: tuple[str, ...]) -> tuple[str, ...]: ...

    def resolve_dependency_packages(
        self, packages: tuple[str, ...]
    ) -> tuple[RepositoryPackage, ...]: ...

    def missing_build_requirements(self) -> tuple[str, ...]: ...


class LocalPackageProvider:
    def __init__(self, repositories: tuple[str, ...]):
        self.repositories = repository_names(repositories)

    def resolve_repository(
        self, bindings: tuple[PackageBinding, ...]
    ) -> tuple[RepositoryPackage, ...]:
        if not bindings:
            return ()
        self._preflight()
        packages = tuple(binding.package for binding in bindings)
        output = run_capture(
            (
                "/usr/bin/pacman",
                "-Sp",
                "--print-format",
                "%r\t%n\t%v",
                "--",
                *packages,
            )
        )
        transaction = parse_transaction(output, bindings, self.repositories)
        check_databases_current({item.repository for item in transaction})
        return transaction

    def inspect_aur(self, binding: PackageBinding) -> AurRecipe:
        if binding.provider != "aur" or binding.url is None or binding.revision is None:
            raise CatalogError(f"package is not a pinned AUR binding: {binding.requirement}")
        with tempfile.TemporaryDirectory(prefix="arch-hypr-aur-plan-") as directory:
            checkout = Path(directory) / "recipe"
            clone_aur(binding.url, binding.revision, checkout)
            files = snapshot_git_tree(checkout)
            srcinfo = checkout / ".SRCINFO"
            if not srcinfo.is_file() or not (checkout / "PKGBUILD").is_file():
                raise CatalogError(f"AUR recipe lacks PKGBUILD or .SRCINFO: {binding.package}")
            srcinfo_content = srcinfo.read_text()
            package_base, package_names, dependencies = parse_srcinfo(srcinfo_content)
            if package_base != binding.package:
                raise CatalogError(
                    f"AUR package base differs from binding: {binding.package} != {package_base}"
                )
            return AurRecipe(
                package_base,
                package_names,
                srcinfo_version(srcinfo_content),
                dependencies,
                files,
            )

    def missing_dependencies(self, dependencies: tuple[str, ...]) -> tuple[str, ...]:
        if not dependencies:
            return ()
        result = subprocess.run(
            ("/usr/bin/pacman", "-T", "--", *dependencies),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=clean_environment(),
        )
        if result.returncode not in {0, 127}:
            raise CatalogError(f"pacman dependency probe failed: {result.stderr.strip()}")
        return tuple(
            dependency_name(line.strip())
            for line in result.stdout.splitlines()
            if line.strip()
        )

    def resolve_dependency_packages(
        self, packages: tuple[str, ...]
    ) -> tuple[RepositoryPackage, ...]:
        if not packages:
            return ()
        bindings = tuple(
            PackageBinding(name, "repository", name, self.repositories, None, None)
            for name in packages
        )
        return self.resolve_repository(bindings)

    def missing_build_requirements(self) -> tuple[str, ...]:
        return () if "base-devel" in installed_versions(("base-devel",)) else ("base-devel",)

    def _preflight(self) -> None:
        if Path("/var/lib/pacman/db.lck").exists():
            raise CatalogError(
                "pacman database is locked; finish or diagnose the active transaction first"
            )



def version_at_least(installed: str | None, required: str) -> bool:
    """True when pacman orders `installed` at or after `required`.

    The distribution updater also upgrades AUR packages, so a newer install
    satisfies a pinned recipe; rebuilding the pin would be a downgrade.
    """
    if installed is None:
        return False
    if installed == required:
        return True
    result = subprocess.run(
        ("/usr/bin/vercmp", installed, required),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        return result.returncode == 0 and int(result.stdout.strip()) >= 0
    except ValueError:
        return False


def check_databases_current(
    repositories: set[str],
    database_directory: Path = SYNC_DATABASE_DIRECTORY,
    remote_time: Callable[[str], float | None] | None = None,
) -> None:
    """Fail unless every local sync database matches its first mirror.

    pacman stamps a downloaded database with the mirror's Last-Modified time,
    so equal times mean the local copy is current. Omarchy's stable mirror is
    a dated snapshot, which makes the file's age meaningless.
    """
    remote_time = remote_time or mirror_database_time
    stale: list[str] = []
    for repository in sorted(repositories):
        database = database_directory / f"{repository}.db"
        if not database.is_file():
            stale.append(repository)
            continue
        remote = remote_time(repository)
        if remote is None or remote > database.stat().st_mtime:
            stale.append(repository)
    if stale:
        raise CatalogError(
            "package databases are stale or missing for "
            + ", ".join(stale)
            + "; run omarchy update, then generate a new plan"
        )


def mirror_database_time(repository: str) -> float | None:
    servers = run_capture(("/usr/bin/pacman-conf", "--repo", repository, "Server")).split()
    if not servers:
        return None
    request = urllib.request.Request(
        f"{servers[0]}/{repository}.db",
        method="HEAD",
        # The Omarchy mirror rejects urllib's default agent with 403.
        headers={"User-Agent": "arch-hypr-bootstrap"},
    )
    try:
        with urllib.request.urlopen(request, timeout=MIRROR_TIMEOUT_SECONDS) as response:
            modified = response.headers.get("Last-Modified")
    except (OSError, urllib.error.URLError) as error:
        raise CatalogError(f"could not check the {repository} mirror: {error}") from error
    if not modified:
        return None
    return parsedate_to_datetime(modified).timestamp()


class StaticPackageProvider:
    """Deterministic provider for repository-owned compatibility fixtures."""

    def resolve_repository(
        self, bindings: tuple[PackageBinding, ...]
    ) -> tuple[RepositoryPackage, ...]:
        return tuple(
            sorted(
                RepositoryPackage(binding.repositories[0], binding.package, "fixture-1")
                for binding in bindings
            )
        )

    def inspect_aur(self, binding: PackageBinding) -> AurRecipe:
        content = base64.b64encode(
            f"pkgbase = {binding.package}\npkgname = {binding.package}\n".encode()
        ).decode()
        return AurRecipe(
            binding.package,
            (binding.package,),
            "fixture-1",
            (),
            ((".SRCINFO", hashlib.sha256(base64.b64decode(content)).hexdigest(), content),),
        )

    def missing_dependencies(self, dependencies: tuple[str, ...]) -> tuple[str, ...]:
        return ()

    def resolve_dependency_packages(
        self, packages: tuple[str, ...]
    ) -> tuple[RepositoryPackage, ...]:
        return ()

    def missing_build_requirements(self) -> tuple[str, ...]:
        return ()


def repository_names(fingerprints: tuple[str, ...]) -> tuple[str, ...]:
    names = tuple(item.split("|", 1)[0].split(":", 1)[0] for item in fingerprints)
    if any(not PACKAGE_NAME_RE.fullmatch(name) for name in names) or len(set(names)) != len(names):
        raise CatalogError("repository fingerprint contains unsafe or duplicate names")
    return names


def parse_transaction(
    output: str,
    direct_bindings: tuple[PackageBinding, ...],
    configured_repositories: tuple[str, ...],
) -> tuple[RepositoryPackage, ...]:
    configured = set(configured_repositories)
    transaction: list[RepositoryPackage] = []
    seen: set[str] = set()
    for line in output.splitlines():
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) != 3:
            raise CatalogError(f"pacman returned an invalid transaction row: {line!r}")
        repository, name, version = fields
        if (
            not PACKAGE_NAME_RE.fullmatch(repository)
            or not PACKAGE_NAME_RE.fullmatch(name)
            or not VERSION_RE.fullmatch(version)
            or repository not in configured
            or name in seen
        ):
            raise CatalogError(f"pacman returned an unsafe transaction row: {line!r}")
        seen.add(name)
        transaction.append(RepositoryPackage(repository, name, version))
    if not transaction:
        raise CatalogError("pacman returned an empty transaction for missing packages")
    resolved = {item.name: item for item in transaction}
    for binding in direct_bindings:
        package = resolved.get(binding.package)
        if package is None:
            raise CatalogError(f"transaction does not contain requested package: {binding.package}")
        if package.repository not in binding.repositories:
            raise CatalogError(
                f"package resolved from unapproved repository: "
                f"{binding.package} -> {package.repository}"
            )
    return tuple(sorted(transaction))


def parse_srcinfo(content: str) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    package_base: str | None = None
    package_names: set[str] = set()
    dependencies: set[str] = set()
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key == "pkgbase":
            package_base = value
        elif key == "pkgname":
            package_names.add(value)
        elif key == "depends" or key == "makedepends" or key == "checkdepends" or key.startswith(("depends_", "makedepends_", "checkdepends_")):
            dependencies.add(value)
    if package_base is None or not PACKAGE_NAME_RE.fullmatch(package_base):
        raise CatalogError("AUR .SRCINFO has no safe pkgbase")
    if not package_names or any(not PACKAGE_NAME_RE.fullmatch(item) for item in package_names):
        raise CatalogError("AUR .SRCINFO has no safe pkgname")
    for dependency in dependencies:
        dependency_name(dependency)
    return package_base, tuple(sorted(package_names)), tuple(sorted(dependencies))


def dependency_name(value: str) -> str:
    match = DEPENDENCY_RE.fullmatch(value)
    if match is None:
        raise CatalogError(f"unsafe AUR dependency: {value}")
    return match.group(1)


def srcinfo_version(content: str) -> str:
    fields: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key in {"epoch", "pkgver", "pkgrel"} and key not in fields:
            fields[key] = value
    if "pkgver" not in fields or "pkgrel" not in fields:
        raise CatalogError("AUR .SRCINFO has no exact package version")
    version = f"{fields['pkgver']}-{fields['pkgrel']}"
    if "epoch" in fields:
        version = f"{fields['epoch']}:{version}"
    if not VERSION_RE.fullmatch(version):
        raise CatalogError("AUR .SRCINFO has an unsafe package version")
    return version


def clone_aur(url: str, revision: str, target: Path) -> None:
    run_capture(("/usr/bin/git", "clone", "--quiet", "--no-checkout", "--", url, str(target)))
    run_capture(
        (
            "/usr/bin/git",
            "-C",
            str(target),
            "-c",
            "advice.detachedHead=false",
            "checkout",
            "--quiet",
            "--detach",
            revision,
        )
    )
    actual = run_capture(("/usr/bin/git", "-C", str(target), "rev-parse", "HEAD")).strip()
    if actual != revision:
        raise CatalogError(f"AUR checkout differs from reviewed commit: {actual}")


def snapshot_git_tree(root: Path) -> tuple[tuple[str, str, str], ...]:
    output = run_capture(
        ("/usr/bin/git", "-C", str(root), "ls-tree", "-r", "--name-only", "HEAD")
    )
    result: list[tuple[str, str, str]] = []
    for relative in output.splitlines():
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise CatalogError(f"unsafe path in AUR recipe: {relative}")
        source = root.joinpath(*path.parts)
        if source.is_symlink():
            resolved = source.resolve(strict=False)
            if root.resolve() not in resolved.parents or not resolved.is_file():
                raise CatalogError(f"AUR recipe symlink escapes its tree: {relative}")
            content = f"symlink:{os.readlink(source)}".encode()
        elif source.is_file():
            content = source.read_bytes()
        else:
            raise CatalogError(f"AUR recipe contains a non-regular file: {relative}")
        if len(content) > MAX_AUR_FILE_SIZE:
            raise CatalogError(f"AUR recipe file is too large to review: {relative}")
        result.append(
            (
                path.as_posix(),
                hashlib.sha256(content).hexdigest(),
                base64.b64encode(content).decode(),
            )
        )
    return tuple(sorted(result))


def verify_aur_snapshot(
    expected: AurRecipe, actual_files: tuple[tuple[str, str, str], ...]
) -> None:
    if expected.files != actual_files:
        raise CatalogError(f"AUR recipe changed after planning: {expected.package_base}")


def recipe_from_action(data: dict[str, object]) -> AurRecipe:
    raw_files = data.get("files")
    if not isinstance(raw_files, (tuple, list)):
        raise CatalogError("planned AUR recipe has no files")
    files: list[tuple[str, str, str]] = []
    for item in raw_files:
        if not isinstance(item, Mapping) or set(item) != {"path", "sha256", "content_base64"}:
            raise CatalogError("planned AUR file record is invalid")
        files.append((str(item["path"]), str(item["sha256"]), str(item["content_base64"])))
    return AurRecipe(
        package_base=str(data["package_base"]),
        package_names=tuple(str(item) for item in iterable(data["packages"])),
        version=str(data["version"]),
        dependencies=tuple(str(item) for item in iterable(data["dependencies"])),
        files=tuple(files),
    )


def transaction_from_action(data: dict[str, object]) -> tuple[RepositoryPackage, ...]:
    raw = data.get("transaction")
    if not isinstance(raw, (tuple, list)):
        raise CatalogError("planned repository action has no transaction")
    result: list[RepositoryPackage] = []
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != {"repository", "name", "version"}:
            raise CatalogError("planned transaction record is invalid")
        result.append(
            RepositoryPackage(str(item["repository"]), str(item["name"]), str(item["version"]))
        )
    return tuple(result)


def verify_transaction(
    planned: tuple[RepositoryPackage, ...],
    current: tuple[RepositoryPackage, ...],
    installed_versions: dict[str, str],
) -> None:
    planned_by_name = {item.name: item for item in planned}
    current_by_name = {item.name: item for item in current}
    if any(planned_by_name.get(name) != item for name, item in current_by_name.items()):
        raise CatalogError("repository transaction changed after planning")
    for name, item in planned_by_name.items():
        if name not in current_by_name and installed_versions.get(name) != item.version:
            raise CatalogError("repository transaction changed after planning")


def installed_versions(packages: Iterable[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for package in sorted(set(packages)):
        probe = subprocess.run(
            ("/usr/bin/pacman", "-Q", "--", package),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=clean_environment(),
        )
        if probe.returncode == 0:
            fields = probe.stdout.strip().split()
            if len(fields) != 2:
                raise CatalogError(f"pacman returned invalid installed state for {package}")
            if fields[0] != package:
                continue
            result[package] = fields[1]
    return result


def bindings_from_action(data: dict[str, object]) -> tuple[PackageBinding, ...]:
    raw = data.get("sources")
    if not isinstance(raw, (tuple, list)):
        raise CatalogError("planned repository action has no source bindings")
    result: list[PackageBinding] = []
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != {"package", "repositories"}:
            raise CatalogError("planned package source record is invalid")
        repositories = tuple(str(value) for value in iterable(item["repositories"]))
        package = str(item["package"])
        result.append(PackageBinding(package, "repository", package, repositories, None, None))
    return tuple(result)


def clean_environment(**extra: str) -> dict[str, str]:
    environment = {
        "HOME": extra.pop("HOME", "/nonexistent"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }
    environment.update(extra)
    return environment


def run_capture(argv: tuple[str, ...], *, cwd: Path | None = None) -> str:
    result = subprocess.run(
        argv,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=clean_environment(),
    )
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise CatalogError(f"command failed ({argv[0]}): {message}")
    return result.stdout


def iterable(value: object) -> Iterable[object]:
    if isinstance(value, (tuple, list)):
        return value
    raise CatalogError("planned sequence has an invalid type")
