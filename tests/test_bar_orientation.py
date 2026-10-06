#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "desktop/omarchy/payload/core-desktop/.config/omarchy/plugins/bar-orientation"
SCRIPT = PLUGIN / "sync-layout"

HORIZONTAL = {"left": [{"id": "omarchy.menu"}], "center": [], "right": [{"id": "omarchy.power"}]}
VERTICAL = {"left": [{"id": "omarchy.power"}], "center": [], "right": [{"id": "omarchy.menu"}]}


def config(position: str, layout: dict, entry: dict | None) -> dict:
    plugins = [{"id": "other"}] + ([entry] if entry is not None else [])
    return {"version": 1, "bar": {"position": position, "layout": layout}, "plugins": plugins}


class BarOrientationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.path = Path(self.home.name) / ".config/omarchy/shell.json"
        self.path.parent.mkdir(parents=True)
        self.bin = Path(self.home.name) / "bin"
        self.bin.mkdir()
        self.reloads = Path(self.home.name) / "reloads"
        fake = self.bin / "omarchy-shell"
        fake.write_text(f'#!/bin/sh\necho "$*" >> "{self.reloads}"\n')
        fake.chmod(0o755)

    def sync(self) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ, HOME=self.home.name, PATH=f"{self.bin}:/usr/bin:/bin")
        return subprocess.run(
            ("bash", str(SCRIPT)), env=environment, text=True, capture_output=True
        )

    def reload_count(self) -> int:
        return len(self.reloads.read_text().splitlines()) if self.reloads.exists() else 0

    def write(self, value: dict) -> None:
        self.path.write_text(json.dumps(value))

    def read(self) -> dict:
        return json.loads(self.path.read_text())

    def entry(self) -> dict:
        return next(item for item in self.read()["plugins"] if item["id"] == "bar-orientation")

    def test_without_entry_leaves_file_untouched(self) -> None:
        self.path.write_text('{"version":1,"bar":{"layout":{}},"plugins":[]}')
        before = self.path.stat().st_mtime_ns
        self.assertEqual(self.sync().returncode, 0)
        self.assertEqual(self.path.read_text(), '{"version":1,"bar":{"layout":{}},"plugins":[]}')
        self.assertEqual(self.path.stat().st_mtime_ns, before)
        self.assertEqual(self.reload_count(), 0)

    def test_invalid_json_fails_without_writing(self) -> None:
        self.path.write_text('{"version": 1, "plu')
        self.assertNotEqual(self.sync().returncode, 0)
        self.assertEqual(self.path.read_text(), '{"version": 1, "plu')

    def test_first_run_saves_current_layout(self) -> None:
        self.write(config("top", HORIZONTAL, {"id": "bar-orientation", "layouts": {"vertical": VERTICAL}}))
        self.assertEqual(self.sync().returncode, 0)
        self.assertEqual(self.entry()["orientation"], "horizontal")
        self.assertEqual(self.entry()["layouts"], {"horizontal": HORIZONTAL, "vertical": VERTICAL})
        self.assertEqual(self.read()["bar"]["layout"], HORIZONTAL)
        self.assertEqual(self.reloads.read_text(), "shell reloadConfig\n")

    def test_switching_edge_restores_saved_layout(self) -> None:
        entry = {"id": "bar-orientation", "orientation": "horizontal", "layouts": {"vertical": VERTICAL}}
        self.write(config("left", HORIZONTAL, entry))
        self.assertEqual(self.sync().returncode, 0)
        self.assertEqual(self.read()["bar"]["layout"], VERTICAL)
        self.assertEqual(self.entry()["orientation"], "vertical")
        self.assertEqual(self.entry()["layouts"]["horizontal"], HORIZONTAL)

    def test_switching_without_saved_layout_keeps_current(self) -> None:
        self.write(config("right", HORIZONTAL, {"id": "bar-orientation", "orientation": "horizontal"}))
        self.assertEqual(self.sync().returncode, 0)
        self.assertEqual(self.read()["bar"]["layout"], HORIZONTAL)
        self.assertEqual(self.entry()["layouts"], {"horizontal": HORIZONTAL, "vertical": HORIZONTAL})

    def test_edit_on_same_edge_updates_saved_layout(self) -> None:
        entry = {"id": "bar-orientation", "orientation": "vertical", "layouts": {"vertical": HORIZONTAL}}
        self.write(config("left", VERTICAL, entry))
        self.assertEqual(self.sync().returncode, 0)
        self.assertEqual(self.read()["bar"]["layout"], VERTICAL)
        self.assertEqual(self.entry()["layouts"]["vertical"], VERTICAL)

    def test_second_run_does_not_rewrite(self) -> None:
        self.write(config("top", HORIZONTAL, {"id": "bar-orientation"}))
        self.assertEqual(self.sync().returncode, 0)
        settled = self.path.read_text()
        before = self.path.stat().st_ino
        self.assertEqual(self.sync().returncode, 0)
        self.assertEqual(self.path.read_text(), settled)
        self.assertEqual(self.path.stat().st_ino, before)
        self.assertEqual(self.reload_count(), 1)

    def test_write_preserves_mode(self) -> None:
        self.write(config("top", HORIZONTAL, {"id": "bar-orientation"}))
        self.path.chmod(0o644)
        self.assertEqual(self.sync().returncode, 0)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o644)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_repository_shell_json_seeds_vertical_layout(self) -> None:
        shell = json.loads((PLUGIN.parents[1] / "shell.json").read_text())
        entry = next(item for item in shell["plugins"] if item["id"] == "bar-orientation")
        self.assertEqual(set(entry["layouts"]["vertical"]), {"left", "center", "right"})
        manifest = json.loads((PLUGIN / "manifest.json").read_text())
        self.assertEqual(manifest["id"], "bar-orientation")


if __name__ == "__main__":
    unittest.main()
