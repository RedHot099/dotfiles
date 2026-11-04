#!/usr/bin/env python3
"""Refresh vendored public skills from the sources in skills/sources.toml.

Only the selected skills of each source change: their canonical trees, harness
links, index entries, and the source's pinned commit. Nothing else in the
repository or the home directory is touched. Install the result with
`./bootstrap integrations plan` and `./bootstrap integrations apply`.

  update-external-skills.py [--source ID ...] [--check]

Exit codes: 0 up to date or updated, 1 failure (the failing source writes
nothing), 2 updates available with --check.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_FILES = 2000
MAX_BYTES = 50 * 1024 * 1024
LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"
SKILL_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")


def _load_capture():
    spec = importlib.util.spec_from_file_location("capture_user_skills", Path(__file__).with_name("capture-user-skills.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capture = _load_capture()


class UpdateError(Exception):
    pass


@dataclass(frozen=True)
class Source:
    id: str
    url: str
    ref: str
    commit: str
    path: str
    license: str | None
    skills: tuple[str, ...]

    @property
    def origin_prefix(self) -> str:
        return f"{self.id}@"


@dataclass(frozen=True)
class Layout:
    root: Path

    @property
    def sources(self) -> Path:
        return self.root / "integrations/common/skills/sources.toml"

    @property
    def private(self) -> Path:
        return self.root / "integrations/common/skills/private"

    @property
    def payload(self) -> Path:
        return self.root / "integrations/common/payload/user-skills"

    @property
    def store(self) -> Path:
        return self.payload / ".local/share/arch-hypr-bootstrap/agent-skills"

    @property
    def index(self) -> Path:
        return self.payload / ".local/share/arch-hypr-bootstrap/skills-index.toml"

    def harness_targets(self) -> list[Path]:
        data = tomllib.loads((self.root / "integrations/common/harnesses.toml").read_text())
        return [self.payload / harness["target"] for harness in data["harnesses"]]


def read_sources(layout: Layout) -> list[Source]:
    data = tomllib.loads(layout.sources.read_text())
    sources = []
    for raw in data.get("sources", []):
        source = Source(
            id=raw["id"],
            url=raw["url"],
            ref=raw.get("ref", "main"),
            commit=raw.get("commit", ""),
            path=raw.get("path", "."),
            license=raw.get("license"),
            skills=tuple(raw["skills"]),
        )
        if not source.url.startswith("https://"):
            raise UpdateError(f"{source.id}: url must be HTTPS")
        if Path(source.path).is_absolute() or ".." in Path(source.path).parts:
            raise UpdateError(f"{source.id}: unsafe path {source.path}")
        for skill_id in source.skills:
            if not SKILL_ID.match(skill_id):
                raise UpdateError(f"{source.id}: invalid skill id {skill_id}")
        sources.append(source)
    ids = [skill for source in sources for skill in source.skills]
    duplicates = sorted({skill for skill in ids if ids.count(skill) > 1})
    if duplicates:
        raise UpdateError(f"Skills claimed by more than one source: {', '.join(duplicates)}")
    return sources


def read_index(layout: Layout) -> dict[str, tuple[str, str]]:
    entries = re.findall(r'id = "([^"]+)"\norigin = "([^"]+)"\nsha256 = "([0-9a-f]+)"', layout.index.read_text())
    return {skill_id: (origin, digest) for skill_id, origin, digest in entries}


def write_index(layout: Layout, entries: dict[str, tuple[str, str]]) -> None:
    text = f"schema = 1\ncount = {len(entries)}\n"
    for skill_id in sorted(entries):
        origin, digest = entries[skill_id]
        text += f'\n[[skills]]\nid = "{skill_id}"\norigin = "{origin}"\nsha256 = "{digest}"\n'
    layout.index.write_text(text)


def write_commit(layout: Layout, source: Source, commit: str) -> None:
    text = layout.sources.read_text()
    block = re.compile(rf'(\[\[sources\]\]\nid = "{re.escape(source.id)}"\n(?:[^\[\n][^\n]*\n)*?commit = ")[0-9a-f]*(")')
    updated, count = block.subn(rf"\g<1>{commit}\g<2>", text)
    if count != 1:
        raise UpdateError(f"{source.id}: could not rewrite commit in {layout.sources}")
    layout.sources.write_text(updated)


def git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise UpdateError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def resolve_latest(source: Source) -> str:
    output = git("ls-remote", source.url, source.ref)
    lines = [line.split() for line in output.splitlines() if line.strip()]
    exact = [sha for sha, name in lines if name in {source.ref, f"refs/heads/{source.ref}", f"refs/tags/{source.ref}"}]
    if not exact or not COMMIT.match(exact[0]):
        raise UpdateError(f"{source.id}: ref {source.ref} not found at {source.url}")
    return exact[0]


def checkout(source: Source, commit: str, workdir: Path) -> Path:
    git("init", "-q", str(workdir))
    git("remote", "add", "origin", source.url, cwd=workdir)
    git("fetch", "-q", "--depth", "1", "origin", commit, cwd=workdir)
    git("checkout", "-q", "--detach", commit, cwd=workdir)
    if source.commit and source.commit != commit:
        try:
            git("fetch", "-q", "--depth", "1", "origin", source.commit, cwd=workdir)
        except UpdateError:
            pass
    tree = git("ls-tree", "-r", commit, "--", source.path, cwd=workdir)
    if any(line.startswith("160000 ") for line in tree.splitlines()):
        raise UpdateError(f"{source.id}: submodules are not allowed")
    return workdir


def validate(source: Source, checkout_dir: Path) -> dict[str, Path]:
    base = (checkout_dir / source.path).resolve()
    if not base.is_relative_to(checkout_dir.resolve()):
        raise UpdateError(f"{source.id}: path escapes the repository")
    trees: dict[str, Path] = {}
    files = 0
    size = 0
    for skill_id in source.skills:
        tree = base / skill_id
        if tree.is_symlink() or not tree.is_dir():
            raise UpdateError(f"{source.id}: missing skill directory {skill_id}")
        entrypoint = tree / "SKILL.md"
        if not entrypoint.is_file():
            raise UpdateError(f"{source.id}: {skill_id} has no SKILL.md")
        declared = capture.read_skill_id(entrypoint)
        if declared != skill_id:
            raise UpdateError(f"{source.id}: {skill_id}/SKILL.md declares {declared}")
        for path in tree.rglob("*"):
            if path.is_symlink():
                raise UpdateError(f"{source.id}: symlinks are not allowed: {path.relative_to(base)}")
            if path.is_file():
                files += 1
                size += path.stat().st_size
                with path.open("rb") as handle:
                    if handle.read(len(LFS_POINTER)) == LFS_POINTER:
                        raise UpdateError(f"{source.id}: Git LFS pointer: {path.relative_to(base)}")
        try:
            capture.reject_secrets(tree)
        except SystemExit as error:
            raise UpdateError(f"{source.id}: {error}") from None
        trees[skill_id] = tree
    if files > MAX_FILES or size > MAX_BYTES:
        raise UpdateError(f"{source.id}: {files} files, {size} bytes exceeds the source limit")
    if source.license and not (checkout_dir / source.license).is_file():
        raise UpdateError(f"{source.id}: license file {source.license} not found")
    return trees


def check_ownership(source: Source, layout: Layout, index: dict[str, tuple[str, str]]) -> None:
    for skill_id in source.skills:
        origin = index.get(skill_id, (None,))[0]
        owned = origin is None or origin.startswith(source.origin_prefix)
        if not owned or (origin is None and (layout.private / skill_id).exists()):
            raise UpdateError(f"{source.id}: {skill_id} already exists and belongs to {origin or 'the user'}")


def install(source: Source, commit: str, checkout_dir: Path, trees: dict[str, Path], layout: Layout, index: dict[str, tuple[str, str]]) -> list[str]:
    changes = []
    harnesses = layout.harness_targets()
    staging_root = Path(tempfile.mkdtemp(prefix=".external-skills-", dir=layout.private.parent))
    try:
        staged: dict[str, Path] = {}
        for skill_id, tree in trees.items():
            target = staging_root / skill_id
            shutil.copytree(tree, target)
            if source.license:
                shutil.copy2(checkout_dir / source.license, target / Path(source.license).name)
            staged[skill_id] = target
        dropped = sorted(
            skill_id
            for skill_id, (origin, _) in index.items()
            if origin.startswith(source.origin_prefix) and skill_id not in source.skills
        )
        for skill_id in dropped:
            for root in (layout.private, layout.store):
                remove_tree(root, skill_id)
            for harness in harnesses:
                link = harness / skill_id
                if link.is_symlink():
                    link.unlink()
            del index[skill_id]
            changes.append(f"removed {skill_id}")
        for skill_id, target in staged.items():
            digest = capture.tree_hash(target)
            previous = index.get(skill_id, (None, None))[1]
            for root in (layout.private, layout.store):
                remove_tree(root, skill_id)
                shutil.copytree(target, root / skill_id)
            for harness in harnesses:
                link = harness / skill_id
                if link.is_symlink():
                    link.unlink()
                elif link.exists():
                    raise UpdateError(f"{source.id}: {link} exists and is not a link")
                harness.mkdir(parents=True, exist_ok=True)
                link.symlink_to(os.path.relpath(layout.store / skill_id, harness))
            index[skill_id] = (f"{source.id}@{commit}", digest)
            if previous is None:
                changes.append(f"added {skill_id}")
            elif previous != digest:
                changes.append(f"updated {skill_id}")
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
    return changes


def remove_tree(root: Path, skill_id: str) -> None:
    target = root / skill_id
    if target.resolve().parent != root.resolve():
        raise UpdateError(f"Refusing to remove {target}")
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.exists():
        shutil.rmtree(target)


def describe(source: Source, commit: str, checkout_dir: Path) -> str:
    if not source.commit or source.commit == commit:
        return ""
    paths = [f"{source.path}/{skill}" for skill in source.skills]
    try:
        return git("diff", "--stat", source.commit, commit, "--", *paths, cwd=checkout_dir)
    except UpdateError:
        return "(previous commit not fetchable; no diff summary)\n"


def run(layout: Layout, selected: set[str], check: bool) -> int:
    sources = [source for source in read_sources(layout) if not selected or source.id in selected]
    missing = selected - {source.id for source in sources}
    if missing:
        raise UpdateError(f"Unknown source: {', '.join(sorted(missing))}")
    index = read_index(layout)
    pending = False
    for source in sources:
        commit = resolve_latest(source)
        owned_now = {skill for skill, (origin, _) in index.items() if origin.startswith(source.origin_prefix)}
        if commit == source.commit and owned_now == set(source.skills):
            print(f"{source.id}: up to date at {commit[:12]}")
            continue
        pending = True
        print(f"{source.id}: {source.commit[:12] or 'unpinned'} -> {commit[:12]}")
        with tempfile.TemporaryDirectory(prefix="external-skill-") as temporary:
            checkout_dir = checkout(source, commit, Path(temporary) / "repo")
            trees = validate(source, checkout_dir)
            check_ownership(source, layout, index)
            summary = describe(source, commit, checkout_dir)
            if summary:
                print(summary.rstrip())
            if check:
                continue
            for change in install(source, commit, checkout_dir, trees, layout, index):
                print(f"  {change}")
        write_index(layout, index)
        write_commit(layout, source, commit)
    if check and pending:
        return 2
    if pending and not check:
        print("Run ./scripts/verify-bootstrap.sh, then ./bootstrap integrations plan and apply.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh vendored public agent skills")
    parser.add_argument("--source", action="append", default=[], help="source id to refresh (default: all)")
    parser.add_argument("--check", action="store_true", help="report available updates without writing")
    args = parser.parse_args()
    try:
        return run(Layout(ROOT), set(args.source), args.check)
    except UpdateError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
