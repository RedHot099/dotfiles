import unittest
from pathlib import Path

from bootstrap.domain import FeatureId, PlatformId, WorkflowId
from bootstrap.repository import compile_repository


ROOT = Path(__file__).resolve().parents[1]


class RepositoryCompilerTests(unittest.TestCase):
    def test_compiler_exposes_all_workflows_for_each_platform(self):
        for platform in PlatformId:
            with self.subTest(platform=platform):
                repository = compile_repository(ROOT, platform)
                self.assertEqual(set(repository.workflows), set(WorkflowId))
                self.assertTrue(repository.source_digest)

    def test_feature_ids_are_scoped_by_workflow(self):
        packages = FeatureId(WorkflowId.PACKAGES, "editor")
        desktop = FeatureId(WorkflowId.DESKTOP, "editor")

        self.assertNotEqual(packages, desktop)

    def test_curated_application_defaults_match_the_approved_set(self):
        repository = compile_repository(ROOT, PlatformId.CACHY)
        selected = {item.id for item in repository.applications.values() if item.default}

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
        repository = compile_repository(ROOT, PlatformId.CACHY)

        for identifier in ("solaar", "cooler-control"):
            with self.subTest(application=identifier):
                application = repository.applications[identifier]
                self.assertFalse(application.default)
                self.assertIsNotNone(application.hardware_hint)

    def test_every_curated_package_requirement_has_a_platform_binding(self):
        for platform in PlatformId:
            with self.subTest(platform=platform):
                repository = compile_repository(ROOT, platform)
                required = {
                    requirement
                    for application in repository.applications.values()
                    for requirement in application.requirements
                }
                self.assertLessEqual(required, set(repository.package_bindings))

    def test_feature_id_rejects_unsafe_names(self):
        with self.assertRaisesRegex(ValueError, "invalid feature id"):
            FeatureId(WorkflowId.PACKAGES, "../editor")


if __name__ == "__main__":
    unittest.main()
