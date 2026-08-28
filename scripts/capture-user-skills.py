#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path


EXCLUDED_NAMES = {"omarchy", "diagnose-crash"}
SECRET_NAMES = {"auth.json", ".credentials.json", "credentials.json", "secrets.json"}
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    re.compile(rb"(?:access_token|refresh_token|api_key)\s*[=:]\s*['\"][^'\"]{12,}", re.IGNORECASE),
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture reviewed user-owned agent skills")
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--destination", type=Path, default=Path("common/payload/user-skills"))
    args = parser.parse_args()
    sources = (args.home / ".agents" / "skills", args.home / ".codex" / "skills")
    skills = discover(sources)
    destination = args.destination.resolve()
    allowed_destination = (Path(__file__).resolve().parents[1] / "common/payload/user-skills").resolve()
    if destination != allowed_destination:
        raise SystemExit(f"Destination must be {allowed_destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".skills-") as temporary_name:
        temporary = Path(temporary_name)
        canonical = temporary / ".local" / "share" / "arch-hypr-bootstrap" / "agent-skills"
        canonical.mkdir(parents=True)
        index = []
        for skill_id, source in sorted(skills.items()):
            target = canonical / skill_id
            shutil.copytree(source, target, symlinks=True)
            make_portable(skill_id, target)
            reject_secrets(target)
            index.append((skill_id, source.parent.parent.name, tree_hash(target)))
        write_adapters(temporary, [item[0] for item in index])
        write_index(temporary / ".local" / "share" / "arch-hypr-bootstrap" / "skills-index.toml", index)
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(temporary, destination, symlinks=True)
    print(f"Captured {len(skills)} user-owned skills in {destination}")
    return 0


def discover(sources: tuple[Path, ...]) -> dict[str, Path]:
    skills: dict[str, Path] = {}
    for source_root in sources:
        if not source_root.is_dir():
            raise SystemExit(f"Missing skill root: {source_root}")
        for source in sorted(source_root.iterdir()):
            if source.name.startswith(".") or source.name in EXCLUDED_NAMES or source.is_symlink() or not source.is_dir():
                continue
            entrypoint = source / "SKILL.md"
            if not entrypoint.is_file():
                continue
            skill_id = read_skill_id(entrypoint)
            if source.name != skill_id:
                raise SystemExit(f"Skill directory and name differ: {source} declares {skill_id}")
            if skill_id in skills:
                if tree_hash(skills[skill_id]) != tree_hash(source):
                    raise SystemExit(f"Conflicting skill id: {skill_id}")
                continue
            skills[skill_id] = source
    return skills


def read_skill_id(entrypoint: Path) -> str:
    match = re.search(r"^name:\s*['\"]?([^'\"\s]+)", entrypoint.read_text(), re.MULTILINE)
    if not match:
        raise SystemExit(f"Missing skill name: {entrypoint}")
    return match.group(1)


def make_portable(skill_id: str, target: Path) -> None:
    replacements = {
        "jira-task-from-diff": ("bash ~/.codex/skills/jira-task-from-diff/scripts/collect-jira-task-context.sh", "bash scripts/collect-jira-task-context.sh"),
        "python-review": ("bash ~/.codex/skills/python-review/scripts/collect-review-context.sh", "bash scripts/collect-review-context.sh"),
    }
    if skill_id not in replacements:
        return
    old, new = replacements[skill_id]
    entrypoint = target / "SKILL.md"
    content = entrypoint.read_text()
    if old not in content:
        raise SystemExit(f"Expected portability path not found in {entrypoint}")
    entrypoint.write_text(content.replace(old, new))


def reject_secrets(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        if path.name in SECRET_NAMES:
            raise SystemExit(f"Secret-like file rejected: {path}")
        content = path.read_bytes()
        for pattern in SECRET_PATTERNS:
            if pattern.search(content):
                raise SystemExit(f"Secret-like content rejected: {path}")


def write_adapters(root: Path, skill_ids: list[str]) -> None:
    adapters = {
        root / ".agents" / "skills": "../../.local/share/arch-hypr-bootstrap/agent-skills",
        root / ".claude" / "skills": "../../.local/share/arch-hypr-bootstrap/agent-skills",
        root / ".config" / "opencode" / "skills": "../../../.local/share/arch-hypr-bootstrap/agent-skills",
    }
    for directory, canonical in adapters.items():
        directory.mkdir(parents=True)
        for skill_id in skill_ids:
            (directory / skill_id).symlink_to(f"{canonical}/{skill_id}")


def write_index(path: Path, entries: list[tuple[str, str, str]]) -> None:
    lines = ["schema = 1", f"count = {len(entries)}", ""]
    for skill_id, origin, digest in entries:
        lines.extend(("[[skills]]", f'id = "{skill_id}"', f'origin = "{origin}"', f'sha256 = "{digest}"', ""))
    path.write_text("\n".join(lines))


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix().encode()
        digest.update(relative + b"\0")
        digest.update(oct(path.lstat().st_mode & 0o777).encode() + b"\0")
        if path.is_symlink():
            digest.update(b"link\0" + os.readlink(path).encode() + b"\0")
        elif path.is_file():
            digest.update(b"file\0" + path.read_bytes() + b"\0")
        elif path.is_dir():
            digest.update(b"dir\0")
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
