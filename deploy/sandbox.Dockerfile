FROM python:3.13-slim

# 依赖路由:让 pip/npm 等把包装进 /workspace 卷(跨容器重建保留)。详见 spec §8.1。
ENV HOME=/workspace/.home \
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
