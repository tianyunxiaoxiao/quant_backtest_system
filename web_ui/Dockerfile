FROM public.ecr.aws/docker/library/node:22-alpine AS frontend
WORKDIR /build
COPY web_ui/frontend/package*.json ./
RUN npm ci
COPY web_ui/frontend/ ./
RUN npm run build

FROM public.ecr.aws/docker/library/python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    QBT_PROJECT_ROOT=/app \
    OUTPUT_ROOT=/data/runs \
    DATABASE_PATH=/data/qbt_web.db
WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/
COPY web_ui/backend/requirements.txt ./web_ui/backend/requirements.txt
RUN pip install --no-cache-dir . -r web_ui/backend/requirements.txt
COPY web_ui/backend/ ./web_ui/backend/
COPY --from=frontend /build/dist ./web_ui/frontend/dist
WORKDIR /app/web_ui/backend
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "qbt_web.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
