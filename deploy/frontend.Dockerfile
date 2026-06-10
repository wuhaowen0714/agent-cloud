# 前端:vite 构建 → nginx 托管静态 + /api 反代到 backend。
# 从仓库根构建:docker build -f deploy/frontend.Dockerfile .
FROM node:22-alpine AS build
WORKDIR /app
# 国内服务器:npm 走 npmmirror
RUN npm config set registry https://registry.npmmirror.com
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM nginx:alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
