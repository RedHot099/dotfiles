import hashlib
import json
import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "integrations/common/payload/user-skills/.local/share/arch-hypr-bootstrap"


class SkillPayloadTests(unittest.TestCase):
    def test_all_reviewed_skills_are_indexed_and_linked_for_each_agent(self):
        lines = (STORE / "skills-index.toml").read_text().splitlines()
        skill_ids = [line.split('"')[1] for line in lines if line.startswith("id = ")]

        self.assertEqual(len(skill_ids), 93)
        self.assertEqual(len(set(skill_ids)), 93)
        self.assertNotIn("omarchy", skill_ids)
        self.assertNotIn("diagnose-crash", skill_ids)
        payload = ROOT / "integrations/common/payload/user-skills"
        for adapter in (
            payload / ".agents/skills",
            payload / ".claude/skills",
            payload / ".codex/skills",
            payload / ".config/opencode/skills",
            payload / ".cursor/skills",
        ):
            self.assertEqual({path.name for path in adapter.iterdir()}, set(skill_ids))
            self.assertTrue(all(path.is_symlink() for path in adapter.iterdir()))

    def test_index_hashes_match_canonical_skill_trees(self):
        expected: dict[str, str] = {}
        current_id: str | None = None
        for line in (STORE / "skills-index.toml").read_text().splitlines():
            if line.startswith("id = "):
                current_id = line.split('"')[1]
            elif line.startswith("sha256 = ") and current_id:
                expected[current_id] = line.split('"')[1]
        actual = {
            path.name: tree_hash(path) for path in (STORE / "agent-skills").iterdir()
        }
        self.assertEqual(expected, actual)


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(oct(path.lstat().st_mode & 0o777).encode() + b"\0")
        if path.is_symlink():
            digest.update(b"link\0" + os.readlink(path).encode() + b"\0")
        elif path.is_file():
            digest.update(b"file\0" + path.read_bytes() + b"\0")
        elif path.is_dir():
            digest.update(b"dir\0")
    return digest.hexdigest()


if __name__ == "__main__":
    unittest.main()
