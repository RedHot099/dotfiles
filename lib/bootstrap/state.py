from __future__ import annotations

import json
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


class StateStore:
    def __init__(self, target_home: Path) -> None:
        self.target_home = target_home

    def read_selection(self, workflow: WorkflowId) -> SelectionRecord | None:
        with HomeFiles(self.target_home) as home:
            content = home.read_text(self._selection_target(workflow))
        if content is None:
            return None
        data = json.loads(content)
        if set(data) != {"schema", "workflow", "selected", "catalog_digest"}:
            raise ValueError(f"invalid {workflow.value} selection state")
        if data["schema"] != 1 or data["workflow"] != workflow.value:
            raise ValueError(f"invalid {workflow.value} selection state")
        selected = data["selected"]
        digest = data["catalog_digest"]
        if (
            not isinstance(selected, list)
            or not all(isinstance(item, str) for item in selected)
            or selected != sorted(set(selected))
            or not isinstance(digest, str)
        ):
            raise ValueError(f"invalid {workflow.value} selection state")
        return SelectionRecord(workflow, frozenset(selected), digest)

    def write_selection(self, record: SelectionRecord) -> None:
        data = {
            "schema": 1,
            "workflow": record.workflow.value,
            "selected": sorted(record.selected),
            "catalog_digest": record.catalog_digest,
        }
        content = (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode()
        with HomeFiles(self.target_home) as home:
            home.ensure_directory(STATE_ROOT, 0o700)
            home.ensure_directory(f"{STATE_ROOT}/selections", 0o700)
            home.write_private_atomic(self._selection_target(record.workflow), content)

    @staticmethod
    def _selection_target(workflow: WorkflowId) -> str:
        return f"{STATE_ROOT}/selections/{workflow.value}.json"
