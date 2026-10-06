import json
import unittest

from bootstrap.domain import PackagesRequest, PlatformId, WorkflowId
from bootstrap.planning.model import PackagesPlan, PlanHeader, plan_from_dict
from bootstrap.platform import detect_platform
from tests.fixtures import omarchy_probe


class WorkflowPlanTests(unittest.TestCase):
    def test_schema_three_package_plan_round_trips(self):
        facts = detect_platform(omarchy_probe())
        header = PlanHeader(3, WorkflowId.PACKAGES, facts.fingerprint(), "a" * 64, facts.target_home)
        original = PackagesPlan.create(header, PackagesRequest(frozenset({"neovim"})), ())

        parsed = plan_from_dict(json.loads(json.dumps(original.to_dict())))

        self.assertEqual(parsed, original)

    def test_digest_tampering_is_rejected(self):
        facts = detect_platform(omarchy_probe())
        header = PlanHeader(3, WorkflowId.PACKAGES, facts.fingerprint(), "a" * 64, facts.target_home)
        data = PackagesPlan.create(header, PackagesRequest(frozenset()), ()).to_dict()
        data["request"]["applications"] = ["neovim"]

        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            plan_from_dict(data)


if __name__ == "__main__":
    unittest.main()
