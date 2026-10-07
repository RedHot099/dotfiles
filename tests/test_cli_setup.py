import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bootstrap import cli
from bootstrap.catalog import CatalogError
from bootstrap.domain import WorkflowId
from bootstrap.executor import planned_package_paths
from bootstrap.tui import screens
from bootstrap.tui import terminal as terminal_module
from bootstrap.tui.model import ChoiceRow, SelectorState


class SetupTests(unittest.TestCase):
    def test_failed_workflow_does_not_stop_later_workflows(self):
        calls = []

        def workflow_command(workflow, operation):
            calls.append((workflow, operation))
            if workflow is WorkflowId.PACKAGES:
                raise CatalogError("package databases are stale")
            if workflow is WorkflowId.DESKTOP and operation == "apply":
                return cli.EXIT_DECLINED
            if workflow is WorkflowId.INTEGRATIONS and operation == "apply":
                return cli.EXIT_INCOMPLETE
            return 0

        with mock.patch.object(cli, "confirm", return_value=True), mock.patch.object(
            cli, "workflow_command", side_effect=workflow_command
        ), mock.patch("sys.stdout", io.StringIO()) as output, mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(cli.setup_command(), 1)

        self.assertIn((WorkflowId.INTEGRATIONS, "apply"), calls)
        summary = output.getvalue()
        self.assertIn("Packages       FAIL", summary)
        self.assertIn("Desktop        SKIPPED", summary)
        self.assertIn("Integrations   INCOMPLETE", summary)


class HardwareHintTests(unittest.TestCase):
    def test_hint_needs_detected_hardware(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "1-1").mkdir()
            (root / "1-1/idVendor").write_text("1d6b\n")
            self.assertFalse(cli._usb_vendor_present("046d", root))
            (root / "1-2").mkdir()
            (root / "1-2/idVendor").write_text("046d\n")
            self.assertTrue(cli._usb_vendor_present("046d", root))

        with mock.patch.dict(cli.HARDWARE_PROBES, {"solaar": lambda: False}):
            self.assertIsNone(cli.hardware_hint("solaar", "Logitech receiver detected"))
        with mock.patch.dict(cli.HARDWARE_PROBES, {"solaar": lambda: True}):
            self.assertEqual(cli.hardware_hint("solaar", "Logitech receiver detected"), "Logitech receiver detected")
        self.assertIsNone(cli.hardware_hint("steam", None))


class RenderTests(unittest.TestCase):
    def test_lines_return_to_column_zero_in_raw_mode(self):
        state = SelectorState((ChoiceRow("steam", "Gaming", "Steam", True),))
        with mock.patch("sys.stdout", io.StringIO()) as output:
            screens._render("Select applications", state)
        text = output.getvalue()
        self.assertNotIn("\n", text.replace("\r\n", ""))
        self.assertIn("\r\n", text)


class TypeaheadTests(unittest.TestCase):
    def test_question_discards_keys_pressed_before_it(self):
        terminal = mock.Mock()
        terminal.isatty.return_value = True
        terminal.fileno.return_value = 7
        with mock.patch("termios.tcflush") as flush, mock.patch("builtins.input", return_value="y"):
            self.assertTrue(terminal_module.ask_yes_no("Apply?", terminal))
        flush.assert_called_once_with(7, terminal_module.termios.TCIFLUSH)


class AurPackageListTests(unittest.TestCase):
    def test_debug_package_listed_but_not_built_is_ignored(self):
        lines = [
            "/build/caprine/caprine-2.61.0-1-any.pkg.tar.zst",
            "/build/caprine/caprine-debug-2.61.0-1-any.pkg.tar.zst",
        ]
        self.assertEqual(
            planned_package_paths(lines, ("caprine",)),
            (Path("/build/caprine/caprine-2.61.0-1-any.pkg.tar.zst"),),
        )

    def test_epoch_versions_and_split_packages_are_matched(self):
        lines = ["/b/aws-cli-bin-1:2.36.32-1-x86_64.pkg.tar.zst", "/b/a-lib-1.0-1-x86_64.pkg.tar.zst", "/b/a-1.0-1-x86_64.pkg.tar.zst"]
        self.assertEqual(len(planned_package_paths(lines, ("aws-cli-bin", "a", "a-lib"))), 3)

    def test_missing_planned_package_yields_nothing(self):
        self.assertEqual(planned_package_paths(["/b/caprine-debug-1-1-any.pkg.tar.zst"], ("caprine",)), ())


if __name__ == "__main__":
    unittest.main()
