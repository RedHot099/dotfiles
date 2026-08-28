import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from bootstrap.audit import audit_install
from bootstrap.catalog import CatalogError, load_workspace
from bootstrap.domain import PlanHostMismatch
from bootstrap.executor import apply_install
from bootstrap.planner import HostState, PlanInputs, plan_install
from bootstrap.platform import detect_platform
from bootstrap.packages import StaticPackageProvider
from tests.test_schema2_domain import cachy_probe, omarchy_probe


ROOT = Path(__file__).resolve().parents[1]


class SchemaTwoExecutorTests(unittest.TestCase):
    @patch("bootstrap.executor.apply_repository_packages", return_value=True)
    @patch("bootstrap.executor.review_aur_actions")
    @patch("bootstrap.executor.os.geteuid", return_value=1000)
    def test_real_package_apply_receives_platform_facts(
        self, _geteuid, _review_aur, apply_repository_packages
    ):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            facts = replace(detect_platform(cachy_probe()), target_home=str(home))
            workspace = load_workspace(ROOT, "cachy")
            plan = plan_install(
                ROOT,
                workspace,
                facts,
                HostState(frozenset(), frozenset()),
                {"system.tailscale"},
                PlanInputs("generic", "claude"),
                StaticPackageProvider(),
            )

            apply_install(
                ROOT, workspace, plan, facts, system_changes=True, interactive=True
            )

            package_action = next(
                action for action in plan.actions if action.kind.value == "repository-packages"
            )
            apply_repository_packages.assert_called_once_with(
                package_action, workspace, facts
            )

    def test_isolated_apply_converges_and_audit_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            facts = replace(detect_platform(omarchy_probe()), target_home=str(home))
            workspace = load_workspace(ROOT, "omarchy")
            requested = {
                feature.id for feature in workspace.public_catalog.values() if feature.default
            }
            plan = plan_install(
                ROOT,
                workspace,
                facts,
                HostState(frozenset(), frozenset()),
                requested,
                PlanInputs("generic", "claude"),
                StaticPackageProvider(),
            )

            first = apply_install(
                ROOT, workspace, plan, facts, system_changes=False, interactive=False
            )
            second = apply_install(
                ROOT, workspace, plan, facts, system_changes=False, interactive=False
            )
            before = snapshot(home)
            findings = audit_install(workspace, plan, facts)
            after = snapshot(home)

            self.assertGreater(first.changed, 0)
            self.assertEqual(second.changed, 0)
            self.assertEqual(before, after)
            self.assertFalse(any(item.status == "FAIL" for item in findings))

    def test_host_and_workspace_drift_fail_before_creating_target_home(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "must-not-exist"
            facts = replace(detect_platform(omarchy_probe()), target_home=str(home))
            workspace = load_workspace(ROOT, "omarchy")
            plan = plan_install(
                ROOT,
                workspace,
                facts,
                HostState(frozenset(), frozenset()),
                set(),
                PlanInputs("generic", "claude"),
                StaticPackageProvider(),
            )

            cachy = replace(detect_platform(cachy_probe()), target_home=str(home))
            with self.assertRaises(PlanHostMismatch):
                apply_install(
                    ROOT, workspace, plan, cachy, system_changes=False, interactive=False
                )
            self.assertFalse(home.exists())

            drifted = replace(workspace, source_digest="f" * 64)
            with self.assertRaisesRegex(CatalogError, "workspace changed"):
                apply_install(
                    ROOT, drifted, plan, facts, system_changes=False, interactive=False
                )
            self.assertFalse(home.exists())

    def test_cachy_payload_and_managed_fragment_converge_without_claiming_gated_features(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            root_config = home / ".config/hypr/hyprland.lua"
            root_config.parent.mkdir(parents=True)
            root_config.write_text('-- distro-owned\nrequire("config.variables")\n')
            facts = replace(detect_platform(cachy_probe()), target_home=str(home))
            workspace = load_workspace(ROOT, "cachy")
            requested = {
                feature.id for feature in workspace.public_catalog.values() if feature.default
            }
            plan = plan_install(
                ROOT,
                workspace,
                facts,
                HostState(frozenset(), frozenset()),
                requested,
                PlanInputs("generic", "claude"),
                StaticPackageProvider(),
            )

            first = apply_install(
                ROOT, workspace, plan, facts, system_changes=False, interactive=False
            )
            second = apply_install(
                ROOT, workspace, plan, facts, system_changes=False, interactive=False
            )
            findings = audit_install(workspace, plan, facts)

            self.assertGreater(first.changed, 0)
            self.assertEqual(second.changed, 0)
            self.assertIn('-- distro-owned\nrequire("config.variables")', root_config.read_text())
            self.assertEqual(root_config.read_text().count("BEGIN arch-hypr-bootstrap"), 1)
            self.assertEqual(
                set(plan.unavailable), {"notifications-calendar", "themes", "todoist"}
            )
            self.assertFalse(any(item.status == "FAIL" for item in findings))

def snapshot(root: Path) -> tuple[tuple[str, str, bytes], ...]:
    result: list[tuple[str, str, bytes]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            result.append((relative, "symlink", path.readlink().as_posix().encode()))
        elif path.is_file():
            result.append((relative, "file", path.read_bytes()))
    return tuple(result)


if __name__ == "__main__":
    unittest.main()
