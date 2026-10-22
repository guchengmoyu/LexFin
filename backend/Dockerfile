# =============================================================================
#  FinRAG 后端镜像（docs/08）
#  构建：docker compose -f deploy/docker-compose.yml up -d --build
#  参数 WITH_LIBREOFFICE=true 时安装 LibreOffice 以支持 .doc（镜像 +约 500MB）
# =============================================================================
FROM python:3.11-slim

ARG WITH_LIBREOFFICE=false

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_ENDPOINT=https://hf-mirror.com \
    DATA_DIR=/data

WORKDIR /app

# --- 系统依赖：Tesseract 5（chi_sim + eng）+ curl（healthcheck） ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-chi-sim \
        tesseract-ocr-eng \
        libgl1 \
        libglib2.0-0 \
        curl \
    && if [ "$WITH_LIBREOFFICE" = "true" ]; then \
           apt-get install -y --no-install-recommends libreoffice-writer ; \
       fi \
    && rm -rf /var/lib/apt/lists/*

# --- Python 依赖（先装依赖层，利用 Docker 缓存） ---
COPY requirements.txt ./
RUN pip install -r requirements.txt

# --- 应用代码 ---
COPY app ./app

# --- 数据目录：上传文件 / OCR 缓存 / 模型权重（运行期挂载卷） ---
RUN mkdir -p /data/uploads /data/ocr_cache /data/models

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=5 \
    CMD curl -fsS http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
