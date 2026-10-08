import unittest
from pathlib import Path

from bootstrap.domain import ActionKind, PackagesRequest, PlatformId
from bootstrap.packages import StaticPackageProvider, version_at_least
from bootstrap.planner import HostState
from bootstrap.platform import detect_platform
from bootstrap.repository import compile_repository
from bootstrap.workflows import plan_packages
from tests.fixtures import omarchy_probe


ROOT = Path(__file__).resolve().parents[1]


class AurVersionTests(unittest.TestCase):
    def test_newer_or_equal_install_satisfies_a_pin(self):
        self.assertTrue(version_at_least("1:2.37.10-1", "1:2.36.32-1"))
        self.assertTrue(version_at_least("1:2.36.32-1", "1:2.36.32-1"))
        self.assertFalse(version_at_least("1:2.35.0-1", "1:2.36.32-1"))
        self.assertFalse(version_at_least("2.61.0-1", "1:2.0-1"))
        self.assertFalse(version_at_least(None, "1.0-1"))

    def test_updated_aur_package_is_not_rebuilt(self):
        repository = compile_repository(ROOT, PlatformId.OMARCHY)

        def aur_actions(installed: str):
            plan = plan_packages(
                repository,
                detect_platform(omarchy_probe()),
                HostState(frozenset({"aws-cli-bin"}), frozenset(), {"aws-cli-bin": installed}),
                PackagesRequest(frozenset({"aws-cli"})),
                StaticPackageProvider(),
            )
            return [item for item in plan.actions if item.kind is ActionKind.AUR_BUILD]

        self.assertEqual(aur_actions("fixture-2"), [])
        self.assertEqual(len(aur_actions("fixture-0")), 1)


if __name__ == "__main__":
    unittest.main()
