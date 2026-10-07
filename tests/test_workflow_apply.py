import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from bootstrap.domain import DesktopRequest, IntegrationsRequest, PackagesRequest, PlatformId, WorkflowId
from bootstrap.execution import apply_workflow_plan, execution_plan
from bootstrap.packages import StaticPackageProvider
from bootstrap.planner import HostState
from bootstrap.planning.model import PackagesEvidence
from bootstrap.platform import detect_platform
from bootstrap.repository import compile_repository
from bootstrap.workflows import plan_desktop, plan_integrations, plan_packages
from tests.fixtures import omarchy_probe


ROOT = Path(__file__).resolve().parents[1]


class DefaultPlanApplyTests(unittest.TestCase):
    """Real catalog plans must pass execution validation, not only empty ones."""

    @classmethod
    def setUpClass(cls):
        cls.repository = compile_repository(ROOT, PlatformId.OMARCHY)

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.facts = replace(detect_platform(omarchy_probe()), target_home=self.home.name)
        self.state = HostState(frozenset(), frozenset(), gpu_vendors=frozenset({"amd"}))
        applications = self.repository.applications.values()
        self.evidence = PackagesEvidence.create(
            frozenset(item.id for item in applications if item.default),
            frozenset(command for item in applications for command in item.commands)
            | {"ssh", "sshd", "rclone"},
        )

    def defaults(self, workflow: WorkflowId) -> frozenset[str]:
        catalog = self.repository.workflow(workflow).workspace.public_catalog
        return frozenset(item.id for item in catalog.values() if item.default and item.visible)

    def apply(self, plan):
        return apply_workflow_plan(
            ROOT, self.repository, plan, self.facts, system_changes=False, interactive=False
        )

    def test_default_packages_plan_is_executable(self):
        plan = plan_packages(
            self.repository,
            self.facts,
            self.state,
            PackagesRequest(frozenset(item.id for item in self.repository.applications.values() if item.default)),
            StaticPackageProvider(),
        )
        self.assertTrue(plan.actions)
        execution = execution_plan(self.repository, plan)
        self.assertTrue({item.feature for item in plan.actions} <= set(execution.selected))
        self.assertGreater(self.apply(plan).simulated, 0)

    def test_default_desktop_plan_applies_idempotently(self):
        plan = plan_desktop(
            ROOT,
            self.repository,
            self.facts,
            self.state,
            DesktopRequest(self.defaults(WorkflowId.DESKTOP), "generic"),
            self.evidence,
        )
        self.assertGreater(self.apply(plan).changed, 0)
        self.assertEqual(self.apply(plan).changed, 0)

    def test_default_integrations_plan_applies_idempotently(self):
        selected = self.defaults(WorkflowId.INTEGRATIONS)
        agents = frozenset(item for item in selected if item.startswith("agent."))
        plan = plan_integrations(
            ROOT,
            self.repository,
            self.facts,
            self.state,
            IntegrationsRequest(selected - agents, agents, frozenset(), frozenset()),
            self.evidence,
        )
        self.assertGreater(self.apply(plan).changed, 0)
        self.assertEqual(self.apply(plan).changed, 0)


if __name__ == "__main__":
    unittest.main()
