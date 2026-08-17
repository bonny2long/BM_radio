# syntax=docker/dockerfile:1
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --gid 10001 bmradio \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin bmradio

COPY requirements-runtime.txt ./requirements-runtime.txt
RUN python -m pip install --no-cache-dir --requirement requirements-runtime.txt

COPY --chown=10001:10001 app/ ./app/
COPY --chown=10001:10001 migrations/ ./migrations/
COPY --chown=10001:10001 alembic.ini ./alembic.ini

RUN mkdir -p /app-cache/artwork \
    && chown -R 10001:10001 /app-cache

USER 10001:10001
EXPOSE 8094

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=6 \
    CMD ["python", "-m", "app.container_healthcheck"]

CMD ["python", "-m", "app.server"]
