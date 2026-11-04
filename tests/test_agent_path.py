import json
import os
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


class LocalEditTests(AgentPathCase):
    def test_reviewed_apply_refuses_edited_and_unmanaged_files(self):
        plan = self.desktop_plan()
        self.apply(plan, reviewed=True)
        managed = StateStore(self.home).read_managed(WorkflowId.DESKTOP)
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
            managed = StateStore(self.home).read_managed(WorkflowId.DESKTOP)
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
        self.assertNotIn(BINDINGS, StateStore(self.home).read_managed(WorkflowId.DESKTOP))
        # A second restore finds nothing left to do.
        again = restore_files(self.home, plan.actions, plan.digest, "desktop", discard_local=False)
        self.assertEqual((again.restored, again.removed), ((), ()))

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


class CliJsonTests(AgentPathCase):
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
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        store = StateStore(self.home)
        store.write_selection(SelectionRecord(WorkflowId.PACKAGES, self.evidence.selected, "x"))

    def run_cli(self, *argv):
        code = cli.main(list(argv))
        return code, self.reports[-1]

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

        code, restored = self.run_cli("desktop", "restore", "--plan", digest, "--json")
        self.assertEqual(restored["operation"], "restore")
        self.assertFalse((self.home / BINDINGS).exists())

    def test_new_catalog_items_are_reported_not_selected(self):
        visible = cli.visible_catalog(self.repository, WorkflowId.DESKTOP)
        StateStore(self.home).write_selection(
            SelectionRecord(WorkflowId.DESKTOP, frozenset({"core-desktop"}), "x", frozenset(visible) - {"vscode"})
        )
        with mock.patch.object(cli, "session_environment", return_value={}):
            _, plan = self.run_cli("desktop", "plan", "--json")
        self.assertEqual([item["id"] for item in plan["selection"]["new_items"]], ["vscode"])
        self.assertNotIn("vscode", plan["selection"]["selected"])

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

    def test_stale_and_unknown_plans(self):
        code, report = self.run_cli("desktop", "apply", "--plan", "a" * 64, "--json")
        self.assertEqual((code, report["status"]), (3, "STALE"))
        code, report = self.run_cli("desktop", "apply", "--json")
        self.assertEqual((code, report["status"]), (2, "FAIL"))
        with self.assertRaises(SystemExit):
            cli.main(["desktop", "plan", "--plan", "a" * 64])

    def test_interrupted_apply_is_reported(self):
        child = subprocess.Popen(("true",))
        child.wait()
        StateStore(self.home).write_result(
            WorkflowId.DESKTOP,
            agent.result_record("desktop", "d" * 64, "RUNNING", 3, pid=child.pid),
        )
        code, report = self.run_cli("desktop", "status", "--json")
        self.assertEqual((code, report["status"]), (3, "INTERRUPTED"))


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
