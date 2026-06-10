from __future__ import annotations

import os
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
    def abspath(self, user_id: str, rel_path: str) -> Path: ...
    def open_read(self, user_id: str, rel_path: str) -> BinaryIO: ...
    def write(self, user_id: str, rel_path: str, data: BinaryIO, max_bytes: int) -> FileEntry: ...
    def mkdir(self, user_id: str, rel_path: str) -> FileEntry: ...
    def move(self, user_id: str, src: str, dst: str) -> FileEntry: ...
    def delete(self, user_id: str, rel_path: str) -> None: ...
    def zip_dir(self, user_id: str, rel_path: str) -> Iterator[bytes]: ...
    def walk(self, user_id: str, limit: int = 2000) -> list[str]: ...


_CHUNK = 1024 * 1024

# walk(@ 文件索引)不下钻的非隐藏目录:依赖/字节码缓存,量大且无引用价值
_INDEX_SKIP_DIRS = {"node_modules", "__pycache__"}


class LocalFileStore:
    """直接在宿主文件系统上操作某用户的工作区(<host_root>/<user_id>/workspace)。"""

    def __init__(self, host_root: str) -> None:
        self._host_root = Path(host_root)

    def _user_root(self, user_id: str) -> Path:
        # 不在此创建:读操作(list/stat)不该为任意 user_id 物化目录(防随机 UUID DoS,I3)。
        # 真正的懒创建发生在写操作(write/mkdir/move 各自 mkdir 父链)。
        return self._host_root / user_id / "workspace"

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

    def abspath(self, user_id: str, rel_path: str) -> Path:
        """围栏内的绝对路径(可能不存在);越界抛 PathEscape。供需要直接读工作区目录的调用方
        (如从工作区安装技能)复用同一套路径解析,确保与文件抽屉看到的是同一处。"""
        return self._resolve(user_id, rel_path)

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
            if target == root:
                return []  # 全新用户:空工作区,读操作不创建目录(I3)
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
        # 写临时文件再原子替换:中断/超限不会污染已有同名文件,失败一律清掉临时件(I2)。
        tmp = target.parent / (target.name + ".part")
        written = 0
        try:
            with tmp.open("wb") as f:
                while True:
                    chunk = data.read(_CHUNK)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        raise FileTooLarge(f"{rel_path}: exceeds {max_bytes} bytes")
                    f.write(chunk)
            os.replace(tmp, target)
        except Exception:
            tmp.unlink(missing_ok=True)
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

    def walk(self, user_id: str, limit: int = 2000) -> list[str]:
        """递归列出工作区文件的相对 posix 路径(仅文件;composer @ 文件引用的索引)。

        - 剪枝点目录与 node_modules/__pycache__(整棵不下钻):沙箱把 HOME/pip/npm
          缓存路由进工作区(.home 等),点目录又按字节序排最前——不剪的话一次
          pip install 的数千缓存文件就把 limit 配额全部吃光,真实文件一条都进不了
          索引。顶层点【文件】(.env 等)保留,可被 @ 引用。
        - 目录符号链接不下钻(os.walk 默认),文件符号链接跳过(与 zip_dir 同款,
          防越狱读)。
        - 名字无法 UTF-8 round-trip 的跳过:Linux 下 surrogateescape 文件名会让
          JSON 响应渲染时 UnicodeEncodeError → 整个端点永久 500;这类文件纯文本
          @ 也无法引用,跳过自洽。
        - 排序后截断 limit;遍历自带 10×limit 熔断,防巨型工作区全树枚举。
        """
        root = self._user_root(user_id).resolve()
        if not root.exists():
            return []  # 全新用户:空工作区,读操作不创建目录(I3)
        fuse = limit * 10
        out: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            # 原地改 dirnames 才能阻止 os.walk 下钻;排序让熔断截到的子集确定
            dirnames[:] = sorted(
                d for d in dirnames if not d.startswith(".") and d not in _INDEX_SKIP_DIRS
            )
            base = Path(dirpath)
            for name in sorted(filenames):
                p = base / name
                if not p.is_file() or p.is_symlink():
                    continue
                rel = p.relative_to(root).as_posix()
                try:
                    rel.encode("utf-8")
                except UnicodeEncodeError:
                    continue
                out.append(rel)
                if len(out) >= fuse:
                    break
            if len(out) >= fuse:
                break
        out.sort()
        return out[:limit]

    def zip_dir(self, user_id: str, rel_path: str) -> Iterator[bytes]:
        target = self._resolve(user_id, rel_path)
        if not target.exists():
            raise FileNotFoundError(rel_path)
        if not target.is_dir():
            raise NotADirectoryError(rel_path)
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(target.rglob("*")):
                # 跳过符号链接:否则指向围栏外的链接会被打包,造成越狱读(M3)
                if p.is_file() and not p.is_symlink():
                    zf.write(p, p.relative_to(target).as_posix())
        buf.seek(0)
        yield from iter(lambda: buf.read(_CHUNK), b"")
