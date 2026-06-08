from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol


class ObjectStore(Protocol):
    """skill 包对象存储抽象。生产用 S3;本仓库用 LocalObjectStore。"""

    def put_dir(self, prefix: str, src_dir: Path) -> None: ...
    def get_dir(self, prefix: str, dst_dir: Path) -> None: ...
    def delete_prefix(self, prefix: str) -> None: ...
    def exists(self, prefix: str) -> bool: ...


class LocalObjectStore:
    """本地文件系统替身:prefix → root/prefix 目录。"""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def _path(self, prefix: str) -> Path:
        if not prefix or prefix.strip() in (".", "/", ""):
            raise ValueError(f"invalid object store prefix: {prefix!r}")
        root = self._root.resolve()
        p = (self._root / prefix).resolve()
        if p != root and root not in p.parents:
            raise ValueError(f"prefix escapes object store root: {prefix!r}")
        return p

    def put_dir(self, prefix: str, src_dir: Path) -> None:
        dst = self._path(prefix)
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        # symlinks=True:保留链接、不跟随。否则源目录(尤其用户工作区)里指向宿主文件的链接会把
        # 宿主内容拷进技能包→物化进沙箱。api 层已拒符号链接,这里兜底堵 TOCTOU。
        shutil.copytree(src_dir, dst, symlinks=True)

    def get_dir(self, prefix: str, dst_dir: Path) -> None:
        src = self._path(prefix)
        if not src.exists():
            raise FileNotFoundError(prefix)
        dst = Path(dst_dir)
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, symlinks=True)  # 同 put_dir:保留链接、不跟随(防越权拷贝宿主内容)

    def delete_prefix(self, prefix: str) -> None:
        p = self._path(prefix)
        if p.exists():
            shutil.rmtree(p)

    def exists(self, prefix: str) -> bool:
        return self._path(prefix).exists()
