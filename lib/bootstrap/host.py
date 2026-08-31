from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
from functools import cached_property
from pathlib import Path


class LocalHostProbe:
    def __init__(self, target_home: Path) -> None:
        self._target_home = target_home.resolve()

    def os_release(self) -> str:
        return Path("/etc/os-release").read_text()

    def command_output(self, argv: tuple[str, ...]) -> str | None:
        executable = shutil.which(argv[0])
        if executable is None:
            return None
        result = subprocess.run(
            [executable, *argv[1:]],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def path_exists(self, path: str) -> bool:
        return Path(path).exists()

    def architecture(self) -> str:
        return platform.machine()

    def uid(self) -> int:
        return os.getuid()

    def target_home(self) -> str:
        return str(self._target_home)

    def pacman_config_digest(self) -> str:
        encoded = json.dumps(self._repository_records, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def repositories(self) -> tuple[str, ...]:
        return tuple(
            f"{item['name']}|siglevel={','.join(item['siglevel'])}|usage={','.join(item['usage'])}"
            for item in self._repository_records
        )

    def capabilities(self) -> frozenset[str]:
        commands = ("pacman", "mise", "hyprctl", "uwsm", "noctalia", "ufw", "systemctl")
        available = {command for command in commands if shutil.which(command)}
        return frozenset(available)

    @cached_property
    def _repository_records(self) -> tuple[dict[str, object], ...]:
        repositories = self.command_output(("pacman-conf", "--repo-list"))
        global_config = self.command_output(("pacman-conf", "--verbose", "SigLevel"))
        if repositories is None or global_config is None:
            raise RuntimeError("pacman-conf could not describe the configured repositories")
        global_siglevel = _directive_values(global_config, "SigLevel")
        records: list[dict[str, object]] = []
        for name in repositories.splitlines():
            config = self.command_output(("pacman-conf", "--verbose", "--repo", name, "SigLevel", "Usage"))
            if config is None:
                raise RuntimeError(f"pacman-conf could not describe repository {name}")
            siglevel = _directive_values(config, "SigLevel") or global_siglevel
            usage = _directive_values(config, "Usage") or ("All",)
            records.append({"name": name, "siglevel": siglevel, "usage": usage})
        return tuple(records)


def _directive_values(output: str, directive: str) -> tuple[str, ...]:
    prefix = f"{directive} = "
    return tuple(line.removeprefix(prefix) for line in output.splitlines() if line.startswith(prefix))
