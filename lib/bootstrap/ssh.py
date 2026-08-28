from __future__ import annotations

import base64
import binascii
import hashlib
import re
import subprocess


def fetch_github_keys(username: str) -> tuple[str, ...]:
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", username):
        raise RuntimeError(f"invalid GitHub username: {username}")
    try:
        result = subprocess.run(
            (
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                "--max-time",
                "20",
                f"https://github.com/{username}.keys",
            ),
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError(f"could not fetch SSH keys for GitHub user {username}") from error
    return parse_github_keys(result.stdout)


def parse_github_keys(response: str) -> tuple[str, ...]:
    allowed = {
        "ssh-ed25519",
        "ssh-rsa",
        "ecdsa-sha2-nistp256",
        "ecdsa-sha2-nistp384",
        "ecdsa-sha2-nistp521",
        "sk-ssh-ed25519@openssh.com",
        "sk-ecdsa-sha2-nistp256@openssh.com",
    }
    keys: list[str] = []
    for line in response.splitlines():
        key = line.strip()
        if not key:
            continue
        parts = key.split()
        if len(parts) < 2 or parts[0] not in allowed:
            raise RuntimeError("GitHub returned an invalid SSH public key")
        try:
            blob = base64.b64decode(parts[1], validate=True)
        except (ValueError, binascii.Error) as error:
            raise RuntimeError("GitHub returned an invalid SSH public key") from error
        if len(blob) < 4:
            raise RuntimeError("GitHub returned an invalid SSH public key")
        algorithm_length = int.from_bytes(blob[:4], "big")
        try:
            algorithm = blob[4 : 4 + algorithm_length].decode("ascii")
        except UnicodeDecodeError as error:
            raise RuntimeError("GitHub returned an invalid SSH public key") from error
        if algorithm != parts[0] or 4 + algorithm_length >= len(blob):
            raise RuntimeError("GitHub returned an invalid SSH public key")
        normalized = " ".join(parts)
        if normalized not in keys:
            keys.append(normalized)
    if not keys:
        raise RuntimeError("GitHub returned no SSH public keys")
    return tuple(keys)


def ssh_fingerprint(key: str) -> str:
    blob = base64.b64decode(key.split()[1], validate=True)
    digest = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    return f"SHA256:{digest}"
