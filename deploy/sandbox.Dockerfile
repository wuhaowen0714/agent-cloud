FROM python:3.13-slim

# agent 高频命令行工具(bash 工具开箱可用)。放在应用层之前:工具层比 Python 代码稳定,
# 改代码不使其失效缓存。ca-certificates 是 https 根证书,curl/wget/git 的 https 全靠它。
# 出网未限制是既有语境(python 一直能联网),这些工具只是便利化,不扩大攻击面;
# egress allowlist 是独立加固项(见 roadmap)。
# apt 走阿里云镜像【并强制 https】:部署目标机境外网络受限(连 GitHub 都被掐),拉官方源
# deb.debian.org 会卡死;且部分机房(如 st-e)封了【出站 80 端口】,http 镜像同样连不上 ——
# 故 sed 把 `http://deb.debian.org` 整段换成 `https://mirrors.aliyun.com`(443 通)。trixie 用
# deb822 的 debian.sources;基础镜像 python-slim 自带 ca-certificates,https apt 可直接用。
RUN sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl wget git jq vim \
    && rm -rf /var/lib/apt/lists/*

# 预设系统级 vim 配置:debian vim 的 /etc/vim/vimrc 会自动 source vimrc.local。
# 用户级 ~/.vimrc 在 /workspace(运行时 bind mount)里,镜像构建时写不进,故走系统级。
COPY deploy/sandbox-vimrc /etc/vim/vimrc.local

# git 开箱可用:/workspace 是宿主 bind mount,容器内 root 与宿主属主 uid 不一致会触发
# "dubious ownership" 拒绝操作 → safe.directory '*' 放行(沙箱单用户隔离环境)。
# 兜底身份免去首次 commit 的 "tell me who you are";system 级最低优先级,agent 可在
# /workspace/.home(HOME 在卷里,持久)用 git config --global 自行覆盖。
RUN git config --system safe.directory '*' \
    && git config --system init.defaultBranch main \
    && git config --system user.name agent \
    && git config --system user.email agent@sandbox.local

# 依赖路由:让 pip/npm 等把包装进 /workspace 卷(跨容器重建保留)。详见 spec §8.1。
# 镜像源走国内(阿里云 pip / npmmirror):部署目标机境外网络受限,默认 PyPI/npm registry
# 拉不动——构建期装 grpcio 等会卡,运行期 agent pip/npm install 同理。与 app.Dockerfile 一致。
ENV HOME=/workspace/.home \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    npm_config_registry=https://registry.npmmirror.com \
    PYTHONUSERBASE=/workspace/.home/.local \
    PIP_USER=1 \
    PIP_CACHE_DIR=/workspace/.home/.cache/pip \
    NPM_CONFIG_PREFIX=/workspace/.npm-global \
    npm_config_cache=/workspace/.home/.npm \
    XDG_DATA_HOME=/workspace/.home/.local/share \
    XDG_CACHE_HOME=/workspace/.home/.cache \
    PATH=/workspace/.home/.local/bin:/workspace/.npm-global/bin:/usr/local/bin:/usr/bin:/bin \
    AGENT_CLOUD_SANDBOX_BASE=/workspace \
    AGENT_CLOUD_SANDBOX_PORT=50051 \
    PYTHONUNBUFFERED=1

# 沙箱服务 + 其依赖(common)。从仓库根构建:docker build -f deploy/sandbox.Dockerfile .
WORKDIR /app
COPY packages/common /app/packages/common
COPY services/sandbox /app/services/sandbox
# --no-user 覆盖 PIP_USER=1:构建期装进镜像系统(无卷);运行期用户 pip 才走 --user→/workspace。
RUN pip install --no-cache-dir --no-user /app/packages/common /app/services/sandbox

COPY deploy/sandbox-entrypoint.sh /usr/local/bin/sandbox-entrypoint.sh
RUN chmod +x /usr/local/bin/sandbox-entrypoint.sh

EXPOSE 50051
CMD ["/usr/local/bin/sandbox-entrypoint.sh"]
