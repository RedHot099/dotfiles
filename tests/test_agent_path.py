import json
import os
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from bootstrap import agent, cli
from bootstrap.domain import DesktopRequest, IntegrationsRequest, PlatformId, WorkflowId
from bootstrap.execution import apply_workflow_plan
from bootstrap.executor import LocalEditConflict, NeedsTerminal, restore_files
from bootstrap.planner import HostState
from bootstrap.planning.model import PackagesEvidence
from bootstrap.platform import detect_platform
from bootstrap.repository import compile_repository
from bootstrap.session import session_environment
from bootstrap.state import SelectionRecord, StateStore
from bootstrap.workflows import plan_desktop, plan_integrations
from tests.fixtures import omarchy_probe


ROOT = Path(__file__).resolve().parents[1]


def managed_files(home: Path) -> dict[str, str]:
    from bootstrap.state import read_managed

    with cli.HomeFiles(home) as files:
        return read_managed(files, "desktop")
CLEAN_MAIN = {"git": True, "branch": "main", "commit": "c" * 40, "dirty": False}
BINDINGS = ".config/hypr/bindings.lua"


class AgentPathCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = compile_repository(ROOT, PlatformId.OMARCHY)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        self.facts = replace(detect_platform(omarchy_probe()), target_home=str(self.home))
        self.state = HostState(frozenset(), frozenset(), gpu_vendors=frozenset({"amd"}))
        applications = self.repository.applications.values()
        self.evidence = PackagesEvidence.create(
            frozenset(item.id for item in applications if item.default),
            frozenset(command for item in applications for command in item.commands) | {"ssh", "sshd", "rclone"},
        )

    def defaults(self, workflow):
        catalog = self.repository.workflow(workflow).workspace.public_catalog
        return frozenset(item.id for item in catalog.values() if item.default and item.visible)

    def desktop_plan(self):
        return plan_desktop(
            ROOT, self.repository, self.facts, self.state,
            DesktopRequest(self.defaults(WorkflowId.DESKTOP), "generic"), self.evidence,
        )

    def integrations_plan(self):
        selected = self.defaults(WorkflowId.INTEGRATIONS)
        agents = frozenset(item for item in selected if item.startswith("agent."))
        return plan_integrations(
            ROOT, self.repository, self.facts, self.state,
            IntegrationsRequest(selected - agents, agents), self.evidence,
        )

    def apply(self, plan, **options):
        return apply_workflow_plan(
            ROOT, self.repository, plan, self.facts, system_changes=False, interactive=False, **options
        )


class NonInteractiveApplyTests(AgentPathCase):
    def test_terminal_actions_stop_before_any_change(self):
        plan = self.integrations_plan()
        with mock.patch("bootstrap.executor.terminal_action_satisfied", return_value=False), mock.patch(
            "bootstrap.executor.run"
        ) as run:
            with self.assertRaises(NeedsTerminal) as caught:
                apply_workflow_plan(
                    ROOT, self.repository, plan, self.facts, system_changes=True, interactive=False, reviewed=True
                )
        self.assertTrue(any(item.startswith("system-unit:") for item in caught.exception.pending))
        run.assert_not_called()
        self.assertFalse((self.home / ".config").exists())

    def test_logins_and_reload_are_deferred_without_prompts(self):
        plan = self.integrations_plan()
        with mock.patch("bootstrap.executor.terminal_action_satisfied", return_value=True), mock.patch(
            "bootstrap.executor.action_satisfied", return_value=False
        ), mock.patch("bootstrap.executor.run_probe", return_value=False), mock.patch(
            "bootstrap.executor.run"
        ), mock.patch("bootstrap.executor.ask_yes_no", side_effect=AssertionError("prompted")):
            result = apply_workflow_plan(
                ROOT, self.repository, plan, self.facts, system_changes=True, interactive=False, reviewed=True
            )
        reasons = {item.reason for item in result.deferred}
        self.assertIn("needs-login", reasons)
        self.assertIn("waiting-for-login", reasons)
        self.assertGreater(result.changed, 0)

        desktop = self.desktop_plan()
        with mock.patch("bootstrap.executor.session_environment", return_value=None), mock.patch(
            "bootstrap.executor.run"
        ), mock.patch("bootstrap.executor.apply_repository"), mock.patch(
            "bootstrap.executor.action_satisfied", return_value=False
        ):
            result = apply_workflow_plan(
                ROOT, self.repository, desktop, self.facts, system_changes=True, interactive=False, reviewed=True
            )
        self.assertEqual([item.reason for item in result.deferred], ["needs-session"])


class FailedApplyTests(AgentPathCase):
    def test_files_from_a_failed_apply_stay_managed(self):
        plan = self.desktop_plan()
        with mock.patch("bootstrap.executor.run"), mock.patch("bootstrap.executor.apply_repository"), mock.patch(
            "bootstrap.executor.action_satisfied", return_value=False
        ), mock.patch("bootstrap.executor.reload_hyprland", side_effect=RuntimeError("configerrors")):
            with self.assertRaises(RuntimeError):
                apply_workflow_plan(
                    ROOT, self.repository, plan, self.facts, system_changes=True, interactive=False, reviewed=True
                )
        managed = managed_files(self.home)
        self.assertIn(BINDINGS, managed)


class UserUnitTests(AgentPathCase):
    def test_changed_unit_file_restarts_a_running_unit(self):
        plan = self.integrations_plan()
        units = [item for item in plan.actions if item.kind.value == "user-unit"]
        self.assertTrue(units)
        with mock.patch("bootstrap.executor.terminal_action_satisfied", return_value=True), mock.patch(
            "bootstrap.executor.action_satisfied", return_value=True
        ), mock.patch("bootstrap.executor.run_probe", return_value=True), mock.patch("bootstrap.executor.run") as run:
            apply_workflow_plan(ROOT, self.repository, plan, self.facts, system_changes=True, interactive=False, reviewed=True)
            calls = [call.args[0] for call in run.call_args_list]
            for unit in units:
                self.assertIn(("/usr/bin/systemctl", "--user", "restart", unit.data["name"]), calls)
            run.reset_mock()
            apply_workflow_plan(ROOT, self.repository, plan, self.facts, system_changes=True, interactive=False, reviewed=True)
            self.assertFalse([call for call in run.call_args_list if "restart" in call.args[0]])


class ResumeTests(AgentPathCase):
    def test_a_resumed_apply_still_restarts_a_changed_unit(self):
        plan = self.integrations_plan()

        def failing_restart(argv, **_):
            if "restart" in argv:
                raise RuntimeError("restart failed")

        with mock.patch("bootstrap.executor.terminal_action_satisfied", return_value=True), mock.patch(
            "bootstrap.executor.action_satisfied", return_value=True
        ), mock.patch("bootstrap.executor.run", side_effect=failing_restart):
            with self.assertRaises(RuntimeError):
                apply_workflow_plan(ROOT, self.repository, plan, self.facts, system_changes=True, interactive=False, reviewed=True)
        with mock.patch("bootstrap.executor.terminal_action_satisfied", return_value=True), mock.patch(
            "bootstrap.executor.action_satisfied", return_value=True
        ), mock.patch("bootstrap.executor.run") as run:
            apply_workflow_plan(ROOT, self.repository, plan, self.facts, system_changes=True, interactive=False, reviewed=True)
        self.assertTrue([call for call in run.call_args_list if "restart" in call.args[0]])


class FirewallTests(unittest.TestCase):
    def test_root_only_rules_need_no_handoff_but_a_terminal_apply_re_adds(self):
        from bootstrap import audit, executor
        from bootstrap.domain import ActionKind
        from bootstrap.planner import action

        item = action(ActionKind.FIREWALL_RULE, "ssh-firewall", {"backend": "ufw", "rule": "limit", "port": 22, "protocol": "tcp"})
        with tempfile.TemporaryDirectory() as directory, cli.HomeFiles(Path(directory)) as home, mock.patch.object(
            executor.Path, "read_text", side_effect=PermissionError
        ):
            self.assertIsNone(executor.ufw_rule_present())
            self.assertTrue(executor.terminal_action_satisfied(item, home))
            self.assertFalse(executor.action_satisfied(item, home))
            self.assertEqual(audit.audit_action(item, home, False).status, "WARN")


class InterruptionTests(AgentPathCase):
    def test_interrupted_apply_remembers_created_files_for_restore(self):
        plan = self.desktop_plan()
        from bootstrap import executor

        real = executor.apply_file_action
        calls = []

        def flaky(*args):
            calls.append(args)
            if len(calls) == 5:
                raise KeyboardInterrupt
            return real(*args)

        with mock.patch("bootstrap.executor.apply_file_action", side_effect=flaky):
            with self.assertRaises(KeyboardInterrupt):
                self.apply(plan, reviewed=True)
        result = restore_files(self.home, plan.actions, plan.digest, "desktop", discard_local=False)
        self.assertEqual(len(result.removed), 4)
        self.assertEqual(result.restored, ())


class LocalEditTests(AgentPathCase):
    def test_reviewed_apply_refuses_edited_and_unmanaged_files(self):
        plan = self.desktop_plan()
        self.apply(plan, reviewed=True)
        managed = managed_files(self.home)
        self.assertIn(BINDINGS, managed)
        self.assertEqual(self.apply(plan, reviewed=True).changed, 0)

        bindings = self.home / BINDINGS
        bindings.write_text("-- edited by hand\n")
        with self.assertRaises(LocalEditConflict) as caught:
            self.apply(plan, reviewed=True)
        self.assertEqual(caught.exception.targets, (BINDINGS,))
        self.assertEqual(bindings.read_text(), "-- edited by hand\n")

        self.assertEqual(self.apply(plan, reviewed=True, discard_local=True).changed, 1)
        backup = self.home / ".local/state/arch-hypr-bootstrap/backups" / plan.digest / BINDINGS
        self.assertEqual(backup.read_text(), "-- edited by hand\n")

    def test_reapplying_after_a_local_edit_keeps_both_backups(self):
        plan = self.desktop_plan()
        target = self.home / BINDINGS
        target.parent.mkdir(parents=True)
        target.write_text("-- before\n")
        self.apply(plan, reviewed=True, discard_local=True)
        target.write_text("-- edited after the apply\n")
        self.apply(plan, reviewed=True, discard_local=True)
        backups = self.home / ".local/state/arch-hypr-bootstrap/backups" / plan.digest
        self.assertEqual((backups / BINDINGS).read_text(), "-- before\n")
        superseded = [path.read_text() for path in (backups / ".superseded").rglob("bindings.lua")]
        self.assertEqual(superseded, ["-- edited after the apply\n"])

    def test_unmanaged_file_needs_discard_local_but_legacy_apply_replaces_it(self):
        plan = self.desktop_plan()
        target = self.home / BINDINGS
        target.parent.mkdir(parents=True)
        target.write_text("-- omarchy default\n")
        with self.assertRaises(LocalEditConflict):
            self.apply(plan, reviewed=True)
        self.assertGreater(self.apply(plan).changed, 0)
        self.assertNotEqual(target.read_text(), "-- omarchy default\n")

    def test_update_of_managed_file_is_not_a_conflict(self):
        plan = self.desktop_plan()
        self.apply(plan, reviewed=True)
        item = next(entry for entry in plan.actions if entry.data.get("target") == BINDINGS)
        changed = replace(item, data={**item.data, "sha256": "0" * 64})
        with cli.HomeFiles(self.home) as home:
            managed = managed_files(self.home)
            self.assertEqual(cli.agent.file_change(home, changed, managed), "update")
            self.assertEqual(cli.agent.file_change(home, item, managed), "unchanged")


class RestoreTests(AgentPathCase):
    def test_restore_brings_back_replaced_files_and_removes_created_ones(self):
        plan = self.desktop_plan()
        target = self.home / BINDINGS
        target.parent.mkdir(parents=True)
        target.write_text("-- before\n")
        self.apply(plan, reviewed=True, discard_local=True)
        created = self.home / ".config/hypr/looknfeel.lua"
        self.assertTrue(created.exists())

        result = restore_files(self.home, plan.actions, plan.digest, "desktop", discard_local=False)
        self.assertIn(BINDINGS, result.restored)
        self.assertIn(".config/hypr/looknfeel.lua", result.removed)
        self.assertEqual(target.read_text(), "-- before\n")
        self.assertFalse(created.exists())
        # Restored files count as managed, so the next update replaces them freely.
        self.assertIn(BINDINGS, managed_files(self.home))
        # A second restore finds nothing left to do.
        again = restore_files(self.home, plan.actions, plan.digest, "desktop", discard_local=False)
        self.assertEqual((again.restored, again.removed), ((), ()))

    def test_restore_keeps_a_previously_managed_file_managed(self):
        monitors = ".config/hypr/monitors.lua"

        def plan_with(content):
            return plan_desktop(
                ROOT, self.repository, self.facts, self.state,
                DesktopRequest(self.defaults(WorkflowId.DESKTOP), "detected"), self.evidence,
                monitor_content=content,
            )

        first, second = plan_with("-- first\n"), plan_with("-- second\n")
        self.apply(first, reviewed=True)
        self.apply(second, reviewed=True)
        self.assertEqual((self.home / monitors).read_text(), "-- second\n")
        restore_files(self.home, second.actions, second.digest, "desktop", discard_local=False)
        self.assertEqual((self.home / monitors).read_text(), "-- first\n")
        # The restored content is the bootstrap's own, so the next update is no conflict.
        self.apply(plan_with("-- third\n"), reviewed=True)
        self.assertEqual((self.home / monitors).read_text(), "-- third\n")

    def test_restore_puts_back_the_mode_too(self):
        plan = self.desktop_plan()
        item = next(
            entry for entry in plan.actions
            if entry.kind.value == "user-file" and entry.data["mode"] & 0o111 and entry.data.get("symlink") is None
        )
        target = self.home / str(item.data["target"])
        source = next(
            entry for entry in self.repository.workflow(WorkflowId.DESKTOP).workspace.payload[item.feature]
            if entry.target == item.data["target"]
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / str(source.source)).read_bytes())
        # Planned modes follow the checkout's umask; drop only the execute bits.
        before = int(item.data["mode"]) & ~0o111
        target.chmod(before)
        self.apply(plan, reviewed=True)
        self.assertEqual(target.stat().st_mode & 0o777, item.data["mode"])
        result = restore_files(self.home, plan.actions, plan.digest, "desktop", discard_local=False)
        self.assertIn(str(item.data["target"]), result.restored)
        self.assertEqual(target.stat().st_mode & 0o777, before)

    def test_resumed_restore_settles_the_manifest(self):
        monitors = ".config/hypr/monitors.lua"

        def plan_with(content):
            return plan_desktop(
                ROOT, self.repository, self.facts, self.state,
                DesktopRequest(self.defaults(WorkflowId.DESKTOP), "detected"), self.evidence,
                monitor_content=content,
            )

        first, second = plan_with("-- first\n"), plan_with("-- second\n")
        self.apply(first, reviewed=True)
        self.apply(second, reviewed=True)
        # An interrupted restore put the file back but never wrote the manifest.
        (self.home / monitors).write_text("-- first\n")
        restore_files(self.home, second.actions, second.digest, "desktop", discard_local=False)
        self.apply(plan_with("-- third\n"), reviewed=True)
        self.assertEqual((self.home / monitors).read_text(), "-- third\n")

    def test_restore_refuses_files_edited_after_the_apply(self):
        plan = self.desktop_plan()
        self.apply(plan, reviewed=True)
        edited = self.home / ".config/hypr/looknfeel.lua"
        edited.write_text("-- mine\n")
        with self.assertRaises(LocalEditConflict):
            restore_files(self.home, plan.actions, plan.digest, "desktop", discard_local=False)
        self.assertEqual(edited.read_text(), "-- mine\n")

    def test_restore_needs_a_journal(self):
        plan = self.desktop_plan()
        with self.assertRaisesRegex(Exception, "never applied"):
            restore_files(self.home, plan.actions, plan.digest, "desktop", discard_local=False)


class CliCase(AgentPathCase):
    def setUp(self):
        super().setUp()
        self.reports = []
        patches = [
            mock.patch.dict(os.environ, {"HOME": str(self.home)}),
            mock.patch.object(cli, "detect_platform", return_value=self.facts),
            mock.patch.object(cli, "compile_repository", return_value=self.repository),
            mock.patch.object(
                cli,
                "detect_host_state",
                return_value=replace(self.state, commands=frozenset(self.evidence.installed)),
            ),
            mock.patch.object(cli, "detect_monitor_content", return_value=None),
            mock.patch.object(cli.agent, "emit", side_effect=lambda _fd, report: self.reports.append(report)),
            mock.patch.object(cli.agent, "checkout_state", return_value=CLEAN_MAIN),
            mock.patch("bootstrap.agent.run_probe", return_value=False),
            # Never reach the real user manager or Hyprland session.
            mock.patch.object(cli, "run"),
            mock.patch("bootstrap.executor.session_environment", return_value=None),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        store = StateStore(self.home)
        store.write_selection(SelectionRecord(WorkflowId.PACKAGES, self.evidence.selected, "x"))

    def run_cli(self, *argv):
        code = cli.main(list(argv))
        return code, self.reports[-1]


class CliJsonTests(CliCase):
    def test_desktop_plan_needs_the_session(self):
        with mock.patch.object(cli, "session_environment", return_value=None):
            code, report = self.run_cli("desktop", "plan", "--json")
        self.assertEqual((code, report["status"]), (3, "NEEDS_SESSION"))

    def test_plan_apply_and_status_round_trip(self):
        with mock.patch.object(cli, "session_environment", return_value={}):
            code, plan = self.run_cli("desktop", "plan", "--json", "--remove", "vscode")
        self.assertEqual((code, plan["status"]), (0, "PLANNED"))
        self.assertNotIn("vscode", plan["selection"]["selected"])
        self.assertGreater(len(plan["changes"]["files"]["create"]), 0)
        record = StateStore(self.home).read_selection(WorkflowId.DESKTOP)
        self.assertIn("vscode", record.known)
        self.assertNotIn("vscode", record.selected)

        digest = plan["plan_digest"]
        with mock.patch.object(cli.agent, "checkout_state", return_value={**CLEAN_MAIN, "dirty": True}):
            code, blocked = self.run_cli("desktop", "apply", "--plan", digest, "--json")
        self.assertEqual((code, blocked["status"]), (3, "BLOCKED"))
        self.assertFalse((self.home / BINDINGS).exists())

        with mock.patch("bootstrap.executor.session_environment", return_value=None), mock.patch(
            "bootstrap.executor.run"
        ), mock.patch("bootstrap.executor.apply_repository"), mock.patch(
            "bootstrap.executor.action_satisfied", return_value=False
        ):
            code, applied = self.run_cli("desktop", "apply", "--plan", digest, "--json")
        self.assertEqual((code, applied["status"]), (3, "INCOMPLETE"))
        self.assertEqual(applied["deferred"][0]["reason"], "needs-session")
        self.assertTrue((self.home / BINDINGS).exists())

        code, status = self.run_cli("desktop", "status", "--plan", digest, "--json")
        self.assertEqual((code, status["status"]), (3, "INCOMPLETE"))
        code, other = self.run_cli("desktop", "status", "--plan", "f" * 64, "--json")
        self.assertEqual(other["status"], "NO_RESULT")

        with mock.patch.object(cli, "reload_hyprland", return_value=True) as reload:
            code, restored = self.run_cli("desktop", "restore", "--plan", digest, "--json")
            self.assertEqual((code, restored["status"]), (0, "RESTORED"))
            self.assertFalse((self.home / BINDINGS).exists())
            # A repeated restore changes nothing but still reloads and checks.
            code, again = self.run_cli("desktop", "restore", "--plan", digest, "--json")
            self.assertEqual((code, again["removed"]), (0, []))
            self.assertEqual(reload.call_count, 2)
        _, pending = self.run_cli("desktop", "restore", "--plan", digest, "--json")
        self.assertEqual(pending["status"], "INCOMPLETE")

    def test_new_catalog_items_are_reported_not_selected(self):
        visible = cli.visible_catalog(self.repository, WorkflowId.DESKTOP)
        StateStore(self.home).write_selection(
            SelectionRecord(WorkflowId.DESKTOP, frozenset({"core-desktop"}), "x", frozenset(visible) - {"vscode"})
        )
        with mock.patch.object(cli, "session_environment", return_value={}):
            _, plan = self.run_cli("desktop", "plan", "--json")
        self.assertEqual([item["id"] for item in plan["selection"]["new_items"]], ["vscode"])
        self.assertNotIn("vscode", plan["selection"]["selected"])
        # Reported again by the next plan, until the selection is changed.
        with mock.patch.object(cli, "session_environment", return_value={}):
            _, again = self.run_cli("desktop", "plan", "--json")
            self.assertEqual([item["id"] for item in again["selection"]["new_items"]], ["vscode"])
            self.run_cli("desktop", "plan", "--json", "--remove", "vscode")
            _, seen = self.run_cli("desktop", "plan", "--json")
        self.assertEqual(seen["selection"]["new_items"], [])

    def test_restore_restarts_only_units_it_put_back(self):
        unit = self.home / ".config/systemd/user/rclone-onedrive.service"
        unit.parent.mkdir(parents=True)
        unit.write_text("[Service]\nExecStart=/bin/true\n")
        with mock.patch.object(cli, "fetch_github_keys", return_value=()):
            _, plan = self.run_cli("integrations", "plan", "--json")
        digest = plan["plan_digest"]
        with mock.patch("bootstrap.executor.terminal_action_satisfied", return_value=True), mock.patch(
            "bootstrap.executor.action_satisfied", return_value=True
        ), mock.patch("bootstrap.executor.run"):
            self.run_cli("integrations", "apply", "--plan", digest, "--json", "--discard-local")

        cli.run.reset_mock()
        code, restored = self.run_cli("integrations", "restore", "--plan", digest, "--json")
        self.assertEqual((code, restored["status"]), (0, "RESTORED"))
        self.assertEqual(unit.read_text(), "[Service]\nExecStart=/bin/true\n")
        restarts = [call.args[0][-1] for call in cli.run.call_args_list if "try-restart" in call.args[0]]
        self.assertEqual(restarts, ["rclone-onedrive.service"])

    def test_privileged_plan_is_handed_to_a_terminal(self):
        with mock.patch.object(cli, "fetch_github_keys", return_value=()):
            _, plan = self.run_cli("integrations", "plan", "--json")
        digest = plan["plan_digest"]
        with mock.patch("bootstrap.executor.terminal_action_satisfied", return_value=False):
            code, report = self.run_cli("integrations", "apply", "--plan", digest, "--json", "--discard-local")
            self.assertEqual((code, report["status"]), (3, "NEEDS_TERMINAL"))
            self.assertIn("--in-terminal", report["next_actions"][0]["command"])
            self.assertFalse((self.home / ".config").exists())

            with mock.patch.object(cli, "session_environment", return_value=None):
                _, report = self.run_cli("integrations", "apply", "--plan", digest, "--json", "--in-terminal")
            self.assertEqual(report["status"], "NEEDS_TERMINAL")
            self.assertIn(f"apply --plan {digest}", report["next_actions"][0]["command"])

            with mock.patch.object(cli, "session_environment", return_value={"PATH": ""}), mock.patch.object(
                cli.agent, "launch_terminal"
            ) as launch:
                _, report = self.run_cli("integrations", "apply", "--plan", digest, "--json", "--in-terminal")
            self.assertEqual(report["status"], "HANDED_OFF")
            self.assertEqual(launch.call_args.args[0][-3:], ["apply", "--plan", digest])

        code, status = self.run_cli("integrations", "status", "--plan", digest, "--json")
        self.assertEqual((code, status["status"]), (3, "HANDED_OFF"))

    def test_the_terminal_asks_before_trusting_ssh_keys(self):
        with mock.patch.object(cli, "session_environment", return_value={}):
            _, plan = self.run_cli("desktop", "plan", "--json")
        with mock.patch.object(cli, "terminal_pending", return_value=("authorized-ssh-keys: ssh-access",)), mock.patch.object(
            cli, "confirm", return_value=False
        ) as confirm:
            report, code = cli.approved_apply(WorkflowId.DESKTOP, plan["plan_digest"], discard_local=False, in_terminal=False, prompts=True)
        confirm.assert_called_once()
        self.assertEqual((code, report["status"]), (1, "DECLINED"))
        self.assertFalse((self.home / BINDINGS).exists())

    def test_restore_disables_units_the_plan_created(self):
        with mock.patch.object(cli, "fetch_github_keys", return_value=()):
            _, plan = self.run_cli("integrations", "plan", "--json")
        digest = plan["plan_digest"]
        with mock.patch("bootstrap.executor.terminal_action_satisfied", return_value=True), mock.patch(
            "bootstrap.executor.action_satisfied", return_value=True
        ), mock.patch("bootstrap.executor.run"):
            self.run_cli("integrations", "apply", "--plan", digest, "--json")
        with mock.patch.object(cli.subprocess, "run") as systemctl:
            code, report = self.run_cli("integrations", "restore", "--plan", digest, "--json")
        self.assertEqual((code, report["status"]), (0, "RESTORED"))
        self.assertIn(
            ("/usr/bin/systemctl", "--user", "disable", "--now", "rclone-onedrive.service"),
            [call.args[0] for call in systemctl.call_args_list],
        )
        self.assertFalse((self.home / ".config/systemd/user/rclone-onedrive.service").exists())

    def test_a_second_apply_reports_busy(self):
        with mock.patch.object(cli, "session_environment", return_value={}):
            _, plan = self.run_cli("desktop", "plan", "--json")
        state = self.home / ".local/state/arch-hypr-bootstrap"
        import fcntl

        with open(state / "apply.lock", "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            code, report = self.run_cli("desktop", "apply", "--plan", plan["plan_digest"], "--json")
        self.assertEqual((code, report["status"]), (3, "BUSY"))
        self.assertFalse((self.home / BINDINGS).exists())

    def test_stale_and_unknown_plans(self):
        code, report = self.run_cli("desktop", "apply", "--plan", "a" * 64, "--json")
        self.assertEqual((code, report["status"]), (3, "STALE"))
        with mock.patch.object(cli, "session_environment", return_value={}):
            _, plan = self.run_cli("desktop", "plan", "--json")
        changed = replace(self.repository, source_digest="0" * 64)
        with mock.patch.object(cli, "compile_repository", return_value=changed):
            code, report = self.run_cli("desktop", "apply", "--plan", plan["plan_digest"], "--json")
        self.assertEqual((code, report["status"]), (3, "STALE"))
        with mock.patch.object(cli.time, "sleep", side_effect=AssertionError("waited")):
            _, other = self.run_cli("desktop", "status", "--plan", "b" * 64, "--wait", "900", "--json")
        self.assertEqual(other["status"], "NO_RESULT")
        for argv in (["desktop", "apply", "--json"], ["desktop", "plan", "--plan", "a" * 64], ["desktop", "plan", "--add", "vscode"]):
            with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                cli.main(argv)

    def test_stale_package_databases_ask_for_a_system_update(self):
        error = cli.CatalogError("package databases are stale or missing for omarchy; run omarchy update, then generate a new plan")
        with mock.patch.object(cli, "plan_packages", side_effect=error):
            code, report = self.run_cli("packages", "plan", "--json")
        self.assertEqual((code, report["status"]), (3, "NEEDS_SYSTEM_UPDATE"))
        self.assertEqual(report["next_actions"][0]["who"], "user")

    def test_interrupted_apply_is_reported(self):
        child = subprocess.Popen(("true",))
        child.wait()
        StateStore(self.home).write_result(
            WorkflowId.DESKTOP,
            agent.result_record("desktop", "d" * 64, "RUNNING", 3, pid=child.pid),
        )
        code, report = self.run_cli("desktop", "status", "--json")
        self.assertEqual((code, report["status"]), (3, "INTERRUPTED"))


class UpdateCycleTests(CliCase):
    """The runbook end to end through the CLI: install, a repository update,
    a local edit, its conflict, and a restore. Only system calls are stubbed."""

    def setUp(self):
        super().setUp()
        checkout = tempfile.TemporaryDirectory()
        self.addCleanup(checkout.cleanup)
        self.root = Path(checkout.name) / "dotfiles"
        shutil.copytree(ROOT, self.root, symlinks=True, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        patches = [
            mock.patch.object(cli, "ROOT", self.root),
            mock.patch.object(cli, "compile_repository", side_effect=compile_repository),
            mock.patch.object(cli, "session_environment", return_value={}),
            mock.patch("bootstrap.executor.run"),
            mock.patch("bootstrap.executor.apply_repository"),
            mock.patch("bootstrap.executor.action_satisfied", return_value=False),
            mock.patch("bootstrap.executor.reload_hyprland", return_value=True),
            mock.patch.object(cli, "reload_hyprland", return_value=True),
            mock.patch("bootstrap.audit.action_satisfied", return_value=True),
            mock.patch("bootstrap.audit.session_environment", return_value=None),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def plan(self):
        code, report = self.run_cli("desktop", "plan", "--json")
        self.assertEqual((code, report["status"]), (0, "PLANNED"))
        return report

    def apply(self, digest, *extra):
        return self.run_cli("desktop", "apply", "--plan", digest, "--json", *extra)

    def test_install_update_conflict_and_restore(self):
        bindings = self.home / BINDINGS
        installed = self.plan()
        self.assertEqual(installed["changes"]["files"]["update"], [])
        code, report = self.apply(installed["plan_digest"])
        self.assertEqual((code, report["status"]), (0, "READY"))
        first = bindings.read_text()

        # Nothing left to do: the fresh plan is empty and the audit is clean.
        again = self.plan()
        self.assertEqual(again["plan_digest"], installed["plan_digest"])
        self.assertEqual((again["changes"]["files"]["create"], again["changes"]["files"]["update"]), ([], []))
        code, audit = self.run_cli("desktop", "audit", "--plan", again["plan_digest"], "--json")
        self.assertEqual((code, audit["status"]), (0, "CLEAN"))

        # A pulled commit changes one payload file: the old plan is stale and
        # the new plan updates exactly that file without asking anyone.
        payload = self.root / "desktop/omarchy/payload/core-desktop" / BINDINGS
        payload.write_text(payload.read_text() + "-- pulled change\n")
        code, stale = self.apply(installed["plan_digest"])
        self.assertEqual((code, stale["status"]), (3, "STALE"))
        updated = self.plan()
        self.assertEqual(updated["changes"]["files"]["update"], [BINDINGS])
        self.assertEqual(updated["changes"]["files"]["local-edit"], [])
        code, report = self.apply(updated["plan_digest"])
        self.assertEqual((code, report["status"]), (0, "READY"))
        self.assertTrue(bindings.read_text().endswith("-- pulled change\n"))

        # A hand edit blocks the next update until the user approves it.
        payload.write_text(payload.read_text() + "-- second change\n")
        bindings.write_text(bindings.read_text() + "-- my tweak\n")
        edited = self.plan()
        self.assertEqual(edited["changes"]["files"]["local-edit"], [BINDINGS])
        code, report = self.apply(edited["plan_digest"])
        self.assertEqual((code, report["status"], report["conflicts"]), (3, "CONFLICT", [BINDINGS]))
        self.assertIn("-- my tweak", bindings.read_text())
        code, report = self.apply(edited["plan_digest"], "--discard-local")
        self.assertEqual((code, report["status"]), (0, "READY"))
        self.assertTrue(bindings.read_text().endswith("-- second change\n"))

        # A file dropped from the repository is reported, never deleted.
        dropped = ".config/nvim/lua/plugins/theme.lua"
        source = next(self.root.glob(f"desktop/*/payload/*/{dropped}"))
        source.unlink()
        orphaned = self.plan()
        self.assertEqual(orphaned["changes"]["files"]["orphaned"], [dropped])
        code, report = self.apply(orphaned["plan_digest"])
        self.assertEqual((code, report["status"]), (0, "READY"))
        # Reported once: the apply keeps the file and stops tracking it.
        self.assertTrue(os.path.lexists(self.home / dropped))
        self.assertEqual(self.plan()["changes"]["files"]["orphaned"], [])

        # Restore undoes that apply: the hand edit comes back from its backup.
        code, report = self.run_cli("desktop", "restore", "--plan", edited["plan_digest"], "--json")
        self.assertEqual((code, report["status"], report["restored"]), (0, "RESTORED", [BINDINGS]))
        self.assertTrue(bindings.read_text().endswith("-- my tweak\n"))
        self.assertNotEqual(bindings.read_text(), first)


class SelectionStateTests(unittest.TestCase):
    def test_schema_one_records_still_read(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            store = StateStore(home)
            store.write_selection(SelectionRecord(WorkflowId.DESKTOP, frozenset({"b", "a"}), "x"))
            record = store.read_selection(WorkflowId.DESKTOP)
            self.assertEqual((record.selected, record.known), (frozenset({"a", "b"}), None))
            store.write_selection(SelectionRecord(WorkflowId.DESKTOP, frozenset({"a"}), "x", frozenset({"a", "c"})))
            self.assertEqual(store.read_selection(WorkflowId.DESKTOP).known, frozenset({"a", "c"}))


class SessionTests(unittest.TestCase):
    def test_reads_only_session_keys_from_the_user_manager(self):
        with tempfile.TemporaryDirectory() as runtime:
            output = "HYPRLAND_INSTANCE_SIGNATURE=abc\nWAYLAND_DISPLAY=wayland-1\nUNRELATED_VARIABLE=x\n"
            completed = subprocess.CompletedProcess((), 0, output)
            environment = {"XDG_RUNTIME_DIR": runtime, "PATH": "/usr/bin"}
            with mock.patch.dict(os.environ, environment, clear=True), mock.patch(
                "bootstrap.session.subprocess.run", return_value=completed
            ):
                self.assertIsNone(session_environment())
                Path(runtime, "hypr/abc").mkdir(parents=True)
                Path(runtime, "hypr/abc/.socket.sock").touch()
                session = session_environment()
        self.assertEqual(session["HYPRLAND_INSTANCE_SIGNATURE"], "abc")
        self.assertEqual(session["WAYLAND_DISPLAY"], "wayland-1")
        self.assertNotIn("UNRELATED_VARIABLE", session)


class EmitTests(unittest.TestCase):
    def test_a_partial_write_is_completed(self):
        written = []

        def short_write(_descriptor, data):
            chunk = bytes(data[:7])
            written.append(chunk)
            return len(chunk)

        with mock.patch("bootstrap.agent.os.write", side_effect=short_write):
            agent.emit(1, {"status": "READY", "files": ["x" * 50]})
        self.assertEqual(json.loads(b"".join(written)), {"status": "READY", "files": ["x" * 50]})


class JsonStdoutTests(unittest.TestCase):
    def test_child_output_goes_to_stderr(self):
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            saved_out, saved_err = os.dup(1), os.dup(2)
            os.dup2(out.fileno(), 1)
            os.dup2(err.fileno(), 2)
            try:
                with agent.json_stdout() as descriptor:
                    subprocess.run(("echo", "noise"), check=True)
                    print("more noise", flush=True)
                    agent.emit(descriptor, {"status": "READY"})
            finally:
                os.dup2(saved_out, 1)
                os.dup2(saved_err, 2)
                os.close(saved_out)
                os.close(saved_err)
            out.seek(0)
            err.seek(0)
            self.assertEqual(json.loads(out.read()), {"status": "READY"})
            self.assertIn(b"noise", err.read())


if __name__ == "__main__":
    unittest.main()
