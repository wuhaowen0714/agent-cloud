from __future__ import annotations

import shutil
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Protocol

from .errors import FileConflict, FileTooLarge, PathEscape


@dataclass
class FileEntry:
    name: str  # 基名,如 "app.py"
    path: str  # 相对工作区根的 posix 路径,无前导 "/";根目录为 ""
    is_dir: bool
    size: int  # 字节;目录为 0
    mtime: float  # epoch 秒


class FileStore(Protocol):
    def list_dir(self, user_id: str, rel_path: str) -> list[FileEntry]: ...
    def stat(self, user_id: str, rel_path: str) -> FileEntry: ...
    def open_read(self, user_id: str, rel_path: str) -> BinaryIO: ...
    def write(self, user_id: str, rel_path: str, data: BinaryIO, max_bytes: int) -> FileEntry: ...
    def mkdir(self, user_id: str, rel_path: str) -> FileEntry: ...
    def move(self, user_id: str, src: str, dst: str) -> FileEntry: ...
    def delete(self, user_id: str, rel_path: str) -> None: ...
    def zip_dir(self, user_id: str, rel_path: str) -> Iterator[bytes]: ...


_CHUNK = 1024 * 1024


class LocalFileStore:
    """直接在宿主文件系统上操作某用户的工作区(<host_root>/<user_id>/workspace)。"""

    def __init__(self, host_root: str) -> None:
        self._host_root = Path(host_root)

    def _user_root(self, user_id: str) -> Path:
        root = self._host_root / user_id / "workspace"
        root.mkdir(parents=True, exist_ok=True)  # 懒创建:新用户也能浏览/上传
        return root

    def _resolve(self, user_id: str, rel_path: str) -> Path:
        """把相对路径解析成围栏内的绝对路径;越界一律抛 PathEscape。"""
        if "\0" in rel_path:
            raise PathEscape("null byte in path")
        if rel_path.startswith("/"):
            raise PathEscape(f"absolute path not allowed: {rel_path!r}")
        parts = [p for p in rel_path.split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            raise PathEscape(f"parent traversal not allowed: {rel_path!r}")
        root = self._user_root(user_id).resolve()
        candidate = (root / Path(*parts)).resolve() if parts else root
        # resolve() 跟随 symlink:指向围栏外的链接解析后落在 root 外 → 拒绝
        if candidate != root and root not in candidate.parents:
            raise PathEscape(f"path escapes workspace: {rel_path!r}")
        return candidate

    def _entry(self, root: Path, p: Path) -> FileEntry:
        st = p.stat()
        is_dir = p.is_dir()
        return FileEntry(
            name=p.name,
            path="" if p == root else p.relative_to(root).as_posix(),
            is_dir=is_dir,
            size=0 if is_dir else st.st_size,
            mtime=st.st_mtime,
        )

    def list_dir(self, user_id: str, rel_path: str) -> list[FileEntry]:
        root = self._user_root(user_id).resolve()
        target = self._resolve(user_id, rel_path)
        if not target.exists():
            raise FileNotFoundError(rel_path)
        if not target.is_dir():
            raise NotADirectoryError(rel_path)
        entries = [self._entry(root, c) for c in target.iterdir()]
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))  # 目录优先,名称升序
        return entries

    def stat(self, user_id: str, rel_path: str) -> FileEntry:
        root = self._user_root(user_id).resolve()
        target = self._resolve(user_id, rel_path)
        if not target.exists():
            raise FileNotFoundError(rel_path)
        return self._entry(root, target)

    def open_read(self, user_id: str, rel_path: str) -> BinaryIO:
        target = self._resolve(user_id, rel_path)
        if not target.exists():
            raise FileNotFoundError(rel_path)
        if target.is_dir():
            raise IsADirectoryError(rel_path)
        return target.open("rb")

    def write(self, user_id: str, rel_path: str, data: BinaryIO, max_bytes: int) -> FileEntry:
        root = self._user_root(user_id).resolve()
        target = self._resolve(user_id, rel_path)
        if target == root:
            raise PathEscape("cannot write to workspace root")
        target.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        try:
            with target.open("wb") as f:
                while True:
                    chunk = data.read(_CHUNK)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        raise FileTooLarge(f"{rel_path}: exceeds {max_bytes} bytes")
                    f.write(chunk)
        except FileTooLarge:
            target.unlink(missing_ok=True)  # 删半截
            raise
        return self._entry(root, target)

    def mkdir(self, user_id: str, rel_path: str) -> FileEntry:
        root = self._user_root(user_id).resolve()
        target = self._resolve(user_id, rel_path)
        if target.exists():
            raise FileConflict(rel_path)
        target.mkdir(parents=True)
        return self._entry(root, target)

    def move(self, user_id: str, src: str, dst: str) -> FileEntry:
        root = self._user_root(user_id).resolve()
        s = self._resolve(user_id, src)
        d = self._resolve(user_id, dst)
        if not s.exists():
            raise FileNotFoundError(src)
        if d.exists():
            raise FileConflict(dst)
        if d == root:
            raise PathEscape("cannot overwrite workspace root")
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        return self._entry(root, d)

    def delete(self, user_id: str, rel_path: str) -> None:
        root = self._user_root(user_id).resolve()
        target = self._resolve(user_id, rel_path)
        if target == root:
            raise PathEscape("cannot delete workspace root")
        if not target.exists():
            raise FileNotFoundError(rel_path)
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

    def zip_dir(self, user_id: str, rel_path: str) -> Iterator[bytes]:
        target = self._resolve(user_id, rel_path)
        if not target.exists():
            raise FileNotFoundError(rel_path)
        if not target.is_dir():
            raise NotADirectoryError(rel_path)
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(target.rglob("*")):
                if p.is_file():
                    zf.write(p, p.relative_to(target).as_posix())
        buf.seek(0)
        yield from iter(lambda: buf.read(_CHUNK), b"")
