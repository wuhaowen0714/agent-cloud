# 移动端 OTA 自动更新

App 启动(已登录)和「设置 → 检查更新」会请求 `GET /api/app/version`,拿到的 `build`
比自身大就弹窗;`force: true` 时不可跳过(禁返回键 / 无「稍后」)。点「立即更新」用系统
浏览器下载 APK 并安装。

## 链路

```
App 启动 → GET /api/app/version → 后端读 release.json
  → build 比当前大 → 弹窗(force 决定能否跳过)
  → launchUrl(url) → 浏览器下载 APK → 系统安装
```

## 一次性服务端配置(st-e)

### 1. nginx 托管 APK 下载目录

在 18080 的 server 块内加 location(放在 `/api` location 之外):

```nginx
location /app/download/ {
    alias /data/app-releases/;
    autoindex off;
}
```

`nginx -s reload` 生效。

### 2. 后端挂载发布目录 + 指向 release.json

docker-compose 的 backend service:

```yaml
volumes:
  - /data/app-releases:/data/app-releases:ro
environment:
  AGENT_CLOUD_APP_RELEASE_FILE: /data/app-releases/release.json
```

重启 backend 生效。未配置该 env 时端点返回 `build: 0`(永远不提示),不影响其它功能。

## 发版流程

```bash
cd apps/mobile
./scripts/release.sh 1.0.1 2 "修复登录问题"          # 普通更新
./scripts/release.sh 1.1.0 3 "重大更新,建议升级" --force  # 强制更新
```

脚本做三件事:构建 release APK(带 build 号)→ 生成 `release.json` → scp 到
`st-e:/data/app-releases`(先传 APK 再切 json)。

`build` 必须**单调递增**(App 靠它比对);`version` 是给人看的语义版本。

可用环境变量覆盖默认:`ST_SSH`(SSH alias,默认 `st`)、`ST_RELEASE_DIR`、`APP_BASE_URL`。
