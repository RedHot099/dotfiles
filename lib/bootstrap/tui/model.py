from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChoiceRow:
    id: str
    group: str
    label: str
    selected: bool
    installed: bool = False
    hint: str | None = None


@dataclass(frozen=True)
class VisibleRow:
    kind: str
    id: str
    group: str


@dataclass(frozen=True)
class SelectorState:
    choices: tuple[ChoiceRow, ...]
    collapsed: frozenset[str] = frozenset()
    filter_text: str = ""
    cursor: int = 0

    def visible_rows(self) -> tuple[VisibleRow, ...]:
        query = self.filter_text.casefold()
        groups: list[str] = []
        matches: dict[str, list[ChoiceRow]] = {}
        for choice in self.choices:
            if query and query not in choice.label.casefold() and query not in choice.group.casefold():
                continue
            if choice.group not in matches:
                groups.append(choice.group)
                matches[choice.group] = []
            matches[choice.group].append(choice)
        rows: list[VisibleRow] = []
        for group in groups:
            rows.append(VisibleRow("group", group, group))
            if group not in self.collapsed or query:
                rows.extend(VisibleRow("choice", item.id, group) for item in matches[group])
        return tuple(rows)

    def selected_ids(self) -> frozenset[str]:
        return frozenset(item.id for item in self.choices if item.selected)
