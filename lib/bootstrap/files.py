from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import stat
from pathlib import Path, PurePosixPath


class FileBoundaryError(RuntimeError):
    pass


class HomeFiles:
    def __init__(self, target_home: Path, *, create: bool = True) -> None:
        if target_home.exists() and target_home.is_symlink():
            raise FileBoundaryError("target home must not be a symlink")
        if create:
            target_home.mkdir(parents=True, exist_ok=True)
        elif not target_home.is_dir():
            raise FileBoundaryError("target home does not exist")
        self.path = target_home.resolve()
        self._root = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def close(self) -> None:
        os.close(self._root)

    def __enter__(self) -> HomeFiles:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def hash(self, target: str) -> str | None:
        parent, name = self._parent(target, create=False)
        if parent is None:
            return None
        try:
            metadata = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                return _digest(f"symlink:{os.readlink(name, dir_fd=parent)}".encode())
            if not stat.S_ISREG(metadata.st_mode):
                raise FileBoundaryError(f"target is not a regular file: {target}")
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                digest = hashlib.sha256()
                while chunk := os.read(descriptor, 1024 * 1024):
                    digest.update(chunk)
                return digest.hexdigest()
            finally:
                os.close(descriptor)
        except FileNotFoundError:
            return None
        finally:
            os.close(parent)

    def target_kind(self, target: str) -> str | None:
        parent, name = self._parent(target, create=False)
        if parent is None:
            return None
        try:
            try:
                mode = os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode
            except FileNotFoundError:
                return None
            if stat.S_ISDIR(mode):
                return "directory"
            if stat.S_ISLNK(mode):
                return "symlink"
            if stat.S_ISREG(mode):
                return "file"
            return "other"
        finally:
            os.close(parent)

    def remove_exact(self, target: str) -> None:
        parent, name = self._parent(target, create=False)
        if parent is None:
            return
        try:
            try:
                mode = os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode
            except FileNotFoundError:
                return
            if stat.S_ISDIR(mode):
                shutil.rmtree(name, dir_fd=parent)
            else:
                os.unlink(name, dir_fd=parent)
            os.fsync(parent)
        finally:
            os.close(parent)

    def read_text(self, target: str) -> str | None:
        parent, name = self._parent(target, create=False)
        if parent is None:
            return None
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                chunks: list[bytes] = []
                while chunk := os.read(descriptor, 1024 * 1024):
                    chunks.append(chunk)
                return b"".join(chunks).decode()
            finally:
                os.close(descriptor)
        except FileNotFoundError:
            return None
        finally:
            os.close(parent)

    def ensure_directory(self, target: str, mode: int) -> None:
        lexical = PurePosixPath(target)
        if lexical.is_absolute() or not lexical.parts or ".." in lexical.parts:
            raise FileBoundaryError(f"directory escapes home: {target}")
        descriptor = os.dup(self._root)
        try:
            for index, part in enumerate(lexical.parts):
                if part == ".":
                    continue
                desired = mode if index == len(lexical.parts) - 1 else 0o755
                try:
                    child = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=descriptor,
                    )
                except FileNotFoundError:
                    os.mkdir(part, desired, dir_fd=descriptor)
                    os.fsync(descriptor)
                    child = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=descriptor,
                    )
                if index == len(lexical.parts) - 1:
                    os.fchmod(child, mode)
                os.close(descriptor)
                descriptor = child
        finally:
            os.close(descriptor)

    def open_lock(self, target: str) -> int:
        parent, name = self._parent(target, create=True)
        assert parent is not None
        try:
            return os.open(
                name,
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
        finally:
            os.close(parent)

    def write_private_atomic(self, target: str, content: bytes) -> None:
        parent, name = self._parent(target, create=True)
        assert parent is not None
        temporary = f".{name}.bootstrap-{secrets.token_hex(8)}"
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
            try:
                view = memoryview(content)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
                os.fchmod(descriptor, 0o600)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.rename(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
            os.close(parent)

    def list_text_files(self, directory: str, suffix: str) -> dict[str, str]:
        parent, name = self._parent(f"{directory}/placeholder", create=False)
        if parent is None:
            return {}
        try:
            try:
                descriptor = os.open(
                    name if name != "placeholder" else ".",
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=parent,
                )
            except FileNotFoundError:
                return {}
            try:
                result: dict[str, str] = {}
                for filename in sorted(os.listdir(descriptor)):
                    if not filename.endswith(suffix):
                        continue
                    file_descriptor = os.open(
                        filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor
                    )
                    try:
                        chunks: list[bytes] = []
                        while chunk := os.read(file_descriptor, 1024 * 1024):
                            chunks.append(chunk)
                        result[filename] = b"".join(chunks).decode()
                    finally:
                        os.close(file_descriptor)
                return result
            finally:
                os.close(descriptor)
        finally:
            os.close(parent)

    def matches(self, target: str, expected_sha256: str, mode: int, symlink: str | None) -> bool:
        if self.hash(target) != expected_sha256:
            return False
        parent, name = self._parent(target, create=False)
        if parent is None:
            return False
        try:
            metadata = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if symlink is not None:
                return stat.S_ISLNK(metadata.st_mode) and os.readlink(name, dir_fd=parent) == symlink
            return stat.S_ISREG(metadata.st_mode) and metadata.st_mode & 0o777 == mode
        finally:
            os.close(parent)

    def install(
        self,
        target: str,
        *,
        content: bytes | None,
        symlink: str | None,
        mode: int,
        expected_sha256: str,
        backup_root: str,
    ) -> bool:
        if (content is None) == (symlink is None):
            raise ValueError("exactly one of content and symlink is required")
        if self.matches(target, expected_sha256, mode, symlink):
            return False
        self._backup_once(target, backup_root)
        parent, name = self._parent(target, create=True)
        assert parent is not None
        temporary = f".{name}.bootstrap-{secrets.token_hex(8)}"
        try:
            if symlink is not None:
                _validate_link(target, symlink)
                os.symlink(symlink, temporary, dir_fd=parent)
            else:
                descriptor = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    mode,
                    dir_fd=parent,
                )
                try:
                    assert content is not None
                    view = memoryview(content)
                    while view:
                        written = os.write(descriptor, view)
                        view = view[written:]
                    os.fchmod(descriptor, mode)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            os.rename(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
            os.close(parent)
        if not self.matches(target, expected_sha256, mode, symlink):
            raise FileBoundaryError(f"postcondition failed for {target}")
        return True

    def _backup_once(self, target: str, backup_root: str) -> None:
        if self.hash(target) is None:
            return
        backup = f"{backup_root}/{target}"
        if self.hash(backup) is not None:
            return
        source_parent, source_name = self._parent(target, create=False)
        assert source_parent is not None
        try:
            metadata = os.stat(source_name, dir_fd=source_parent, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                self.install(
                    backup,
                    content=None,
                    symlink=os.readlink(source_name, dir_fd=source_parent),
                    mode=metadata.st_mode & 0o777,
                    expected_sha256=self.hash(target) or "",
                    backup_root=f"{backup_root}/.never",
                )
                return
            descriptor = os.open(source_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=source_parent)
            try:
                chunks: list[bytes] = []
                while chunk := os.read(descriptor, 1024 * 1024):
                    chunks.append(chunk)
            finally:
                os.close(descriptor)
            content = b"".join(chunks)
            self.install(
                backup,
                content=content,
                symlink=None,
                mode=metadata.st_mode & 0o777,
                expected_sha256=_digest(content),
                backup_root=f"{backup_root}/.never",
            )
        finally:
            os.close(source_parent)

    def _parent(self, target: str, *, create: bool) -> tuple[int | None, str]:
        lexical = PurePosixPath(target)
        if lexical.is_absolute() or not lexical.parts or ".." in lexical.parts:
            raise FileBoundaryError(f"target escapes home: {target}")
        if lexical.name in {"", "."}:
            raise FileBoundaryError(f"target is not a file: {target}")
        descriptor = os.dup(self._root)
        try:
            for part in lexical.parent.parts:
                if part == ".":
                    continue
                try:
                    child = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=descriptor,
                    )
                except FileNotFoundError:
                    if not create:
                        os.close(descriptor)
                        return None, lexical.name
                    os.mkdir(part, 0o755, dir_fd=descriptor)
                    os.fsync(descriptor)
                    child = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=descriptor,
                    )
                os.close(descriptor)
                descriptor = child
            return descriptor, lexical.name
        except Exception:
            os.close(descriptor)
            raise


def _validate_link(target: str, link: str) -> None:
    destination = PurePosixPath(link)
    if destination.is_absolute() or "\x00" in link:
        raise FileBoundaryError(f"unsafe symlink: {target} -> {link}")
    parts: list[str] = []
    for part in (PurePosixPath(target).parent / destination).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise FileBoundaryError(f"symlink escapes home: {target} -> {link}")
            parts.pop()
        else:
            parts.append(part)


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
