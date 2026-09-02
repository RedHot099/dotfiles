import json
import os
import unittest
from subprocess import CompletedProcess
from unittest.mock import patch

from bootstrap.cli import detect_monitor_content


class MonitorDetectionTests(unittest.TestCase):
    @patch("bootstrap.cli.shutil.which", return_value="/usr/bin/hyprctl")
    @patch("bootstrap.cli.subprocess.run")
    def test_renders_current_monitor_geometry(self, run, _which):
        run.return_value = CompletedProcess(
            ("hyprctl",),
            0,
            json.dumps([{"name": "DP-1", "width": 3440, "height": 1440, "refreshRate": 174.96, "x": 0, "y": 0, "scale": 1.0}]),
        )
        with patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "test"}):
            content = detect_monitor_content()

        self.assertIn('output = "DP-1"', content)
        self.assertIn('3440x1440@174.96', content)

    @patch("bootstrap.cli.shutil.which", return_value="/usr/bin/hyprctl")
    @patch("bootstrap.cli.subprocess.run")
    def test_rejects_monitor_name_injection(self, run, _which):
        run.return_value = CompletedProcess(
            ("hyprctl",),
            0,
            json.dumps([{"name": 'DP-1";bad', "width": 1, "height": 1, "refreshRate": 60, "x": 0, "y": 0, "scale": 1}]),
        )
        with patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "test"}):
            with self.assertRaisesRegex(Exception, "unsafe monitor name"):
                detect_monitor_content()


if __name__ == "__main__":
    unittest.main()
