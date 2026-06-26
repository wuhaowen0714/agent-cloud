"""移动端 OTA 版本端点测试。"""

import json

from agent_cloud_backend.api.app_version import load_release


def test_load_release_empty_path():
    assert load_release("").build == 0


def test_load_release_missing_file(tmp_path):
    assert load_release(str(tmp_path / "nope.json")).build == 0


def test_load_release_bad_json(tmp_path):
    f = tmp_path / "r.json"
    f.write_text("not json{", encoding="utf-8")
    assert load_release(str(f)).build == 0


def test_load_release_valid(tmp_path):
    f = tmp_path / "r.json"
    f.write_text(
        json.dumps(
            {
                "version": "1.2.0",
                "build": 5,
                "url": "https://x/app.apk",
                "force": True,
                "notes": "新功能",
            }
        ),
        encoding="utf-8",
    )
    v = load_release(str(f))
    assert v.build == 5
    assert v.version == "1.2.0"
    assert v.force is True
    assert v.url == "https://x/app.apk"


async def test_app_version_endpoint_default(client):
    # 未配置发布文件 → build 0(无更新),且无需登录
    r = await client.get("/app/version")
    assert r.status_code == 200
    assert r.json()["build"] == 0


async def test_download_no_release_404(client):
    # 未配置 app_release_file → 下载端点 404(不会暴露任意文件)
    r = await client.get("/app/download/app.apk")
    assert r.status_code == 404
