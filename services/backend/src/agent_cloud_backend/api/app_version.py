"""移动端 OTA:最新版本信息端点(公开,不需登录)。

发版时把 version/build/url/force/notes 写进 app_release_file 指向的 JSON;
App 比对自身 build 决定是否提示更新。无文件/解析失败一律回 build 0(=无更新)。
"""

import json
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from agent_cloud_backend.config import Settings, get_settings

router = APIRouter(prefix="/app", tags=["app"])


class AppVersionInfo(BaseModel):
    version: str = "0.0.0"
    build: int = 0  # 单调递增构建号,App 用它比对
    url: str = ""  # APK 下载地址
    force: bool = False  # 强制更新(App 端不可跳过)
    notes: str = ""  # 更新说明


def load_release(path: str) -> AppVersionInfo:
    """从 JSON 文件读发布信息;路径空/不存在/解析失败一律回默认(build 0)。"""
    if path:
        p = Path(path)
        if p.exists():
            try:
                return AppVersionInfo(**json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                pass
    return AppVersionInfo()


@router.get("/version", response_model=AppVersionInfo)
async def get_app_version(
    settings: Settings = Depends(get_settings),
) -> AppVersionInfo:
    return load_release(settings.app_release_file)
