import tempfile
import unittest
from pathlib import Path

from bootstrap.domain import WorkflowId
from bootstrap.state import SelectionRecord, StateStore


class WorkflowStateTests(unittest.TestCase):
    def test_selection_round_trip_is_private_and_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            store = StateStore(home)
            record = SelectionRecord(
                WorkflowId.PACKAGES,
                frozenset({"cursor", "chromium"}),
                "a" * 64,
            )

            store.write_selection(record)
            target = home / ".local/state/arch-hypr-bootstrap/selections/packages.json"
            first = target.read_bytes()
            store.write_selection(record)

            self.assertEqual(store.read_selection(WorkflowId.PACKAGES), record)
            self.assertEqual(target.read_bytes(), first)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)

    def test_each_workflow_has_independent_selection_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory) / "home")
            packages = SelectionRecord(WorkflowId.PACKAGES, frozenset({"cursor"}), "a" * 64)
            desktop = SelectionRecord(WorkflowId.DESKTOP, frozenset({"calendar"}), "b" * 64)

            store.write_selection(packages)
            store.write_selection(desktop)

            self.assertEqual(store.read_selection(WorkflowId.PACKAGES), packages)
            self.assertEqual(store.read_selection(WorkflowId.DESKTOP), desktop)
            self.assertIsNone(store.read_selection(WorkflowId.INTEGRATIONS))


if __name__ == "__main__":
    unittest.main()
