from __future__ import annotations


class FileError(Exception):
    """文件操作错误基类。"""


class PathEscape(FileError):
    """路径越出工作区围栏(.. / 绝对 / symlink 越狱 / null 字节)。"""


class FileConflict(FileError):
    """目标已存在(mkdir / move 目的地)。"""


class FileTooLarge(FileError):
    """上传超过 file_upload_max_bytes。"""
