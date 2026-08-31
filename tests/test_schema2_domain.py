import json
import os
import unittest
from dataclasses import dataclass, replace
from pathlib import Path
from unittest.mock import patch

from bootstrap.domain import (
    ActionKind,
    ExecutionPlan,
    PlanHostMismatch,
    PlanSchemaError,
    PlannedAction,
    assert_plan_matches_host,
    parse_plan_json,
)
from bootstrap.platform import PlatformDetectionError, PlatformFacts, detect_platform, parse_os_release
from bootstrap.host import LocalHostProbe


SHA = "a" * 64


@dataclass(frozen=True)
class FixtureProbe:
    release: str
    outputs: dict[tuple[str, ...], str]
    paths: frozenset[str] = frozenset()

    def os_release(self) -> str:
        return self.release

    def command_output(self, argv: tuple[str, ...]) -> str | None:
        return self.outputs.get(argv)

    def path_exists(self, path: str) -> bool:
        return path in self.paths

    def architecture(self) -> str:
        return "x86_64"

    def uid(self) -> int:
        return 1000

    def target_home(self) -> str:
        return "/home/tester"

    def pacman_config_digest(self) -> str:
        return SHA

    def repositories(self) -> tuple[str, ...]:
        return ("core:Required:Sync", "extra:Required:Sync")

    def capabilities(self) -> frozenset[str]:
        return frozenset({"pacman", "graphical-session"})


def omarchy_probe() -> FixtureProbe:
    return FixtureProbe(
        release='NAME="Omarchy"\nID=omarchy\nID_LIKE=arch\n',
        outputs={
            ("omarchy", "version"): "4.0.1",
            ("Hyprland", "--version"): "Hyprland 0.56.2",
            ("uwsm", "--version"): "uwsm 0.24.0",
            ("omarchy-shell", "--version"): "omarchy-shell 1.2.0",
        },
        paths=frozenset({"/usr/share/omarchy"}),
    )


def cachy_probe() -> FixtureProbe:
    return FixtureProbe(
        release='NAME="CachyOS"\nID=cachyos\n',
        outputs={
            ("Hyprland", "--version"): "Hyprland 0.56.2",
            ("uwsm", "--version"): "uwsm 0.24.0",
            ("noctalia", "--version"): "Noctalia 5.0.0",
        },
    )


def make_plan(facts: PlatformFacts) -> ExecutionPlan:
    return ExecutionPlan.create(
        platform=facts.fingerprint(),
        workspace_digest="b" * 64,
        target_home=facts.target_home,
        selected=("core-desktop",),
        dependencies={"core-desktop": ()},
        actions=(
            PlannedAction(
                kind=ActionKind.USER_FILE,
                feature="core-desktop",
                data={"target": ".config/hypr/user.lua", "sha256": "c" * 64, "mode": 420},
            ),
        ),
    )


class PlatformDetectionTests(unittest.TestCase):
    def test_detects_omarchy_from_agreeing_static_and_command_evidence(self):
        facts = detect_platform(omarchy_probe())

        self.assertEqual(facts.platform.value, "omarchy")
        self.assertEqual(facts.omarchy_major, 4)
        self.assertEqual(facts.hyprland_version, "0.56.2")

    def test_detects_cachy_only_with_complete_desktop_contract(self):
        facts = detect_platform(cachy_probe())

        self.assertEqual(facts.platform.value, "cachy")
        self.assertEqual(facts.shell_name, "noctalia")
        self.assertEqual(facts.shell_version, "5.0.0")

    def test_rejects_incomplete_or_contradictory_platform_evidence(self):
        incomplete = replace(cachy_probe(), outputs={("Hyprland", "--version"): "Hyprland 0.56.2"})
        contradictory = replace(cachy_probe(), paths=frozenset({"/usr/share/omarchy"}))

        with self.assertRaisesRegex(PlatformDetectionError, "incomplete"):
            detect_platform(incomplete)
        with self.assertRaisesRegex(PlatformDetectionError, "contradictory"):
            detect_platform(contradictory)

    def test_rejects_cachy_component_versions_outside_reviewed_range(self):
        future = replace(
            cachy_probe(),
            outputs={**cachy_probe().outputs, ("Hyprland", "--version"): "Hyprland 0.57.0"},
        )
        old_shell = replace(
            cachy_probe(),
            outputs={**cachy_probe().outputs, ("noctalia", "--version"): "Noctalia 4.7.7"},
        )
        with self.assertRaisesRegex(PlatformDetectionError, "unsupported Hyprland"):
            detect_platform(future)
        with self.assertRaisesRegex(PlatformDetectionError, "unsupported Noctalia"):
            detect_platform(old_shell)

    def test_parses_os_release_as_data_and_rejects_shell_expansion(self):
        parsed = parse_os_release('NAME="Cachy OS"\nID=cachyos\n')

        self.assertEqual(parsed, {"NAME": "Cachy OS", "ID": "cachyos"})
        with self.assertRaisesRegex(PlatformDetectionError, "unsafe"):
            parse_os_release("ID=$(touch /tmp/must-not-exist)\n")


class SchemaTwoPlanTests(unittest.TestCase):
    def setUp(self):
        self.facts = detect_platform(omarchy_probe())
        self.plan = make_plan(self.facts)

    def test_round_trips_schema_two_plan_and_closed_action(self):
        parsed = parse_plan_json(self.plan.to_json())

        self.assertEqual(parsed.to_dict(), self.plan.to_dict())
        self.assertIs(parsed.actions[0].kind, ActionKind.USER_FILE)

    def test_rejects_unknown_fields_at_each_defined_object_boundary(self):
        raw = self.plan.to_dict()
        raw["surprise"] = True
        with self.assertRaisesRegex(PlanSchemaError, "unknown plan fields"):
            parse_plan_json(json.dumps(raw))

        raw = self.plan.to_dict()
        raw["platform"]["surprise"] = True
        with self.assertRaisesRegex(PlanSchemaError, "unknown platform fields"):
            parse_plan_json(json.dumps(raw))

        raw = self.plan.to_dict()
        raw["actions"][0]["surprise"] = True
        with self.assertRaisesRegex(PlanSchemaError, "unknown action fields"):
            parse_plan_json(json.dumps(raw))

        raw = self.plan.to_dict()
        raw["actions"][0]["data"]["surprise"] = True
        with self.assertRaisesRegex(PlanSchemaError, "unknown user-file data fields"):
            parse_plan_json(json.dumps(raw))

    def test_rejects_unknown_action_kind_schema_one_and_digest_drift(self):
        raw = self.plan.to_dict()
        raw["actions"][0]["kind"] = "run-shell"
        with self.assertRaisesRegex(PlanSchemaError, "unknown action kind"):
            parse_plan_json(json.dumps(raw))

        with self.assertRaisesRegex(PlanSchemaError, "regenerate"):
            parse_plan_json('{"schema": 1}')

        raw = self.plan.to_dict()
        raw["workspace_digest"] = "d" * 64
        with self.assertRaisesRegex(PlanSchemaError, "digest"):
            parse_plan_json(json.dumps(raw))

        with self.assertRaisesRegex(PlanSchemaError, "duplicate JSON field"):
            parse_plan_json('{"schema":2,"schema":2}')

    def test_host_binding_is_checked_before_caller_mutates(self):
        mutations: list[str] = []
        cachy = detect_platform(cachy_probe())

        with self.assertRaisesRegex(PlanHostMismatch, "platform"):
            assert_plan_matches_host(self.plan, cachy)
            mutations.append("changed")

        self.assertEqual(mutations, [])

    def test_host_binding_reports_repository_and_home_drift(self):
        repository_drift = replace(self.facts, repositories=("core:Required:Sync",))
        home_drift = replace(self.facts, target_home="/home/other")

        with self.assertRaisesRegex(PlanHostMismatch, "repositories"):
            assert_plan_matches_host(self.plan, repository_drift)
        with self.assertRaisesRegex(PlanHostMismatch, "target_home"):
            assert_plan_matches_host(self.plan, home_drift)


class RepositoryFingerprintTests(unittest.TestCase):
    def test_capabilities_do_not_depend_on_the_calling_graphical_session(self):
        probe = LocalHostProbe(Path("/home/tester"))

        with patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "instance"}):
            self.assertNotIn("graphical-session", probe.capabilities())

    def test_fingerprint_tracks_repository_order_siglevel_and_usage(self):
        probe = FixtureLocalHostProbe(
            {
                ("pacman-conf", "--repo-list"): "core\ncustom",
                ("pacman-conf", "--verbose", "SigLevel"): "SigLevel = PackageRequired\nSigLevel = PackageTrustedOnly",
                ("pacman-conf", "--verbose", "--repo", "core", "SigLevel", "Usage"): "Usage = All",
                ("pacman-conf", "--verbose", "--repo", "custom", "SigLevel", "Usage"): "SigLevel = PackageOptional\nUsage = Sync",
            }
        )

        self.assertEqual(
            probe.repositories(),
            (
                "core|siglevel=PackageRequired,PackageTrustedOnly|usage=All",
                "custom|siglevel=PackageOptional|usage=Sync",
            ),
        )
        self.assertEqual(len(probe.pacman_config_digest()), 64)


class FixtureLocalHostProbe(LocalHostProbe):
    def __init__(self, outputs: dict[tuple[str, ...], str]):
        super().__init__(Path("/home/tester"))
        self.outputs = outputs

    def command_output(self, argv: tuple[str, ...]) -> str | None:
        return self.outputs.get(argv)


if __name__ == "__main__":
    unittest.main()
