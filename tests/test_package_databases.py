import os
import tempfile
import unittest
from pathlib import Path

from bootstrap.catalog import CatalogError
from bootstrap.packages import check_databases_current


SNAPSHOT = 1788891826.0


class PackageDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.sync = Path(self.directory.name)

    def database(self, repository: str, modified: float) -> None:
        path = self.sync / f"{repository}.db"
        path.write_bytes(b"db")
        os.utime(path, (modified, modified))

    def check(self, remote: dict[str, float | None]) -> None:
        check_databases_current(set(remote), self.sync, remote.__getitem__)

    def test_old_snapshot_matching_the_mirror_is_current(self):
        self.database("core", SNAPSHOT)
        self.database("extra", SNAPSHOT)
        self.check({"core": SNAPSHOT, "extra": SNAPSHOT})

    def test_newer_mirror_database_is_stale(self):
        self.database("core", SNAPSHOT)
        self.database("omarchy", SNAPSHOT)
        with self.assertRaisesRegex(CatalogError, r"stale or missing for omarchy;"):
            self.check({"core": SNAPSHOT, "omarchy": SNAPSHOT + 86400})

    def test_missing_database_or_unknown_mirror_time_is_stale(self):
        self.database("extra", SNAPSHOT)
        with self.assertRaisesRegex(CatalogError, r"stale or missing for core, extra;"):
            self.check({"core": SNAPSHOT, "extra": None})


if __name__ == "__main__":
    unittest.main()
