from __future__ import annotations

from dataclasses import replace
from enum import StrEnum

from .model import ChoiceRow, SelectorState


class Key(StrEnum):
    UP = "up"
    DOWN = "down"
    SPACE = "space"
    LEFT = "left"
    RIGHT = "right"
    ALL = "all"
    NONE = "none"


def reduce_selector(state: SelectorState, key: Key) -> SelectorState:
    rows = state.visible_rows()
    if not rows:
        return replace(state, cursor=0)
    cursor = min(state.cursor, len(rows) - 1)
    if key is Key.UP:
        return replace(state, cursor=(cursor - 1) % len(rows))
    if key is Key.DOWN:
        return replace(state, cursor=(cursor + 1) % len(rows))
    row = rows[cursor]
    if key is Key.LEFT and row.kind == "group":
        return replace(state, collapsed=state.collapsed | {row.group}, cursor=cursor)
    if key is Key.RIGHT and row.kind == "group":
        return replace(state, collapsed=state.collapsed - {row.group}, cursor=cursor)
    if key is Key.SPACE:
        identifiers = (
            {item.id for item in state.choices if item.group == row.group}
            if row.kind == "group"
            else {row.id}
        )
        selected = [item.selected for item in state.choices if item.id in identifiers]
        return _set_selected(state, identifiers, not all(selected), cursor)
    if key in {Key.ALL, Key.NONE}:
        visible = {row.id for row in rows if row.kind == "choice"}
        return _set_selected(state, visible, key is Key.ALL, cursor)
    return replace(state, cursor=cursor)


def set_filter(state: SelectorState, value: str) -> SelectorState:
    return replace(state, filter_text=value, cursor=0)


def _set_selected(
    state: SelectorState,
    identifiers: set[str],
    selected: bool,
    cursor: int,
) -> SelectorState:
    choices = tuple(
        replace(item, selected=selected) if item.id in identifiers else item
        for item in state.choices
    )
    return replace(state, choices=choices, cursor=cursor)
