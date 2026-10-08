import unittest
from pathlib import Path

from bootstrap.domain import FeatureId, PlatformId, WorkflowId
from bootstrap.domain import ActionKind, DesktopRequest, IntegrationsRequest, PackagesRequest
from bootstrap.planning.model import PackagesEvidence
from bootstrap.planner import HostState
from bootstrap.platform import detect_platform
from bootstrap.packages import StaticPackageProvider
from bootstrap.repository import compile_repository
from bootstrap.workflows import plan_desktop, plan_integrations, plan_packages
from tests.fixtures import omarchy_probe


ROOT = Path(__file__).resolve().parents[1]


class RepositoryCompilerTests(unittest.TestCase):
    def test_compiler_exposes_all_workflows(self):
        repository = compile_repository(ROOT, PlatformId.OMARCHY)

        self.assertEqual(set(repository.workflows), set(WorkflowId))
        self.assertTrue(repository.source_digest)

    def test_feature_ids_are_scoped_by_workflow(self):
        packages = FeatureId(WorkflowId.PACKAGES, "editor")
        desktop = FeatureId(WorkflowId.DESKTOP, "editor")

        self.assertNotEqual(packages, desktop)

    def test_curated_application_defaults_match_the_approved_set(self):
        repository = compile_repository(ROOT, PlatformId.OMARCHY)
        selected = {
            item.id
            for item in repository.applications.values()
            if item.default and item.visible
        }

        self.assertEqual(
            selected,
            {
                "aws-cli", "caprine", "chromium", "cursor", "github-cli",
                "google-chrome", "mise", "neovim", "obsidian", "rust",
                "signal", "spotify", "steam", "t3-code", "tailscale",
                "typora", "vesktop", "visual-studio-code",
            },
        )

    def test_hardware_tools_are_optional_and_have_hints(self):
        repository = compile_repository(ROOT, PlatformId.OMARCHY)

        for identifier in ("solaar", "cooler-control"):
            with self.subTest(application=identifier):
                application = repository.applications[identifier]
                self.assertFalse(application.default)
                self.assertIsNotNone(application.hardware_hint)

    def test_every_curated_package_requirement_has_a_binding(self):
        repository = compile_repository(ROOT, PlatformId.OMARCHY)
        required = {
            requirement
            for application in repository.applications.values()
            for requirement in application.requirements
        }

        self.assertLessEqual(required, set(repository.package_bindings))

    def test_packages_plan_contains_only_package_actions(self):
        repository = compile_repository(ROOT, PlatformId.OMARCHY)
        facts = detect_platform(omarchy_probe())
        selected = frozenset(
            item.id for item in repository.applications.values() if item.default
        )

        plan = plan_packages(
            repository,
            facts,
            HostState(frozenset(), frozenset()),
            PackagesRequest(selected),
            StaticPackageProvider(),
        )

        self.assertEqual(plan.header.workflow, WorkflowId.PACKAGES)
        self.assertTrue(plan.actions)
        self.assertLessEqual(
            {item.kind for item in plan.actions},
            {ActionKind.REPOSITORY_PACKAGES, ActionKind.AUR_BUILD, ActionKind.PINNED_TOOL},
        )

    def test_feature_id_rejects_unsafe_names(self):
        with self.assertRaisesRegex(ValueError, "invalid feature id"):
            FeatureId(WorkflowId.PACKAGES, "../editor")

    def test_integrations_report_missing_package_workflow_prerequisites(self):
        repository = compile_repository(ROOT, PlatformId.OMARCHY)
        facts = detect_platform(omarchy_probe())

        with self.assertRaisesRegex(Exception, "NEEDS PACKAGES: tailscale"):
            plan_integrations(
                ROOT,
                repository,
                facts,
                HostState(frozenset(), frozenset()),
                IntegrationsRequest(frozenset({"tailscale"}), frozenset(), frozenset(), frozenset()),
                PackagesEvidence.create(frozenset(), frozenset()),
            )

    def test_agents_need_no_package_because_omarchy_provides_them(self):
        plan = plan_integrations(
            ROOT,
            compile_repository(ROOT, PlatformId.OMARCHY),
            detect_platform(omarchy_probe()),
            HostState(frozenset(), frozenset()),
            IntegrationsRequest(frozenset(), frozenset({"agent.codex"}), frozenset(), frozenset()),
            PackagesEvidence.create(frozenset(), frozenset()),
        )
        self.assertIn("agent.codex", {item.feature for item in plan.actions})

    def test_desktop_and_integrations_cannot_plan_package_mutations(self):
        repository = compile_repository(ROOT, PlatformId.OMARCHY)
        facts = detect_platform(omarchy_probe())
        state = HostState(frozenset(), frozenset())
        evidence = PackagesEvidence.create(frozenset(), frozenset())

        desktop = plan_desktop(
            ROOT,
            repository,
            facts,
            state,
            DesktopRequest(frozenset(), "generic"),
            evidence,
        )
        integrations = plan_integrations(
            ROOT,
            repository,
            facts,
            state,
            IntegrationsRequest(frozenset(), frozenset(), frozenset(), frozenset()),
            evidence,
        )

        forbidden = {
            ActionKind.REPOSITORY_PACKAGES,
            ActionKind.AUR_BUILD,
            ActionKind.PINNED_TOOL,
        }
        self.assertFalse(forbidden.intersection(item.kind for item in desktop.actions))
        self.assertFalse(forbidden.intersection(item.kind for item in integrations.actions))
        self.assertNotEqual(desktop.digest, integrations.digest)


if __name__ == "__main__":
    unittest.main()
