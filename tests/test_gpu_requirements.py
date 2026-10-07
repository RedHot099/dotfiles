import tempfile
import unittest
from pathlib import Path

from bootstrap.cli import detect_gpu_vendors
from bootstrap.domain import PackagesRequest, PlatformId
from bootstrap.packages import RepositoryPackage
from bootstrap.planner import HostState
from bootstrap.platform import detect_platform
from bootstrap.repository import compile_repository
from bootstrap.workflows import plan_packages
from tests.fixtures import omarchy_probe


ROOT = Path(__file__).resolve().parents[1]


class RecordingProvider:
    def __init__(self):
        self.packages: tuple[str, ...] = ()

    def resolve_repository(self, bindings):
        self.packages = tuple(binding.package for binding in bindings)
        return tuple(RepositoryPackage("multilib", name, "1-1") for name in self.packages)


class GpuRequirementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = compile_repository(ROOT, PlatformId.OMARCHY)

    def plan_steam(self, vendors: frozenset[str]) -> tuple[str, ...]:
        provider = RecordingProvider()
        plan_packages(
            self.repository,
            detect_platform(omarchy_probe()),
            HostState(frozenset(), frozenset(), gpu_vendors=vendors),
            PackagesRequest(frozenset({"steam"})),
            provider,
        )
        return provider.packages

    def test_steam_gets_the_32_bit_vulkan_driver_for_each_gpu(self):
        self.assertIn("lib32-vulkan-radeon", self.plan_steam(frozenset({"amd"})))
        self.assertIn("lib32-vulkan-intel", self.plan_steam(frozenset({"intel"})))
        nvidia = self.plan_steam(frozenset({"nvidia"}))
        self.assertNotIn("lib32-vulkan-radeon", nvidia)
        self.assertNotIn("lib32-vulkan-intel", nvidia)

    def test_detects_display_controllers_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, device_class, vendor in (
                ("0000:63:00.0", "0x038000", "0x1002"),
                ("0000:00:14.0", "0x0c0330", "0x8086"),
            ):
                (root / name).mkdir()
                (root / name / "class").write_text(device_class + "\n")
                (root / name / "vendor").write_text(vendor + "\n")
            self.assertEqual(detect_gpu_vendors(root), frozenset({"amd"}))


if __name__ == "__main__":
    unittest.main()
