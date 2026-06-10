# backend 与 worker 共用的应用镜像(同一 uv workspace,装一次;运行命令由 compose 指定)。
# 从仓库根构建:docker build -f deploy/app.Dockerfile .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    # 国内服务器:PyPI 走阿里云镜像(uv 读 UV_DEFAULT_INDEX)
    UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/

RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ uv

WORKDIR /app
# 完整 workspace:uv sync 需要全部成员的 pyproject;生成的 gRPC 桩已提交在 packages/common。
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY services ./services
# --all-packages:workspace 根的 sync 默认只装根包,必须显式装全部成员(backend/worker/common…)
RUN uv sync --frozen --no-dev --all-packages
