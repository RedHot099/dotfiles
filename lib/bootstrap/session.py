from __future__ import annotations

import os
import subprocess


SESSION_KEYS = ("HYPRLAND_INSTANCE_SIGNATURE", "WAYLAND_DISPLAY")


def session_environment() -> dict[str, str] | None:
    """Return the environment for the user's running Hyprland session.

    Agents run without the session variables (inside T3 Code, or over ssh).
    The systemd user manager holds them for the active UWSM session; only
    these two keys are read from it, nothing else is kept or printed.
    """
    found = {key: os.environ[key] for key in SESSION_KEYS if os.environ.get(key)}
    if "HYPRLAND_INSTANCE_SIGNATURE" not in found:
        try:
            result = subprocess.run(
                ("/usr/bin/systemctl", "--user", "show-environment"),
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return None
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                key, _, value = line.partition("=")
                if key in SESSION_KEYS and value and key not in found:
                    found[key] = value
    signature = found.get("HYPRLAND_INSTANCE_SIGNATURE")
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    # A value left over from an ended session has no live control socket.
    if not signature or "/" in signature or not os.path.exists(
        os.path.join(runtime, "hypr", signature, ".socket.sock")
    ):
        return None
    return dict(os.environ, XDG_RUNTIME_DIR=runtime, **found)
