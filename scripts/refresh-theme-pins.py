#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import tempfile
import tomllib
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Review or refresh pinned custom theme commits")
    parser.add_argument("--write", action="store_true", help="Write the reported remote HEAD commits")
    parser.add_argument("--catalog", type=Path, default=Path("features/themes/feature.toml"))
    args = parser.parse_args()
    content = args.catalog.read_text()
    data = tomllib.loads(content)
    changed = content
    for repository in data["repositories"]:
        remote = subprocess.run(
            ["git", "ls-remote", repository["url"], "HEAD"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.split()[0]
        current = repository["revision"]
        print(f"{repository['target']}: {current} -> {remote}")
        if args.write:
            old = f'revision = "{current}"'
            new = f'revision = "{remote}"'
            if changed.count(old) != 1:
                raise SystemExit(f"Expected one revision entry for {repository['target']}")
            changed = changed.replace(old, new)
    if args.write and changed != content:
        with tempfile.NamedTemporaryFile("w", dir=args.catalog.parent, delete=False) as stream:
            stream.write(changed)
            temporary = Path(stream.name)
        temporary.replace(args.catalog)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
