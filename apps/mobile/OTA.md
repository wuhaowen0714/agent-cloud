# 移动端 OTA 自动更新

App 启动(已登录)和「设置 → 检查更新」会请求 `GET /api/app/version`,拿到的 `build`
比自身大就弹窗;`force: true` 时不可跳过(禁返回键 / 无「稍后」)。点「立即更新」**在 app 内
直接下载 APK 并拉起系统安装器**(ota_update 插件,免浏览器跳转 / 免"文件可能有害"警告);
下载失败可回退弹窗里的「浏览器下载」。

## 链路

```
App → GET /api/app/version → backend 读 release.json
  → build 比当前大 → 弹窗(force 决定能否跳过)
  → ota_update 下载 /api/app/download/<apk> 到 app 内部存储 → 拉起 PackageInstaller 安装
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
./scripts/release.sh 1.0.1 "修复登录问题"             # 普通更新
./scripts/release.sh 1.1.0 "重大更新,建议升级" --force  # 强制更新
```

**build 号自动取 main 提交数**(`git rev-list --count HEAD`):单调递增、同 commit 幂等、
绝不撞号,因此 `release.sh` 不再收 build 参数。**只允许在 main 分支发版** —— 发版 = 给用户
推 main 上的统一版本;多 worktree 并行开发时各自 `flutter build apk` 本地测试、不走发版,
从而不会撞号 / 互相覆盖 release.json。

> ⚠️ **并发发版会互相覆盖 version 标签**:build 号靠 commit 数单调,但 **version 字符串 / notes
> 是各自传的** —— 两个会话先后发版,后发的 release.json 覆盖先发的(version、notes 都被换掉),
> 且 release.sh 的"清理旧 APK"会删掉对方那个非当前 build 的 APK。真实事故:发了 1.4.0/771,
> 对方随后发 1.3.3/773,把线上标签冲成 1.3.3 并删了 771.apk(773 代码其实已含 771 的功能,只是
> 标签被换)。**因 build-name 编译进 APK**,只改 release.json 的 version 不彻底(装上仍显示旧标签),
> 得用目标 version 重打一个 build 号更高的包。发版前先 `git pull` 看清线上最新 build,多人发版需协调。

脚本做三件事:构建 release APK(`--target-platform android-arm64`)→ 生成 `release.json`
→ scp 到 `st-e:/opt/agent-cloud/data/app-releases`(先传 APK 再切 json,避免指向尚未上传的包),
并清理同目录的旧 APK。可用环境变量覆盖:`ST_SSH`(默认 `st`,部署到 st-e 用
`ST_SSH=st-e-ecs-2`)、`ST_RELEASE_DIR`、`APP_BASE_URL`。

## 实现踩过的坑(改 OTA 前必读)

1. **FileProvider 缺失 → 下载完闪退装不了**:ota_update 7.x 不自带 `<provider>`,App 必须
   在 `AndroidManifest.xml` 声明 `OtaUpdateFileProvider` + `InstallResultReceiver` +
   `res/xml/ota_update_filepaths.xml`,并在 `build.gradle.kts` 开 `coreLibraryDesugaring`
   (`desugar_jdk_libs`)。

2. **固定下载文件名 → 更新"装回旧包"**:`destinationFilename` 若固定(如
   `agent-cloud-update.apk`),部分 ROM(ColorOS)的安装器 / PackageInstaller session 对该
   路径有缓存,下载新版后未覆盖、装回设备上残留的同名旧包 —— 现象:提示有新版、装完版本号
   没变、弹"已安装相同版本"。**必须用带 build 号的唯一文件名**(取 url 末段
   `agent-cloud-<build>.apk`),见 `update_service.dart`。

3. **改 OTA 机制本身无法靠 OTA 生效**:坏的 OTA 逻辑在旧版里、修不了自己,改完需**手动装
   一次**含修复的版本破 circle,之后才恢复正常自更新。上面 1、2 两次修复都踩过这一点。
