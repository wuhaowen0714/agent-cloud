"""移动端 OTA:版本信息 + APK 下载(公开,不需登录)。

发版时把 version/build/url/force/notes 写进 app_release_file 指向的 JSON,APK 放同目录;
App 比对自身 build 决定是否提示更新、从 /app/download/<apk> 拉取。
无文件/解析失败一律回 build 0(=无更新)。
"""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
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


@router.get("/download/{filename}")
async def download_apk(
    filename: str,
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """从 app_release_file 同目录返回 APK(OTA 下载)。只取 basename 防路径穿越。"""
    if not settings.app_release_file:
        raise HTTPException(status_code=404, detail="no release configured")
    target = Path(settings.app_release_file).parent / Path(filename).name
    if not target.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(
        target,
        media_type="application/vnd.android.package-archive",
        filename=target.name,
    )
