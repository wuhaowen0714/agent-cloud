# 沙箱工具链(curl/wget/git/jq)设计

**日期:** 2026-06-11
**状态:** 设计已批准

## 目标

沙箱镜像(`python:3.13-slim`,缺 curl/wget/git)补齐 agent 高频命令行工具,让 bash 工具开箱可用;git 免身份/ownership 报错。

## 设计

### 镜像(`deploy/sandbox.Dockerfile`)

在 `pip install` 之前加一层 apt(放前面:工具层比应用代码稳定,改 Python 代码不使其失效缓存):

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl wget git jq \
    && rm -rf /var/lib/apt/lists/*
```

- **`ca-certificates`**:https 的根证书,curl/wget/git 的 https 全靠它,必带。
- **`curl` `wget` `git` `jq`**:用户点名三件 + jq(agent 解析 JSON 极高频)。`--no-install-recommends` + 清 apt 缓存控制增量(预计 +60~80MB)。

### git 开箱可用(system 级配置进镜像)

紧随 apt 层:

```dockerfile
RUN git config --system safe.directory '*' \
    && git config --system init.defaultBranch main \
    && git config --system user.name agent \
    && git config --system user.email agent@sandbox.local
```

- **`safe.directory '*'`**:`/workspace` 是宿主 bind mount,容器内 root 与宿主属主 uid 不一致 → git 报 "dubious ownership" 拒绝操作。`'*'` 放行全部(沙箱本就单用户隔离环境)。
- **兜底身份**:否则首次 `git commit` 报 "tell me who you are"。system 级是最低优先级,agent 可在 `/workspace/.home`(HOME 在卷里,持久)自行 `git config --global` 覆盖。
- `init.defaultBranch main`:免去 master/main 的告警。

### 安全语境(spec 如实记录,不在本次实现)

egress 出口本就**未限制**(沙箱的 python 一直能发任意网络请求、读写任意文件),curl/wget/git 只是便利化既有能力,**不扩大攻击面**;沙箱不持有 LLM key(只在 worker),`cap_drop ALL` + `no-new-privileges` 隔离不变。真正的加固项是 **egress 白名单/网络隔离**(多租户 + agent 自主执行下防数据外泄/内网跳板)——独立 backlog,见 roadmap。

## 非目标(YAGNI)

- 不装 unzip/ripgrep/build 工具链等(按需再加);不做 egress 限制(独立项);不改运行期依赖路由(pip/npm 仍走 /workspace 卷)。

## 测试

`services/backend/tests/test_docker_sandbox_isolation.py` 加 `@pytest.mark.docker`(本地有镜像才跑,CI 跳过)用例,复用既有 `DockerProvisioner` + `_exec`:
- `curl --version` / `wget --version` / `git --version` / `jq --version` 在沙箱内 exec 成功(is_error False、输出非空);
- `git init && echo x > f && git add f && git commit -m t` 开箱成功(不报身份/ownership);返回非错。

需重建镜像:`docker build -f deploy/sandbox.Dockerfile -t agent-cloud-sandbox:latest .`(dev_up 第 2.5 步自动)。
