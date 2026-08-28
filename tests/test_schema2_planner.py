import unittest
from pathlib import Path

from bootstrap.catalog import load_workspace
from bootstrap.domain import ActionKind, parse_plan_json
from bootstrap.planner import HostState, PlanInputs, plan_install, resolve_features
from tests.test_schema2_domain import omarchy_probe
from bootstrap.platform import detect_platform
from bootstrap.packages import StaticPackageProvider


ROOT = Path(__file__).resolve().parents[1]


class SchemaTwoPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = load_workspace(ROOT, "omarchy")
        self.facts = detect_platform(omarchy_probe())

    def test_default_plan_uses_schema_two_and_every_selected_payload_entry(self):
        requested = {
            feature.id for feature in self.workspace.public_catalog.values() if feature.default
        }
        selected = resolve_features(self.workspace, requested)
        plan = plan_install(
            ROOT,
            self.workspace,
            self.facts,
            HostState(frozenset(), frozenset()),
            requested,
            PlanInputs("generic", "claude"),
            StaticPackageProvider(),
        )

        expected_files = sum(len(self.workspace.payload[item]) for item in selected)
        actual_files = sum(action.kind is ActionKind.USER_FILE for action in plan.actions)
        self.assertEqual(actual_files, expected_files)
        self.assertEqual(parse_plan_json(plan.to_json()).to_dict(), plan.to_dict())
        self.assertIn("desktop-portable", plan.selected)
        self.assertIn("todoist-helper", plan.selected)

    def test_ssh_requires_reviewed_keys_and_firewall_stays_separate(self):
        state = HostState(frozenset(), frozenset())
        with self.assertRaisesRegex(ValueError, "reviewed GitHub SSH keys"):
            plan_install(
                ROOT,
                self.workspace,
                self.facts,
                state,
                {"ssh-access"},
                PlanInputs("generic", "claude"),
                StaticPackageProvider(),
            )

        key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGbCPBCj8p06IPpbQ3QnAN+H6PA5WIJXKz7GZi5GdLcY test"
        plan = plan_install(
            ROOT,
            self.workspace,
            self.facts,
            state,
            {"ssh-access"},
            PlanInputs("generic", "claude", github_keys={"RedHot099": (key,)}),
            StaticPackageProvider(),
        )
        self.assertIn(ActionKind.AUTHORIZED_SSH_KEYS, {item.kind for item in plan.actions})
        self.assertIn(ActionKind.REPOSITORY_PACKAGES, {item.kind for item in plan.actions})
        self.assertIn(ActionKind.SYSTEM_UNIT, {item.kind for item in plan.actions})
        self.assertNotIn(ActionKind.FIREWALL_RULE, {item.kind for item in plan.actions})


if __name__ == "__main__":
    unittest.main()
