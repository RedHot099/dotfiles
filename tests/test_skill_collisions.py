import tempfile
import unittest
from pathlib import Path

from bootstrap.files import HomeFiles


class SkillCollisionTests(unittest.TestCase):
    def test_exact_directory_removal_preserves_protected_sibling(self):
        with tempfile.TemporaryDirectory() as directory:
            home_path = Path(directory)
            collision = home_path / ".codex/skills/research"
            protected = home_path / ".codex/skills/.system"
            collision.mkdir(parents=True)
            protected.mkdir()
            (collision / "SKILL.md").write_text("old")
            (protected / "marker").write_text("keep")

            with HomeFiles(home_path) as home:
                home.remove_exact(".codex/skills/research")

            self.assertFalse(collision.exists())
            self.assertEqual((protected / "marker").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
