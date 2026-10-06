import unittest

from bootstrap.domain import PlatformId
from bootstrap.platform import PlatformDetectionError, detect_platform
from tests.fixtures import FixtureProbe, omarchy_probe


class PlatformDetectionTests(unittest.TestCase):
    def test_omarchy_4_is_detected(self):
        facts = detect_platform(omarchy_probe())

        self.assertIs(facts.platform, PlatformId.OMARCHY)
        self.assertEqual(facts.omarchy_major, 4)
        self.assertEqual(facts.shell_name, "omarchy-shell")

    def test_cachyos_is_rejected_as_unsupported(self):
        probe = FixtureProbe(
            'NAME="CachyOS"\nID=cachyos\n',
            {("Hyprland", "--version"): "Hyprland 0.56.2"},
        )

        with self.assertRaisesRegex(PlatformDetectionError, "unsupported platform"):
            detect_platform(probe)


if __name__ == "__main__":
    unittest.main()
