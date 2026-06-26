# 移动端 OTA 自动更新

App 启动(已登录)和「设置 → 检查更新」会请求 `GET /api/app/version`,拿到的 `build`
比自身大就弹窗;`force: true` 时不可跳过(禁返回键 / 无「稍后」)。点「立即更新」用系统
浏览器下载 APK 并安装。

## 链路

```
App → GET /api/app/version → backend 读 release.json
  → build 比当前大 → 弹窗(force 决定能否跳过)
  → launchUrl(/api/app/download/<apk>) → backend 返回 APK → 系统安装
```

APK 由 **backend 直接托管**(`/api/app/download/<file>` → FileResponse),走现成的 nginx
`/api` 反代,**不需要改 nginx**。

## 一次性服务端配置(st-e)

backend 挂载发布目录 + 指向 release.json —— 已写进 `deploy/compose.yml`:

```yaml
backend:
  environment:
    AGENT_CLOUD_APP_RELEASE_FILE: /data/app-releases/release.json
  volumes:
    - /opt/agent-cloud/data/app-releases:/data/app-releases:ro
```

首次部署前在 st-e 建目录,然后重建 backend 容器:

```bash
mkdir -p /opt/agent-cloud/data/app-releases
cd /opt/agent-cloud/repo
docker compose --env-file .env -f deploy/compose.yml up -d --build backend
```

未配置/无文件时 `/app/version` 返回 build 0(永不提示),`/app/download` 返回 404,不影响其它功能。

## 发版流程

```bash
cd apps/mobile
./scripts/release.sh 1.0.1 2 "修复登录问题"             # 普通更新
./scripts/release.sh 1.1.0 3 "重大更新,建议升级" --force  # 强制更新
```

脚本做三件事:构建 release APK(带 build 号)→ 生成 `release.json` → scp 到
`st-e:/opt/agent-cloud/data/app-releases`(先传 APK 再切 json,避免指向尚未上传的包)。

`build` 必须**单调递增**(App 靠它比对);`version` 是给人看的语义版本。
可用环境变量覆盖:`ST_SSH`(SSH alias,默认 `st`)、`ST_RELEASE_DIR`、`APP_BASE_URL`。
