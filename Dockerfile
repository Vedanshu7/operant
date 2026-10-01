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
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
COPY alembic.ini ./
# Optional extras, e.g. --build-arg OPERANT_EXTRAS="privacy observability".
ARG OPERANT_EXTRAS=""
# The spaCy pipeline the privacy extra loads (about 500 MB for _lg).
ARG SPACY_MODEL="en_core_web_lg"
RUN uv sync --frozen --no-dev --no-extra macos \
    $(for extra in $OPERANT_EXTRAS; do printf -- '--extra %s ' "$extra"; done)
RUN case " $OPERANT_EXTRAS " in *" privacy "*) \
    uv pip install --python /app/.venv/bin/python \
    "https://github.com/explosion/spacy-models/releases/download/${SPACY_MODEL}-3.8.0/${SPACY_MODEL}-3.8.0-py3-none-any.whl";; \
    esac
COPY --from=web /web/dist ./web/dist
# OpenSSL's CPU probe in the cryptography wheel dies with an illegal instruction
# under Docker on recent Apple chips; skipping it only drops hardware speedups.
ENV PATH="/app/.venv/bin:${PATH}" \
    OPENSSL_armcap=0 \
    OPERANT_SERVER__HOST=0.0.0.0 \
    OPERANT_SERVER__STATIC_DIR=/app/web/dist \
    OPERANT_PATHS__ROOT=/data
# Run unprivileged; only the data volume is writable.
RUN useradd --system --uid 10001 --home-dir /app operant \
    && mkdir -p /data && chown operant /data
USER operant
VOLUME ["/data"]
EXPOSE 7080
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7080/healthz', timeout=3).status == 200 else 1)"
CMD ["operant", "serve"]
