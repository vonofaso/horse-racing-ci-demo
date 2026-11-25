FROM python:3.12.15-alpine3.24@sha256:b658b05ce9c4eb97ec6fc19424818a1f31993659c2b505a532f470e83807815d

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    APP_RELOAD=false
WORKDIR /opt/app
COPY requirements.lock ./
RUN apk upgrade --no-cache \
    && python -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r requirements.lock \
    && python -m pip check \
    && addgroup -S -g 10001 app \
    && adduser -S -D -H -u 10001 -G app -s /sbin/nologin app
COPY app ./app
COPY scripts/__init__.py scripts/db_tools.py scripts/container_health.py ./scripts/
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-m", "scripts.container_health"]
STOPSIGNAL SIGTERM
CMD ["python", "-m", "app"]
