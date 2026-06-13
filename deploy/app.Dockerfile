# backend 与 worker 共用的应用镜像(运行命令由 compose 指定)。
# 从仓库根构建:docker build -f deploy/app.Dockerfile .
#
# 用 pip + 阿里镜像而非 `uv sync --frozen`:uv.lock 把下载源锁死在 files.pythonhosted.org
# (锁文件记录完整 URL,UV_DEFAULT_INDEX 无法改写),国内服务器只有 KB/s 级速度,构建必死;
# pip 按需解析、全程走镜像,与 sandbox.Dockerfile 同款做法。代价是不锁版本(个人部署可接受)。
FROM python:3.12-slim

# pip 走清华 mirror(国内快且稳)。PIP_DEFAULT_TIMEOUT/RETRIES:mirror 偶发 ReadTimeout
# (默认 15s 超时扛不住慢响应,构建会死在拉 build 依赖如 hatchling);调大超时 + 多重试容忍
# 抖动(任何源都可能瞬时抖,这是关键防护)。见 deploy/README。
ENV PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

WORKDIR /app
# 只装运行所需的三个包(sandbox 有自己的镜像);common 在同一命令里从本地路径满足
# backend/worker 对 agent-cloud-common 的依赖。
COPY packages/common ./packages/common
COPY services/backend ./services/backend
COPY services/worker ./services/worker
RUN pip install ./packages/common ./services/backend ./services/worker
