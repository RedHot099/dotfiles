from __future__ import annotations

import fcntl
import json
import os
from dataclasses import dataclass
from pathlib import Path

from .domain import WorkflowId
from .files import HomeFiles


STATE_ROOT = ".local/state/arch-hypr-bootstrap"


@dataclass(frozen=True)
class SelectionRecord:
    workflow: WorkflowId
    selected: frozenset[str]
    catalog_digest: str
    # Every visible catalog ID offered when this selection was made; None for
    # schema 1 records. An ID outside it is new since the last selection.
    known: frozenset[str] | None = None


class StateStore:
    def __init__(self, target_home: Path) -> None:
        self.target_home = target_home

    def read_selection(self, workflow: WorkflowId) -> SelectionRecord | None:
        with HomeFiles(self.target_home) as home:
            content = home.read_text(self._selection_target(workflow))
        if content is None:
            return None
        data = json.loads(content)
        keys = {"schema", "workflow", "selected", "catalog_digest"}
        schema = data.get("schema") if isinstance(data, dict) else None
        if schema not in (1, 2) or set(data) != (keys | {"known"} if schema == 2 else keys):
            raise ValueError(f"invalid {workflow.value} selection state")
        if data["workflow"] != workflow.value:
            raise ValueError(f"invalid {workflow.value} selection state")
        selected = _sorted_strings(data["selected"], workflow)
        known = _sorted_strings(data["known"], workflow) if schema == 2 else None
        digest = data["catalog_digest"]
        if not isinstance(digest, str):
            raise ValueError(f"invalid {workflow.value} selection state")
        return SelectionRecord(workflow, selected, digest, known)

    def write_selection(self, record: SelectionRecord) -> None:
        data: dict[str, object] = {
            "schema": 1,
            "workflow": record.workflow.value,
            "selected": sorted(record.selected),
            "catalog_digest": record.catalog_digest,
        }
        if record.known is not None:
            data["schema"] = 2
            data["known"] = sorted(record.known)
        self._write(self._selection_target(record.workflow), data, "selections")

    def read_result(self, workflow: WorkflowId) -> dict[str, object] | None:
        with HomeFiles(self.target_home) as home:
            content = home.read_text(f"{STATE_ROOT}/results/{workflow.value}.json")
        if content is None:
            return None
        data = json.loads(content)
        if not isinstance(data, dict) or data.get("workflow") != workflow.value:
            raise ValueError(f"invalid {workflow.value} result state")
        return data

    def write_result(self, workflow: WorkflowId, result: dict[str, object]) -> None:
        """Write a result; the caller holds the apply lock."""
        self._write(f"{STATE_ROOT}/results/{workflow.value}.json", result, "results")

    def write_result_locked(self, workflow: WorkflowId, result: dict[str, object]) -> bool:
        """Write a result under the apply lock; False when another apply holds it.

        A running apply saves its own status; an outcome from outside the
        lock must not overwrite it.
        """
        with HomeFiles(self.target_home) as home:
            home.ensure_directory(STATE_ROOT, 0o700)
            descriptor = home.open_lock(f"{STATE_ROOT}/apply.lock")
            try:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return False
                self.write_result(workflow, result)
                return True
            finally:
                os.close(descriptor)

    def read_managed(self, workflow: WorkflowId) -> dict[str, str]:
        with HomeFiles(self.target_home) as home:
            return read_managed(home, workflow.value)

    def _write(self, target: str, data: dict[str, object], directory: str) -> None:
        content = (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode()
        with HomeFiles(self.target_home) as home:
            home.ensure_directory(STATE_ROOT, 0o700)
            home.ensure_directory(f"{STATE_ROOT}/{directory}", 0o700)
            home.write_private_atomic(target, content)

    @staticmethod
    def _selection_target(workflow: WorkflowId) -> str:
        return f"{STATE_ROOT}/selections/{workflow.value}.json"


def managed_target(workflow: str) -> str:
    return f"{STATE_ROOT}/managed/{workflow}.json"


def read_managed(home: HomeFiles, workflow: str) -> dict[str, str]:
    """Target -> sha256 of every file the last applies installed."""
    content = home.read_text(managed_target(workflow))
    if content is None:
        return {}
    data = json.loads(content)
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in files.items()
    ):
        raise ValueError(f"invalid {workflow} managed-file state")
    return dict(files)


def write_managed(home: HomeFiles, workflow: str, files: dict[str, str]) -> None:
    content = json.dumps({"schema": 1, "files": dict(sorted(files.items()))}, separators=(",", ":"))
    home.ensure_directory(STATE_ROOT, 0o700)
    home.ensure_directory(f"{STATE_ROOT}/managed", 0o700)
    home.write_private_atomic(managed_target(workflow), (content + "\n").encode())


def _sorted_strings(value: object, workflow: WorkflowId) -> frozenset[str]:
    if (
        not isinstance(value, list)
        or not all(isinstance(item, str) for item in value)
        or value != sorted(set(value))
    ):
        raise ValueError(f"invalid {workflow.value} selection state")
    return frozenset(value)
