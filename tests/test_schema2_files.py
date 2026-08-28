import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from bootstrap.files import FileBoundaryError, HomeFiles


class HomeFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / "home"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_atomic_install_is_idempotent_and_backs_up_previous_bytes(self):
        target = self.home / ".config/app/config"
        target.parent.mkdir(parents=True)
        target.write_text("old")
        content = b"new\n"
        digest = hashlib.sha256(content).hexdigest()

        with HomeFiles(self.home) as files:
            self.assertTrue(
                files.install(
                    ".config/app/config",
                    content=content,
                    symlink=None,
                    mode=0o600,
                    expected_sha256=digest,
                    backup_root=".local/state/arch-hypr-bootstrap/backups/plan",
                )
            )
            self.assertFalse(
                files.install(
                    ".config/app/config",
                    content=content,
                    symlink=None,
                    mode=0o600,
                    expected_sha256=digest,
                    backup_root=".local/state/arch-hypr-bootstrap/backups/plan",
                )
            )

        self.assertEqual(target.read_bytes(), content)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            (self.home / ".local/state/arch-hypr-bootstrap/backups/plan/.config/app/config").read_text(),
            "old",
        )

    def test_rejects_parent_symlinks_and_links_escaping_home(self):
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        self.home.mkdir()
        os.symlink(outside, self.home / ".config")
        digest = hashlib.sha256(b"data").hexdigest()

        with HomeFiles(self.home) as files:
            with self.assertRaises(OSError):
                files.install(
                    ".config/app",
                    content=b"data",
                    symlink=None,
                    mode=0o644,
                    expected_sha256=digest,
                    backup_root=".local/state/arch-hypr-bootstrap/backups/plan",
                )
            with self.assertRaisesRegex(FileBoundaryError, "escapes home"):
                files.install(
                    ".agents/skill",
                    content=None,
                    symlink="../../outside",
                    mode=0o777,
                    expected_sha256=hashlib.sha256(b"symlink:../../outside").hexdigest(),
                    backup_root=".local/state/arch-hypr-bootstrap/backups/plan",
                )


if __name__ == "__main__":
    unittest.main()
