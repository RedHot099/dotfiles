import json
import hashlib
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bootstrap_core import (
    CatalogError,
    MachineFacts,
    apply_plan,
    audit_plan,
    build_plan,
    load_catalog,
    resolve_features,
)
from bootstrap_cli import default_wizard_selections, detect_known_hardware, render_monitor


ROOT = Path(__file__).resolve().parents[1]


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.features = load_catalog(ROOT / "features")

    def test_default_profiles_include_core_desktop_and_ai_development(self):
        defaults = {feature.id for feature in self.features.values() if feature.default}

        self.assertEqual(defaults, {"core-desktop", "ai-development"})

    def test_required_dependencies_are_locked_into_selection(self):
        selected = resolve_features(self.features, {"session-autostart"})

        self.assertIn("core-desktop", selected)
        self.assertIn("app.google-chrome", selected)
        self.assertIn("app.t3code", selected)

    def test_optional_features_are_not_selected_by_default(self):
        selected = resolve_features(
            self.features,
            {feature.id for feature in self.features.values() if feature.default},
        )

        self.assertNotIn("cloud.onedrive", selected)
        self.assertNotIn("cloud.google-drive", selected)
        self.assertNotIn("app.steam", selected)

    def test_installed_optional_features_do_not_become_wizard_defaults(self):
        features = dict(self.features)
        optional = features["app.steam"]

        self.assertNotIn(optional.id, default_wizard_selections(features))

    def test_plan_rejects_two_features_that_own_the_same_target(self):
        first = self.features["core-desktop"]
        conflicting = first.with_id("conflicting-test-feature")
        features = dict(self.features)
        features[conflicting.id] = conflicting
        facts = MachineFacts(omarchy_major=4, packages=frozenset(), commands=frozenset())

        with tempfile.TemporaryDirectory() as target:
            with self.assertRaises(CatalogError):
                build_plan(ROOT, features, {first.id, conflicting.id}, "generic", Path(target), facts)

    def test_plan_is_deterministic(self):
        facts = MachineFacts(omarchy_major=4, packages=frozenset(), commands=frozenset())
        requested = {"core-desktop", "ai-development"}

        with tempfile.TemporaryDirectory() as target:
            first = build_plan(ROOT, self.features, requested, "generic", Path(target), facts)
            second = build_plan(ROOT, self.features, requested, "generic", Path(target), facts)

        self.assertEqual(first.to_dict(), second.to_dict())

    def test_every_catalog_feature_forms_one_conflict_free_plan(self):
        facts = MachineFacts(omarchy_major=4, packages=frozenset(), commands=frozenset())

        with tempfile.TemporaryDirectory() as target:
            plan = build_plan(ROOT, self.features, set(self.features), "generic", Path(target), facts)

        self.assertEqual(set(plan.selected), set(self.features))

    def test_ultrawide_session_autostart_locks_application_dependencies(self):
        selected = resolve_features(self.features, {"session-autostart"})

        self.assertTrue({"app.google-chrome", "app.caprine", "app.t3code"}.issubset(selected))

    def test_monitor_renderer_rejects_lua_injection(self):
        with self.assertRaises(CatalogError):
            render_monitor("HDMI-A-1", "3440x1440@175", "0x0", "1 }); os.execute('bad')")

    def test_known_ultrawide_nvidia_hardware_is_detected(self):
        monitors = [{"name": "HDMI-A-1", "description": "Microstep MAG 341C OLED"}]
        lspci = SimpleNamespace(stdout="01:00.0 VGA compatible controller: NVIDIA Corporation")

        with patch("bootstrap_cli.monitor_facts", return_value=monitors), patch("bootstrap_cli.shutil.which", return_value="/usr/bin/lspci"), patch("bootstrap_cli.subprocess.run", return_value=lspci):
            self.assertEqual(detect_known_hardware(), "desktop-ultrawide-nvidia")

    def test_multiple_monitors_require_layout_selection(self):
        monitors = [
            {"name": "HDMI-A-1", "description": "Microstep MAG 341C OLED"},
            {"name": "DP-1", "description": "Secondary"},
        ]
        lspci = SimpleNamespace(stdout="01:00.0 VGA compatible controller: NVIDIA Corporation")

        with patch("bootstrap_cli.monitor_facts", return_value=monitors), patch("bootstrap_cli.shutil.which", return_value="/usr/bin/lspci"), patch("bootstrap_cli.subprocess.run", return_value=lspci):
            self.assertIsNone(detect_known_hardware())

    def test_session_units_are_reloaded_but_target_is_not_enabled(self):
        facts = MachineFacts(omarchy_major=4, packages=frozenset(), commands=frozenset())

        with tempfile.TemporaryDirectory() as target:
            plan = build_plan(ROOT, self.features, {"session-autostart"}, "generic", Path(target), facts)

        session_actions = [action for action in plan.actions if action.feature == "session-autostart"]
        self.assertTrue(any(action.kind == "daemon-reload" for action in session_actions))
        self.assertFalse(any(action.kind == "unit" and action.data["name"] == "session-apps.target" for action in session_actions))

    def test_cloud_unit_carries_structured_local_auth_probe(self):
        facts = MachineFacts(omarchy_major=4, packages=frozenset(), commands=frozenset())

        with tempfile.TemporaryDirectory() as target:
            plan = build_plan(ROOT, self.features, {"cloud.onedrive"}, "generic", Path(target), facts)

        unit = next(action for action in plan.actions if action.kind == "unit")
        self.assertEqual(unit.data["auth_probes"], [{"command": "rclone listremotes", "contains": "onedrive:"}])


class ApplyTests(unittest.TestCase):
    def test_apply_is_idempotent_and_audit_is_read_only(self):
        features = load_catalog(ROOT / "features")
        facts = MachineFacts(omarchy_major=4, packages=frozenset(), commands=frozenset())

        with tempfile.TemporaryDirectory() as target_name:
            target = Path(target_name)
            plan = build_plan(ROOT, features, {"core-desktop"}, "generic", target, facts)
            first = apply_plan(ROOT, plan, system_changes=False)
            before = snapshot(target)
            second = apply_plan(ROOT, plan, system_changes=False)
            report = audit_plan(ROOT, plan, facts)
            after = snapshot(target)

        self.assertGreater(first.changed, 0)
        self.assertEqual(second.changed, 0)
        self.assertEqual(before, after)
        self.assertFalse(any(item.status == "FAIL" for item in report if item.kind == "file"))

    def test_apply_rejects_a_modified_plan(self):
        features = load_catalog(ROOT / "features")
        facts = MachineFacts(omarchy_major=4, packages=frozenset(), commands=frozenset())

        with tempfile.TemporaryDirectory() as target:
            plan = build_plan(ROOT, features, {"core-desktop"}, "generic", Path(target), facts)
            modified = replace(plan, default_agent="codex")
            with self.assertRaises(CatalogError):
                apply_plan(ROOT, modified, system_changes=False)

    def test_authenticated_cloud_unit_is_reloaded_and_enabled(self):
        features = load_catalog(ROOT / "features")
        facts = MachineFacts(omarchy_major=4, packages=frozenset({"rclone"}), commands=frozenset({"rclone"}))

        with tempfile.TemporaryDirectory() as target:
            plan = build_plan(ROOT, features, {"cloud.onedrive"}, "generic", Path(target), facts)
            with patch("bootstrap_core._probe", return_value=True), patch("bootstrap_core._action_satisfied", return_value=False), patch("bootstrap_core.subprocess.run") as run:
                apply_plan(ROOT, plan, system_changes=True)

        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn(["systemctl", "--user", "daemon-reload"], commands)
        self.assertIn(["systemctl", "--user", "enable", "--now", "rclone-onedrive.service"], commands)


class SkillPayloadTests(unittest.TestCase):
    def test_all_user_skills_are_indexed_once_for_each_agent(self):
        root = ROOT / "payload" / "user-skills"
        index_lines = (root / ".local" / "share" / "omarchy-bootstrap" / "skills-index.toml").read_text().splitlines()
        skill_ids = [line.split('"')[1] for line in index_lines if line.startswith("id = ")]

        self.assertEqual(len(skill_ids), 83)
        self.assertEqual(len(set(skill_ids)), 83)
        self.assertNotIn("omarchy", skill_ids)
        self.assertNotIn("diagnose-crash", skill_ids)
        for adapter in (root / ".agents" / "skills", root / ".claude" / "skills", root / ".config" / "opencode" / "skills"):
            self.assertEqual({path.name for path in adapter.iterdir()}, set(skill_ids))
            self.assertTrue(all(path.is_symlink() for path in adapter.iterdir()))

    def test_skill_index_hashes_match_the_canonical_trees(self):
        root = ROOT / "payload" / "user-skills" / ".local" / "share" / "omarchy-bootstrap"
        lines = (root / "skills-index.toml").read_text().splitlines()
        expected = {}
        current_id = None
        for line in lines:
            if line.startswith("id = "):
                current_id = line.split('"')[1]
            elif line.startswith("sha256 = ") and current_id:
                expected[current_id] = line.split('"')[1]
        actual = {path.name: skill_tree_hash(path) for path in (root / "agent-skills").iterdir()}

        self.assertEqual(expected, actual)


def snapshot(root: Path) -> str:
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            entries.append((str(path.relative_to(root)), path.read_bytes().hex()))
    return json.dumps(entries, separators=(",", ":"))


def skill_tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(oct(path.lstat().st_mode & 0o777).encode() + b"\0")
        if path.is_symlink():
            digest.update(b"link\0" + os.readlink(path).encode() + b"\0")
        elif path.is_file():
            digest.update(b"file\0" + path.read_bytes() + b"\0")
        elif path.is_dir():
            digest.update(b"dir\0")
    return digest.hexdigest()


if __name__ == "__main__":
    unittest.main()
