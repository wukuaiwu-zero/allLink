# 支持 linux/amd64 与 linux/arm64 (RK3566 / 香橙派 / 树莓派)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# 安装音频转码与局域网 mDNS 发现所需的底层系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libavahi-compat-libdnssd1 \
    avahi-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY core/ ./core/
COPY static/ ./static/

EXPOSE 8000

CMD ["uvicorn", "core.main:app", "--host", "0.0.0.0", "--port", "8000"]
