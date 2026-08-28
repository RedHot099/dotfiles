import os
import tempfile
import unittest
from pathlib import Path

from bootstrap.catalog import CatalogError, load_workspace
from bootstrap.domain import PlatformId


FEATURE = '''\
schema = 2
id = "{feature_id}"
label = "{feature_id}"
description = "fixture"
group = "Tests"
default = {default}
visible = {visible}
requires = {requires}
'''


IMPLEMENTATION = '''\
schema = 2
id = "{feature_id}"
package_requirements = {package_requirements}
tools = {tools}
listens = {listens}
listening_ports = {ports}
{files}
'''


class WorkspaceFixture:
    def __init__(self, root: Path):
        self.root = root
        for relative in (
            "common/catalog/features",
            "common/catalog/profiles",
            "common/implementations",
            "common/payload",
            "omarchy/implementations",
            "omarchy/payload",
            "cachy/implementations",
            "cachy/payload",
        ):
            (root / relative).mkdir(parents=True)
        self.bindings: dict[str, dict[str, tuple[str, str]]] = {
            "common": {},
            "omarchy": {},
            "cachy": {},
        }
        self._write_bindings()

    def feature(
        self,
        feature_id: str,
        *,
        default: bool = False,
        visible: bool = True,
        requires: tuple[str, ...] = (),
    ) -> None:
        rendered_requires = "[" + ", ".join(f'"{item}"' for item in requires) + "]"
        self.write(
            f"common/catalog/features/{feature_id}.toml",
            FEATURE.format(
                feature_id=feature_id,
                default=str(default).lower(),
                visible=str(visible).lower(),
                requires=rendered_requires,
            ),
        )

    def implementation(
        self,
        bundle: str,
        feature_id: str,
        *,
        package_requirements: tuple[str, ...] = (),
        provider: str = "repository",
        tools: tuple[str, ...] = (),
        listens: bool = False,
        ports: tuple[int, ...] = (),
        source: str | None = None,
        target: str = ".",
    ) -> None:
        files = ""
        if source is not None:
            files = f'[[files]]\nsource = "{source}"\ntarget = "{target}"'
        quoted = lambda values: "[" + ", ".join(f'"{item}"' for item in values) + "]"
        for requirement in package_requirements:
            self.bindings[bundle][requirement] = (provider, requirement)
        self._write_bindings()
        self.write(
            f"{bundle}/implementations/{feature_id}.toml",
            IMPLEMENTATION.format(
                feature_id=feature_id,
                package_requirements=quoted(package_requirements),
                tools=quoted(tools),
                listens=str(listens).lower(),
                ports="[" + ", ".join(str(port) for port in ports) + "]",
                files=files,
            ),
        )

    def _write_bindings(self) -> None:
        for platform in ("omarchy", "cachy"):
            lines = ["schema = 2", ""]
            bindings = {**self.bindings["common"], **self.bindings[platform]}
            for requirement, (provider, package) in sorted(bindings.items()):
                lines.extend(
                    (
                        "[[bindings]]",
                        f'requirement = "{requirement}"',
                        f'provider = "{provider}"',
                        f'package = "{package}"',
                    )
                )
                if provider == "repository":
                    lines.append('repositories = ["extra"]')
                else:
                    lines.extend(
                        (
                            f'url = "https://aur.archlinux.org/{package}.git"',
                            f'revision = "{"a" * 40}"',
                        )
                    )
                lines.append("")
            self.write(f"{platform}/packages.toml", "\n".join(lines))

    def profile(self, profile_id: str, features: tuple[str, ...]) -> None:
        quoted = "[" + ", ".join(f'"{item}"' for item in features) + "]"
        self.write(
            f"common/catalog/profiles/{profile_id}.toml",
            f'schema = 2\nid = "{profile_id}"\nlabel = "{profile_id}"\n'
            f'default = false\nfeatures = {quoted}\n',
        )

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path


class WorkspaceCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.fixture = WorkspaceFixture(self.root)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_composes_common_with_only_the_selected_platform(self):
        self.fixture.feature("portable")
        self.fixture.feature("desktop")
        self.fixture.implementation("common", "portable", package_requirements=("rclone",))
        self.fixture.implementation("omarchy", "desktop", package_requirements=("omarchy-shell",))
        self.fixture.implementation("cachy", "desktop", package_requirements=("noctalia-shell",))

        omarchy = load_workspace(self.root, PlatformId.OMARCHY)
        cachy = load_workspace(self.root, PlatformId.CACHY)

        self.assertEqual(set(omarchy.public_catalog), {"portable", "desktop"})
        self.assertEqual(omarchy.implementations["portable"].bundle, "common")
        self.assertEqual(omarchy.implementations["desktop"].package_requirements, ("omarchy-shell",))
        self.assertEqual(cachy.implementations["desktop"].package_requirements, ("noctalia-shell",))
        self.assertNotEqual(omarchy.source_digest, cachy.source_digest)

    def test_rejects_duplicate_and_missing_complete_implementations(self):
        self.fixture.feature("desktop")
        self.fixture.implementation("common", "desktop")
        self.fixture.implementation("omarchy", "desktop")

        with self.assertRaisesRegex(CatalogError, "two implementations"):
            load_workspace(self.root, PlatformId.OMARCHY)

        (self.root / "common/implementations/desktop.toml").unlink()
        (self.root / "omarchy/implementations/desktop.toml").unlink()
        with self.assertRaisesRegex(CatalogError, "missing implementation"):
            load_workspace(self.root, PlatformId.OMARCHY)

    def test_rejects_unknown_dependencies_and_cycles(self):
        self.fixture.feature("one", requires=("missing",))
        self.fixture.implementation("common", "one")
        with self.assertRaisesRegex(CatalogError, "unknown feature"):
            load_workspace(self.root, PlatformId.OMARCHY)

    def test_loads_profiles_and_rejects_unknown_profile_features(self):
        self.fixture.feature("desktop")
        self.fixture.implementation("common", "desktop")
        self.fixture.profile("default", ("desktop",))

        workspace = load_workspace(self.root, PlatformId.OMARCHY)
        self.assertEqual(workspace.profiles["default"].features, ("desktop",))

        self.fixture.profile("broken", ("missing",))
        with self.assertRaisesRegex(CatalogError, "profile selects unknown feature"):
            load_workspace(self.root, PlatformId.OMARCHY)

    def test_rejects_unknown_manifest_and_nested_table_fields(self):
        self.fixture.feature("desktop")
        self.fixture.implementation("common", "desktop")
        feature = self.root / "common/catalog/features/desktop.toml"
        feature.write_text(feature.read_text() + "surprise = true\n")
        with self.assertRaisesRegex(CatalogError, "unknown manifest fields"):
            load_workspace(self.root, PlatformId.OMARCHY)

        self.fixture.feature("desktop")
        self.fixture.write("common/payload/desktop", "data")
        implementation = self.root / "common/implementations/desktop.toml"
        implementation.write_text(
            implementation.read_text()
            + '[[files]]\nsource = "payload/desktop"\ntarget = ".config/desktop"\n'
            + "surprise = true\n"
        )
        with self.assertRaisesRegex(CatalogError, "unknown files fields"):
            load_workspace(self.root, PlatformId.OMARCHY)

        self.fixture.feature("one", requires=("two",))
        self.fixture.feature("two", requires=("one",))
        self.fixture.implementation("common", "two")
        with self.assertRaisesRegex(CatalogError, "dependency cycle"):
            load_workspace(self.root, PlatformId.OMARCHY)

    def test_rejects_duplicate_package_and_tool_owners(self):
        cases = (
            ("package_requirements", "ripgrep"),
            ("tools", "node@24.20.0"),
        )
        for field, value in cases:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as directory:
                    fixture = WorkspaceFixture(Path(directory))
                    for feature_id in ("one", "two"):
                        fixture.feature(feature_id)
                        fixture.implementation("common", feature_id, **{field: (value,)})
                    with self.assertRaisesRegex(CatalogError, "owned by both"):
                        load_workspace(Path(directory), PlatformId.OMARCHY)

    def test_rejects_exact_and_ancestor_target_owners(self):
        for second_target in (".config/app/config.toml", ".config/app/config.toml/nested"):
            with self.subTest(second_target=second_target):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    fixture = WorkspaceFixture(root)
                    fixture.feature("one")
                    fixture.feature("two")
                    fixture.write("common/payload/one", "one")
                    fixture.write("common/payload/two", "two")
                    fixture.implementation(
                        "common", "one", source="payload/one", target=".config/app/config.toml"
                    )
                    fixture.implementation(
                        "common", "two", source="payload/two", target=second_target
                    )
                    with self.assertRaisesRegex(CatalogError, "target ownership conflict"):
                        load_workspace(root, PlatformId.OMARCHY)

    def test_directory_payloads_may_share_a_target_root_when_files_do_not_overlap(self):
        for feature_id in ("one", "two"):
            self.fixture.feature(feature_id)
            self.fixture.write(f"common/payload/{feature_id}/.config/{feature_id}.toml", feature_id)
            self.fixture.implementation(
                "common", feature_id, source=f"payload/{feature_id}", target="."
            )

        workspace = load_workspace(self.root, PlatformId.OMARCHY)

        self.assertEqual(set(workspace.implementations), {"one", "two"})

    def test_confines_sources_and_rejects_target_traversal(self):
        self.fixture.feature("unsafe")
        outside = self.root / "outside"
        outside.write_text("outside", encoding="utf-8")
        self.fixture.implementation("common", "unsafe", source="../outside")
        with self.assertRaisesRegex(CatalogError, "unsafe source"):
            load_workspace(self.root, PlatformId.OMARCHY)

        self.fixture.implementation("common", "unsafe", source="payload/safe", target="../escape")
        self.fixture.write("common/payload/safe", "safe")
        with self.assertRaisesRegex(CatalogError, "unsafe target"):
            load_workspace(self.root, PlatformId.OMARCHY)

    def test_rejects_moving_tool_and_git_references(self):
        self.fixture.feature("tool")
        self.fixture.implementation("common", "tool", tools=("node@latest",))
        with self.assertRaisesRegex(CatalogError, "moving tool"):
            load_workspace(self.root, PlatformId.OMARCHY)

        self.fixture.implementation("common", "tool")
        self.fixture.write(
            "common/implementations/tool.toml",
            'schema = 2\nid = "tool"\n'
            '[[repositories]]\nurl = "https://example.test/repo.git"\nrevision = "main"\ntarget = ".local/share/repo"\n',
        )
        with self.assertRaisesRegex(CatalogError, "moving Git"):
            load_workspace(self.root, PlatformId.OMARCHY)

    def test_rejects_listening_services_invisible_or_reachable_from_defaults(self):
        self.fixture.feature("server", visible=False)
        self.fixture.implementation("common", "server", listens=True, ports=(22,))
        with self.assertRaisesRegex(CatalogError, "must be visible"):
            load_workspace(self.root, PlatformId.OMARCHY)

        self.fixture.feature("server", visible=True)
        self.fixture.feature("desktop", default=True, requires=("server",))
        self.fixture.implementation("common", "desktop")
        with self.assertRaisesRegex(CatalogError, "default dependency closure"):
            load_workspace(self.root, PlatformId.OMARCHY)

    def test_common_purity_rejects_platform_api_but_not_vim_lua_options(self):
        self.fixture.feature("editor")
        self.fixture.write("common/payload/editor/init.lua", "vim.o.number = true\n")
        self.fixture.implementation("common", "editor", source="payload/editor", target=".config/nvim")

        load_workspace(self.root, PlatformId.OMARCHY)

        self.fixture.write("common/payload/editor/init.lua", "o.bind({ mod = 'SUPER' })\n")
        with self.assertRaisesRegex(CatalogError, "platform-specific reference"):
            load_workspace(self.root, PlatformId.OMARCHY)

    def test_source_digest_tracks_manifests_payload_bytes_and_symlink_targets(self):
        self.fixture.feature("files")
        self.fixture.write("common/payload/files/data", "one")
        os.symlink("data", self.root / "common/payload/files/link")
        self.fixture.implementation("common", "files", source="payload/files", target=".config/files")
        initial = load_workspace(self.root, PlatformId.OMARCHY).source_digest

        self.fixture.write("common/payload/files/data", "two")
        payload_changed = load_workspace(self.root, PlatformId.OMARCHY).source_digest
        self.assertNotEqual(initial, payload_changed)

        (self.root / "common/payload/files/link").unlink()
        os.symlink("./data", self.root / "common/payload/files/link")
        link_changed = load_workspace(self.root, PlatformId.OMARCHY).source_digest
        self.assertNotEqual(payload_changed, link_changed)

        self.fixture.feature("files", visible=False)
        manifest_changed = load_workspace(self.root, PlatformId.OMARCHY).source_digest
        self.assertNotEqual(link_changed, manifest_changed)

    def test_rejects_symlink_escape_but_accepts_home_confined_dangling_link(self):
        self.fixture.feature("portable")
        os.symlink("../../../../outside", self.root / "common/payload/escape")
        self.fixture.implementation(
            "common", "portable", source="payload/escape", target=".agents/skills/escape"
        )
        with self.assertRaisesRegex(CatalogError, "escapes target home"):
            load_workspace(self.root, PlatformId.OMARCHY)

        (self.root / "common/payload/escape").unlink()
        os.symlink(
            "../../.local/share/arch-hypr-bootstrap/skill",
            self.root / "common/payload/escape",
        )
        workspace = load_workspace(self.root, PlatformId.OMARCHY)
        self.assertIn("portable", workspace.implementations)


if __name__ == "__main__":
    unittest.main()
