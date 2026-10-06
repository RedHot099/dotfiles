import subprocess
import unittest
from pathlib import Path
from unittest import mock

from bootstrap.catalog import CatalogError, _authentication_table
from bootstrap.domain import ActionKind, IntegrationsRequest, PlatformId
from bootstrap.executor import authenticate
from bootstrap.planner import HostState, action
from bootstrap.planning.model import PackagesEvidence
from bootstrap.platform import detect_platform
from bootstrap.repository import compile_repository
from bootstrap.workflows import plan_integrations
from tests.fixtures import omarchy_probe


ROOT = Path(__file__).resolve().parents[1]


def login(command: tuple[str, ...], probe: tuple[str, ...]):
    return action(
        ActionKind.MANUAL_AUTHENTICATION,
        "example",
        {"label": "Example", "command": command, "probe": probe, "probe_contains": None, "order": 100},
    )


class LoginQueueTests(unittest.TestCase):
    def test_ssh_logins_run_first_in_catalog_order(self):
        repository = compile_repository(ROOT, PlatformId.OMARCHY)
        plan = plan_integrations(
            ROOT,
            repository,
            detect_platform(omarchy_probe()),
            HostState(frozenset(), frozenset()),
            IntegrationsRequest(
                frozenset({"aws", "bitbucket", "docker-hub", "1password", "tailscale", "tool.github"}),
                frozenset({"agent.claude", "agent.cursor"}),
                frozenset(),
                frozenset(),
            ),
            PackagesEvidence.create(
                frozenset(),
                frozenset({"aws", "claude", "cursor-agent", "gh", "ssh", "sshd", "tailscale"}),
            ),
        )

        labels = [
            item.data["label"] for item in plan.actions if item.kind is ActionKind.MANUAL_AUTHENTICATION
        ]
        self.assertEqual(labels[:3], ["SSH key", "GitHub", "Bitbucket"])
        self.assertEqual(
            set(labels[3:]),
            {"1Password", "Claude", "Cursor Agent", "AWS CLI", "Docker Hub", "Tailscale"},
        )
        targets = {item.data.get("target") for item in plan.actions if item.kind is ActionKind.USER_FILE}
        self.assertIn(".local/bin/bootstrap-login", targets)

    def test_declined_login_is_deferred(self):
        with mock.patch("builtins.input", return_value="n"), mock.patch("bootstrap.executor.run") as run:
            self.assertFalse(authenticate(login(("true",), ("true",)), {}))
        run.assert_not_called()

    def test_failed_login_command_is_deferred(self):
        failure = subprocess.CalledProcessError(1, ("false",))
        with mock.patch("builtins.input", return_value="y"), mock.patch(
            "bootstrap.executor.run", side_effect=failure
        ), mock.patch("builtins.print"):
            self.assertFalse(authenticate(login(("false",), ("true",)), {}))

    def test_cancelled_login_is_deferred(self):
        with mock.patch("builtins.input", return_value="y"), mock.patch(
            "bootstrap.executor.run", side_effect=KeyboardInterrupt
        ), mock.patch("builtins.print"):
            self.assertFalse(authenticate(login(("sleep", "9"), ("true",)), {}))

    def test_failed_login_check_is_deferred(self):
        with mock.patch("builtins.input", return_value="y"), mock.patch("bootstrap.executor.run"), mock.patch(
            "builtins.print"
        ):
            self.assertFalse(authenticate(login(("true",), ("false",)), {}))
            self.assertTrue(authenticate(login(("true",), ("true",)), {}))

    def test_authentication_order_is_bounded(self):
        table = {"label": "Example", "command": ["true"], "probe": ["true"]}
        self.assertEqual(_authentication_table(table, Path("example.toml"))[4], 100)
        with self.assertRaisesRegex(CatalogError, "order"):
            _authentication_table({**table, "order": 1000}, Path("example.toml"))
        with self.assertRaisesRegex(CatalogError, "order"):
            _authentication_table({**table, "order": True}, Path("example.toml"))


if __name__ == "__main__":
    unittest.main()
