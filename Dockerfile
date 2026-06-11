# ========================================
# Stage 1: 构建基础镜像（安装依赖）
# ========================================
FROM python:3.11-slim-bookworm AS builder-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    libpq-dev \
    pkg-config \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.txt

# ========================================
# Stage 2: 构建生产镜像
# ========================================
FROM python:3.11-slim-bookworm AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOME=/opt/bronze-rust \
    TZ=Asia/Shanghai \
    LOG_LEVEL=INFO

WORKDIR $APP_HOME

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    ca-certificates \
    curl \
    tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r appuser && useradd -r -g appuser appuser \
    && mkdir -p /var/log/bronze-rust && chown -R appuser:appuser /var/log/bronze-rust

COPY --from=builder-base /app/wheels /wheels
COPY backend/requirements.txt .

RUN pip install --no-cache --no-cache-dir /wheels/* \
    && rm -rf /wheels requirements.txt \
    && pip install loguru prometheus-client

COPY --chown=appuser:appuser backend/ $APP_HOME/backend/
COPY --chown=appuser:appuser database/ $APP_HOME/database/

RUN chmod +x $APP_HOME/backend/*.py 2>/dev/null || true

ENV PYTHONPATH=$APP_HOME/backend:$PYTHONPATH \
    CONFIG_PATH=$APP_HOME/backend/config.yaml

EXPOSE 8000 9090

USER appuser

ENTRYPOINT ["/usr/bin/tini", "--"]

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--loop", "uvloop"]

# ========================================
# Stage 3: 模拟器镜像
# ========================================
FROM production AS simulator

WORKDIR $APP_HOME

ENV SIMULATOR_MODE=true \
    NUM_ARTIFACTS=200 \
    REPORT_INTERVAL=900 \
    INJECT_PITTING=0 \
    INJECT_CL_PEAK=0 \
    PEAK_INTERVAL_HOURS=6 \
    LOG_LEVEL=INFO

COPY --chown=appuser:appuser backend/mqtt_simulator.py $APP_HOME/simulator.py

USER appuser

CMD ["python", "simulator.py"]

# ========================================
# Stage 4: 开发镜像（含 pytest 和调试工具）
# ========================================
FROM production AS development

USER root

RUN pip install --no-cache-dir pytest pytest-asyncio pytest-cov ipython

USER appuser

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
