# =============================================================================
#  FinRAG 前端镜像（docs/08）
#  构建：docker compose -f deploy/docker-compose.yml up -d --build frontend
#  形态：Node 构建 → Nginx 托管静态产物，并把 /api 反代到后端容器
# =============================================================================
FROM node:20-alpine AS build

WORKDIR /app

# 先装依赖，利用层缓存
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# 构建期变量（Vite 在 build 时内联，运行期不可改）
ARG VITE_API_BASE_URL=/api/v1
ARG VITE_APP_TITLE=金融制度知识问答系统
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_APP_TITLE=$VITE_APP_TITLE

COPY . .
RUN npm run build

# -----------------------------------------------------------------------------
FROM nginx:1.27-alpine

# 反代与 SPA 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 构建产物
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
