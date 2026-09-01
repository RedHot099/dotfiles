from __future__ import annotations

import shutil
import sys
from dataclasses import replace

from .model import SelectorState
from .selector import Key, reduce_selector, set_filter
from .terminal import raw_terminal, read_key


def select(title: str, state: SelectorState) -> SelectorState:
    with raw_terminal():
        while True:
            _render(title, state)
            key = read_key()
            aliases = {"j": Key.DOWN, "k": Key.UP, " ": Key.SPACE, "a": Key.ALL, "n": Key.NONE}
            if key == "enter":
                return state
            if key == "escape":
                raise KeyboardInterrupt
            if key == "/":
                state = set_filter(state, _prompt("Search: "))
                continue
            normalized = aliases.get(key)
            if normalized is None:
                try:
                    normalized = Key(key)
                except ValueError:
                    continue
            state = reduce_selector(state, normalized)


def _render(title: str, state: SelectorState) -> None:
    width = shutil.get_terminal_size((80, 24)).columns
    rows = state.visible_rows()
    choices = {item.id: item for item in state.choices}
    output = ["\x1b[2J\x1b[H", title, ""]
    for index, row in enumerate(rows):
        cursor = ">" if index == state.cursor else " "
        if row.kind == "group":
            members = [item for item in state.choices if item.group == row.group]
            mark = "x" if members and all(item.selected for item in members) else " "
            arrow = "+" if row.group in state.collapsed else "-"
            line = f"{cursor} [{mark}] {arrow} {row.group}"
        else:
            item = choices[row.id]
            suffix = " (installed)" if item.installed else ""
            if item.hint:
                suffix += f" — {item.hint}"
            line = f"{cursor}   [{'x' if item.selected else ' '}] {item.label}{suffix}"
        output.append(line[:width])
    output.extend(("", "↑/↓ or j/k move  Space toggle  ←/→ fold  a all  n none  / search  Enter continue  Esc back"))
    sys.stdout.write("\n".join(output))
    sys.stdout.flush()


def _prompt(label: str) -> str:
    sys.stdout.write("\x1b[2K\r" + label)
    sys.stdout.flush()
    value: list[str] = []
    while True:
        key = read_key()
        if key == "enter":
            return "".join(value)
        if key == "escape":
            return ""
        if key in {"\x7f", "\b"}:
            if value:
                value.pop()
        elif len(key) == 1 and key.isprintable():
            value.append(key)
        sys.stdout.write("\x1b[2K\r" + label + "".join(value))
        sys.stdout.flush()
