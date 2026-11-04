import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("update_external_skills", ROOT / "scripts/update-external-skills.py")
updater = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = updater
SPEC.loader.exec_module(updater)

OLD = "a" * 40
NEW = "b" * 40


class ExternalSkillUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = Path(tempfile.mkdtemp())
        self.root = self.temporary / "repo"
        self.upstream = self.temporary / "upstream"
        self.layout = updater.Layout(self.root)
        common = self.root / "integrations/common"
        (common / "skills/private").mkdir(parents=True)
        self.layout.store.mkdir(parents=True)
        (common / "harnesses.toml").write_text(
            'schema = 1\n\n[[harnesses]]\nid = "claude"\ntarget = ".claude/skills"\n\n'
            '[[harnesses]]\nid = "opencode"\ntarget = ".config/opencode/skills"\n'
        )
        self.write_sources(["alpha", "beta"])
        self.write_user_skill("mine")
        self.write_upstream("alpha", "first")
        self.write_upstream("beta", "second")
        (self.upstream / "LICENSE").write_text("MIT\n")
        self.original = (updater.resolve_latest, updater.checkout)
        updater.resolve_latest = lambda source: NEW
        updater.checkout = lambda source, commit, workdir: self.upstream

    def tearDown(self):
        updater.resolve_latest, updater.checkout = self.original
        shutil.rmtree(self.temporary)

    def write_sources(self, skills):
        listed = ", ".join(f'"{skill}"' for skill in skills)
        self.layout.sources.write_text(
            'schema = 1\n\n[[sources]]\nid = "up"\nurl = "https://example.com/up"\nref = "main"\n'
            f'commit = "{OLD}"\npath = "skills"\nlicense = "LICENSE"\nskills = [{listed}]\n'
        )

    def write_user_skill(self, skill_id):
        for root in (self.layout.private, self.layout.store):
            (root / skill_id).mkdir()
            (root / skill_id / "SKILL.md").write_text(f"---\nname: {skill_id}\n---\n")
        digest = updater.capture.tree_hash(self.layout.store / skill_id)
        self.layout.index.write_text(
            f'schema = 1\ncount = 1\n\n[[skills]]\nid = "{skill_id}"\norigin = ".agents"\nsha256 = "{digest}"\n'
        )

    def write_upstream(self, skill_id, body):
        tree = self.upstream / "skills" / skill_id
        tree.mkdir(parents=True, exist_ok=True)
        (tree / "SKILL.md").write_text(f"---\nname: {skill_id}\n---\n{body}\n")

    def test_installs_links_indexes_and_pins_without_touching_user_skills(self):
        self.assertEqual(updater.run(self.layout, set(), check=False), 0)

        index = updater.read_index(self.layout)
        self.assertEqual(index["alpha"][0], f"up@{NEW}")
        self.assertEqual(index["mine"][0], ".agents")
        self.assertTrue((self.layout.private / "alpha/LICENSE").is_file())
        link = self.layout.payload / ".config/opencode/skills/alpha"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), (self.layout.store / "alpha").resolve())
        self.assertIn(f'commit = "{NEW}"', self.layout.sources.read_text())
        self.assertIn("count = 3", self.layout.index.read_text())

    def test_dropping_a_skill_removes_only_that_skill(self):
        updater.run(self.layout, set(), check=False)
        self.write_sources(["alpha"])

        self.assertEqual(updater.run(self.layout, set(), check=False), 0)

        self.assertFalse((self.layout.private / "beta").exists())
        self.assertFalse((self.layout.store / "beta").exists())
        self.assertFalse(os.path.lexists(self.layout.payload / ".claude/skills/beta"))
        self.assertNotIn("beta", updater.read_index(self.layout))
        self.assertTrue((self.layout.private / "mine").is_dir())

    def test_refuses_to_overwrite_a_user_skill(self):
        self.write_sources(["alpha", "mine"])
        self.write_upstream("mine", "upstream copy")

        with self.assertRaisesRegex(updater.UpdateError, "mine already exists"):
            updater.run(self.layout, set(), check=False)
        self.assertNotIn("alpha", updater.read_index(self.layout))

    def test_rejects_symlinks_in_upstream_skills(self):
        (self.upstream / "skills/alpha/escape").symlink_to("/etc/passwd")

        with self.assertRaisesRegex(updater.UpdateError, "symlinks are not allowed"):
            updater.run(self.layout, set(), check=False)

    def test_check_reports_updates_without_writing(self):
        before = self.layout.sources.read_text()

        self.assertEqual(updater.run(self.layout, set(), check=True), 2)

        self.assertEqual(self.layout.sources.read_text(), before)
        self.assertFalse((self.layout.private / "alpha").exists())


if __name__ == "__main__":
    unittest.main()
