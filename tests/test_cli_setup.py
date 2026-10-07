import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bootstrap import cli
from bootstrap.catalog import CatalogError
from bootstrap.domain import WorkflowId
from bootstrap.tui import screens
from bootstrap.tui.model import ChoiceRow, SelectorState


class SetupTests(unittest.TestCase):
    def test_failed_workflow_does_not_stop_later_workflows(self):
        calls = []

        def workflow_command(workflow, operation):
            calls.append((workflow, operation))
            if workflow is WorkflowId.PACKAGES:
                raise CatalogError("package databases are stale")
            return 0

        with mock.patch.object(cli, "confirm", return_value=True), mock.patch.object(
            cli, "workflow_command", side_effect=workflow_command
        ), mock.patch("sys.stdout", io.StringIO()) as output, mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(cli.setup_command(), 1)

        self.assertIn((WorkflowId.INTEGRATIONS, "apply"), calls)
        summary = output.getvalue()
        self.assertIn("Packages       FAIL", summary)
        self.assertIn("Integrations   READY", summary)


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


if __name__ == "__main__":
    unittest.main()
