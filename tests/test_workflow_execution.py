import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from bootstrap.domain import PackagesRequest, PlatformId, WorkflowId
from bootstrap.execution import apply_workflow_plan
from bootstrap.planning.model import PackagesPlan, PlanHeader
from bootstrap.platform import detect_platform
from bootstrap.repository import compile_repository
from tests.fixtures import cachy_probe


ROOT = Path(__file__).resolve().parents[1]


class WorkflowExecutionTests(unittest.TestCase):
    def test_empty_package_apply_is_idempotent_in_isolated_home(self):
        repository = compile_repository(ROOT, PlatformId.CACHY)
        with tempfile.TemporaryDirectory() as directory:
            facts = replace(detect_platform(cachy_probe()), target_home=directory)
            plan = PackagesPlan.create(
                PlanHeader(3, WorkflowId.PACKAGES, facts.fingerprint(), repository.source_digest, directory),
                PackagesRequest(frozenset()),
                (),
            )

            first = apply_workflow_plan(ROOT, repository, plan, facts, system_changes=False, interactive=False)
            second = apply_workflow_plan(ROOT, repository, plan, facts, system_changes=False, interactive=False)

            self.assertEqual(first.changed, 0)
            self.assertEqual(second.changed, 0)
            self.assertEqual(second.simulated, 0)


if __name__ == "__main__":
    unittest.main()
