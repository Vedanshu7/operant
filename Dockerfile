# syntax=docker/dockerfile:1.7

# --- frontend ---------------------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

# --- backend ----------------------------------------------------------------
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_SYSTEM_PYTHON=1
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
COPY alembic.ini ./
RUN uv sync --frozen --no-dev --no-extra macos
COPY --from=web /web/dist ./web/dist
ENV PATH="/app/.venv/bin:${PATH}" \
    OPERANT_SERVER__HOST=0.0.0.0 \
    OPERANT_SERVER__STATIC_DIR=/app/web/dist \
    OPERANT_PATHS__ROOT=/data
VOLUME ["/data"]
EXPOSE 7080
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7080/api/v1/health', timeout=3).status == 200 else 1)"
CMD ["operant", "serve"]
