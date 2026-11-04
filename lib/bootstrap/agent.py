"""Helpers for the non-interactive agent path: JSON reports, checkout gate, terminal handoff."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .catalog import CatalogError
from .domain import ActionKind
from .executor import (
    FILE_ACTIONS,
    TERMINAL_ACTIONS,
    ApplyResult,
    file_change,
    optional_string,
    run_probe,
    strings,
    command_environment,
    terminal_action_satisfied,
)
from .files import HomeFiles
from .planning.model import WorkflowPlan
from .ssh import ssh_fingerprint


REPORT_SCHEMA = 1
EXIT_READY = 0
EXIT_DRIFT = 1
EXIT_FAIL = 2
EXIT_ACTION_NEEDED = 3
LAUNCHER = "omarchy-launch-floating-terminal-with-presentation"


@contextmanager
def json_stdout() -> Iterator[int]:
    """Send everything to stderr and keep the real stdout for one JSON document.

    Child processes inherit file descriptor 1, so a bare print or a tool's
    progress output would otherwise corrupt the report.
    """
    sys.stdout.flush()
    saved = os.dup(1)
    os.dup2(2, 1)
    try:
        yield saved
    finally:
        sys.stdout.flush()
        os.dup2(saved, 1)
        os.close(saved)


def emit(descriptor: int, report: dict[str, object]) -> None:
    # A pipe can take a large report in parts; write until all of it is out.
    view = memoryview((json.dumps(report, indent=2, sort_keys=True) + "\n").encode())
    while view:
        view = view[os.write(descriptor, view):]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def checkout_state(root: Path) -> dict[str, object]:
    def git(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ("git", "-C", str(root), *arguments),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

    try:
        commit = git("rev-parse", "HEAD")
    except OSError:
        return {"git": False}
    if commit.returncode:
        return {"git": False}
    return {
        "git": True,
        "branch": git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip(),
        "commit": commit.stdout.strip(),
        "dirty": bool(git("status", "--porcelain").stdout.strip()),
    }


def checkout_problem(checkout: dict[str, object]) -> str | None:
    """An approved apply installs only a committed state of main."""
    if not checkout.get("git"):
        return "the repository is not a git checkout"
    if checkout.get("branch") != "main":
        return f"the checkout is on {checkout.get('branch')!r}, not main"
    if checkout.get("dirty"):
        return "the checkout has uncommitted or untracked changes"
    return None


def describe_changes(plan: WorkflowPlan, home: HomeFiles, managed: dict[str, str]) -> dict[str, object]:
    """What applying the plan would change now. Read-only."""
    files: dict[str, list[str]] = {"create": [], "update": [], "local-edit": [], "unmanaged": []}
    unchanged = 0
    terminal: list[str] = []
    logins: list[str] = []
    keys: dict[str, list[str]] = {}
    aur: list[dict[str, object]] = []
    environment = command_environment(str(home.path))
    for item in plan.actions:
        if item.kind in FILE_ACTIONS:
            change = file_change(home, item, managed)
            if change == "unchanged":
                unchanged += 1
            else:
                files[change].append(str(item.data["target"]))
            continue
        if item.kind in TERMINAL_ACTIONS and not terminal_action_satisfied(item, home):
            terminal.append(f"{item.kind.value}: {item.feature}")
            if item.kind is ActionKind.AUTHORIZED_SSH_KEYS:
                keys[item.feature] = [ssh_fingerprint(key) for key in strings(item.data["keys"])]
            if item.kind is ActionKind.AUR_BUILD:
                aur.append(
                    {
                        "package_base": item.data["package_base"],
                        "version": item.data["version"],
                        "commit": item.data["commit"],
                        "url": item.data["url"],
                    }
                )
        if item.kind is ActionKind.MANUAL_AUTHENTICATION and not run_probe(
            tuple(strings(item.data["probe"])), optional_string(item.data.get("probe_contains")), environment
        ):
            logins.append(str(item.data["label"]))
    planned = {str(item.data["target"]) for item in plan.actions if item.kind in FILE_ACTIONS}
    # Installed by an earlier apply, gone from the configuration since.
    orphaned = sorted(target for target in managed if target not in planned and home.hash(target) is not None)
    return {
        "files": {**files, "unchanged": unchanged, "orphaned": orphaned},
        "terminal_required": terminal,
        "logins_pending": logins,
        "new_ssh_keys": keys,
        "aur_builds": aur,
    }


def result_record(
    workflow: str,
    digest: str,
    status: str,
    exit_code: int,
    *,
    result: ApplyResult | None = None,
    message: str = "",
    checkout: dict[str, object] | None = None,
    **extra: object,
) -> dict[str, object]:
    record: dict[str, object] = {
        "schema": REPORT_SCHEMA,
        "workflow": workflow,
        "plan_digest": digest,
        "status": status,
        "exit_code": exit_code,
        "message": message,
        "updated_at": now(),
        **extra,
    }
    if checkout is not None:
        record["checkout"] = checkout
    if result is not None:
        record.update(
            changed=result.changed,
            unchanged=result.unchanged,
            skipped_features=list(result.skipped_features),
            deferred=[
                {"kind": item.kind, "feature": item.feature, "reason": item.reason, "detail": item.detail}
                for item in result.deferred
            ],
        )
    return record


def terminal_command(root: Path, workflow: str, digest: str, discard_local: bool) -> list[str]:
    command = [str(root / "bootstrap"), workflow, "apply", "--plan", digest]
    return command + ["--discard-local"] if discard_local else command


def launch_terminal(command: list[str], environment: dict[str, str]) -> None:
    """Open a floating terminal on the user's session and return at once.

    sudo and pacman ask there; the agent reads the outcome from the result
    file with `status --wait`, never from the terminal.
    """
    launcher = shutil.which(LAUNCHER, path=environment.get("PATH"))
    if launcher is None:
        raise CatalogError(f"{LAUNCHER} is not available")
    subprocess.Popen(
        (launcher, shlex.join(command)),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
