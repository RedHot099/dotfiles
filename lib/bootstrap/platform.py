from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Protocol

from .domain import PlatformFingerprint, PlatformId


VERSION_RE = re.compile(r"\d+(?:\.\d+)+(?:[-+._a-zA-Z0-9]*)?")
OMARCHY_VERSION_RE = re.compile(
    r"^\s*(?:Omarchy\s+)?(\d+)(?:\.\d+)*(?:[-+._a-zA-Z0-9]*)?\s*$",
    re.IGNORECASE,
)
OS_RELEASE_KEY_RE = re.compile(r"[A-Z][A-Z0-9_]*")


class PlatformDetectionError(RuntimeError):
    pass


class HostProbe(Protocol):
    def os_release(self) -> str: ...

    def command_output(self, argv: tuple[str, ...]) -> str | None: ...

    def path_exists(self, path: str) -> bool: ...

    def architecture(self) -> str: ...

    def uid(self) -> int: ...

    def target_home(self) -> str: ...

    def pacman_config_digest(self) -> str: ...

    def repositories(self) -> tuple[str, ...]: ...

    def capabilities(self) -> frozenset[str]: ...


@dataclass(frozen=True)
class PlatformFacts:
    platform: PlatformId
    contract_major: int
    os_id: str
    architecture: str
    uid: int
    target_home: str
    omarchy_major: int | None
    hyprland_version: str | None
    uwsm_version: str | None
    shell_name: str
    shell_version: str | None
    pacman_config_digest: str
    repositories: tuple[str, ...]
    capabilities: frozenset[str]

    def __post_init__(self) -> None:
        self.fingerprint()

    def fingerprint(self) -> PlatformFingerprint:
        return PlatformFingerprint(
            platform=self.platform,
            contract_major=self.contract_major,
            os_id=self.os_id,
            architecture=self.architecture,
            uid=self.uid,
            target_home=self.target_home,
            omarchy_major=self.omarchy_major,
            hyprland_version=self.hyprland_version,
            uwsm_version=self.uwsm_version,
            shell_name=self.shell_name,
            shell_version=self.shell_version,
            pacman_config_digest=self.pacman_config_digest,
            repositories=self.repositories,
            capabilities=self.capabilities,
        )


def detect_platform(probe: HostProbe) -> PlatformFacts:
    release = parse_os_release(probe.os_release())
    os_id = release.get("ID")
    if os_id is None:
        raise PlatformDetectionError("os-release does not define ID")

    omarchy_marker = probe.path_exists("/usr/share/omarchy")
    omarchy_output = probe.command_output(("omarchy", "version"))
    omarchy_major = _omarchy_major(omarchy_output)

    if os_id == "cachyos":
        if omarchy_marker or omarchy_output is not None:
            raise PlatformDetectionError("contradictory CachyOS and Omarchy evidence")
        return _detect_cachy(probe, os_id)

    if omarchy_marker or omarchy_output is not None:
        if os_id not in {"arch", "omarchy"}:
            raise PlatformDetectionError(f"Omarchy markers found on unsupported OS ID {os_id!r}")
        if not omarchy_marker or omarchy_major is None:
            raise PlatformDetectionError("Omarchy marker and version command do not agree")
        if omarchy_major != 4:
            raise PlatformDetectionError(f"unsupported Omarchy major version: {omarchy_major}")
        return _facts(
            probe,
            platform=PlatformId.OMARCHY,
            contract_major=4,
            os_id=os_id,
            omarchy_major=omarchy_major,
            shell_name="omarchy-shell",
            shell_version=_version(probe.command_output(("omarchy-shell", "--version"))),
        )

    raise PlatformDetectionError(f"unsupported platform for OS ID {os_id!r}")


def parse_os_release(content: str) -> dict[str, str]:
    """Parse os-release assignments without evaluating shell code."""

    result: dict[str, str] = {}
    for line_number, raw_line in enumerate(content.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise PlatformDetectionError(f"invalid os-release line {line_number}")
        key, encoded = line.split("=", 1)
        if not OS_RELEASE_KEY_RE.fullmatch(key):
            raise PlatformDetectionError(f"invalid os-release key on line {line_number}")
        if key in result:
            raise PlatformDetectionError(f"duplicate os-release key: {key}")
        if "$" in encoded or "`" in encoded or "\x00" in encoded:
            raise PlatformDetectionError(f"unsafe os-release value for {key}")
        lexer = shlex.shlex(encoded, posix=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        try:
            tokens = list(lexer)
        except ValueError as error:
            raise PlatformDetectionError(f"invalid os-release value for {key}") from error
        if len(tokens) != 1:
            raise PlatformDetectionError(f"invalid os-release value for {key}")
        result[key] = tokens[0]
    return result


def _detect_cachy(probe: HostProbe, os_id: str) -> PlatformFacts:
    hyprland = _version(probe.command_output(("Hyprland", "--version")))
    uwsm = _version(probe.command_output(("uwsm", "--version")))
    noctalia = _version(probe.command_output(("noctalia", "--version")))
    missing = [
        name
        for name, version in (("Hyprland", hyprland), ("UWSM", uwsm), ("Noctalia", noctalia))
        if version is None
    ]
    if missing:
        raise PlatformDetectionError("CachyOS desktop contract is incomplete: " + ", ".join(missing))
    assert hyprland is not None and uwsm is not None and noctalia is not None
    if not ((0, 55, 0) <= _numeric_version(hyprland) < (0, 57, 0)):
        raise PlatformDetectionError(f"unsupported Hyprland version for CachyOS: {hyprland}")
    if not ((0, 24, 0) <= _numeric_version(uwsm) < (1, 0, 0)):
        raise PlatformDetectionError(f"unsupported UWSM version for CachyOS: {uwsm}")
    if _numeric_version(noctalia)[0] != 5:
        raise PlatformDetectionError(f"unsupported Noctalia version for CachyOS: {noctalia}")
    return _facts(
        probe,
        platform=PlatformId.CACHY,
        contract_major=1,
        os_id=os_id,
        omarchy_major=None,
        shell_name="noctalia",
        shell_version=noctalia,
        hyprland_version=hyprland,
        uwsm_version=uwsm,
    )


def _facts(
    probe: HostProbe,
    *,
    platform: PlatformId,
    contract_major: int,
    os_id: str,
    omarchy_major: int | None,
    shell_name: str,
    shell_version: str | None,
    hyprland_version: str | None = None,
    uwsm_version: str | None = None,
) -> PlatformFacts:
    return PlatformFacts(
        platform=platform,
        contract_major=contract_major,
        os_id=os_id,
        architecture=probe.architecture(),
        uid=probe.uid(),
        target_home=probe.target_home(),
        omarchy_major=omarchy_major,
        hyprland_version=hyprland_version or _version(probe.command_output(("Hyprland", "--version"))),
        uwsm_version=uwsm_version or _version(probe.command_output(("uwsm", "--version"))),
        shell_name=shell_name,
        shell_version=shell_version,
        pacman_config_digest=probe.pacman_config_digest(),
        repositories=probe.repositories(),
        capabilities=probe.capabilities(),
    )


def _omarchy_major(output: str | None) -> int | None:
    if output is None:
        return None
    match = OMARCHY_VERSION_RE.fullmatch(output)
    return int(match.group(1)) if match else None


def _version(output: str | None) -> str | None:
    if output is None:
        return None
    match = VERSION_RE.search(output)
    return match.group(0) if match else None


def _numeric_version(value: str) -> tuple[int, int, int]:
    numeric = value.split("-", 1)[0].split("+", 1)[0]
    parts = [int(item) for item in numeric.split(".")]
    return tuple((parts + [0, 0, 0])[:3])
