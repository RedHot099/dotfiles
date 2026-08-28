import base64
import unittest
from pathlib import Path

from bootstrap.catalog import CatalogError, PackageBinding, load_workspace
from bootstrap.packages import (
    AurRecipe,
    repository_names,
    parse_srcinfo,
    parse_transaction,
    verify_transaction,
    verify_aur_snapshot,
)


class PackageSafetyTests(unittest.TestCase):
    def test_cachy_tailscale_accepts_the_official_znver4_extra_repository(self):
        workspace = load_workspace(Path(__file__).resolve().parents[1], "cachy")
        binding = workspace.package_bindings["tailscale"]

        transaction = parse_transaction(
            "cachyos-extra-znver4\ttailscale\t1.0-1\n",
            (binding,),
            ("cachyos-extra-znver4",),
        )

        self.assertEqual(transaction[0].repository, "cachyos-extra-znver4")

    def test_transaction_is_closed_and_direct_sources_are_allowlisted(self):
        binding = PackageBinding(
            "editor", "repository", "editor", ("extra",), None, None
        )
        transaction = parse_transaction(
            "extra\tdependency\t1.0-1\nextra\teditor\t2.0-1\n",
            (binding,),
            ("core", "extra"),
        )

        self.assertEqual(
            tuple((item.repository, item.name, item.version) for item in transaction),
            (("extra", "dependency", "1.0-1"), ("extra", "editor", "2.0-1")),
        )

        with self.assertRaisesRegex(CatalogError, "unapproved repository"):
            parse_transaction("custom\teditor\t2.0-1\n", (binding,), ("custom", "extra"))
        with self.assertRaisesRegex(CatalogError, "does not contain requested"):
            parse_transaction("extra\tdependency\t1.0-1\n", (binding,), ("extra",))

    def test_srcinfo_dependencies_and_split_package_names_are_data(self):
        package_base, package_names, dependencies = parse_srcinfo(
            """pkgbase = example
makedepends = cmake
depends = glibc>=2.40
checkdepends_x86_64 = python
pkgname = example
pkgname = example-cli
"""
        )

        self.assertEqual(package_base, "example")
        self.assertEqual(package_names, ("example", "example-cli"))
        self.assertEqual(dependencies, ("cmake", "glibc>=2.40", "python"))

    def test_aur_snapshot_rejects_any_changed_or_unplanned_file(self):
        content = base64.b64encode(b"pkgname=example\n").decode()
        recipe = AurRecipe(
            package_base="example",
            package_names=("example",),
            version="1.0-1",
            dependencies=(),
            files=(("PKGBUILD", "a" * 64, content),),
        )

        with self.assertRaisesRegex(CatalogError, "AUR recipe changed"):
            verify_aur_snapshot(recipe, (("PKGBUILD", "b" * 64, content),))

    def test_repository_fingerprint_names_are_extracted_without_weakening_it(self):
        self.assertEqual(
            repository_names(("core|siglevel=Required|usage=All", "extra|usage=All")),
            ("core", "extra"),
        )

    def test_reapproval_accepts_only_members_already_installed_at_planned_version(self):
        planned = parse_transaction(
            "extra\tdependency\t1.0-1\nextra\teditor\t2.0-1\n",
            (PackageBinding("editor", "repository", "editor", ("extra",), None, None),),
            ("extra",),
        )
        current = (planned[1],)

        verify_transaction(planned, current, {"dependency": "1.0-1"})
        with self.assertRaisesRegex(CatalogError, "transaction changed"):
            verify_transaction(planned, current, {"dependency": "1.1-1"})


if __name__ == "__main__":
    unittest.main()
