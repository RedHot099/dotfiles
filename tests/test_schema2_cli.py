import json
import tempfile
import unittest
from pathlib import Path

from bootstrap.catalog import CatalogError
from bootstrap.cli import render_monitor, write_plan
from bootstrap.planner import HostState, PlanInputs, plan_install
from bootstrap.catalog import load_workspace
from bootstrap.platform import detect_platform
from tests.test_schema2_domain import omarchy_probe


ROOT = Path(__file__).resolve().parents[1]


class SchemaTwoCliTests(unittest.TestCase):
    def test_monitor_renderer_rejects_injected_values(self):
        content = render_monitor("DP-1", "2560x1440@144", "0x0", "1")
        self.assertIn('output = "DP-1"', content)
        with self.assertRaisesRegex(CatalogError, "invalid monitor output"):
            render_monitor('DP-1" }) os.execute("bad")', "preferred", "auto", "1")

    def test_plan_writer_only_changes_the_requested_file(self):
        workspace = load_workspace(ROOT, "omarchy")
        facts = detect_platform(omarchy_probe())
        plan = plan_install(
            ROOT,
            workspace,
            facts,
            HostState(frozenset(), frozenset()),
            set(),
            PlanInputs("generic", "claude"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            untouched = root / "untouched"
            untouched.write_text("same")
            target = root / "nested/plan.json"
            write_plan(target, plan)
            self.assertEqual(json.loads(target.read_text())["schema"], 2)
            self.assertEqual(untouched.read_text(), "same")
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
