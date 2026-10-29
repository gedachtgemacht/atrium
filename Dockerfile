# Frontend build
FROM docker.io/library/node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# App
FROM docker.io/library/python:3.12-slim
ARG WITH_NOTES=1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN apt-get update && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project $( [ "$WITH_NOTES" = "1" ] && echo "--extra notes" )
COPY backend/ ./
COPY agents/ /app/agents/
COPY --from=web /web/dist /app/frontend/dist
COPY frontend/public/fonts /app/frontend/public/fonts
RUN uv sync --frozen --no-dev $( [ "$WITH_NOTES" = "1" ] && echo "--extra notes" )
ENV ATRIUM_DATA_DIR=/data ATRIUM_AGENTS_DIR=/app/agents ATRIUM_FRONTEND_DIST=/app/frontend/dist PATH="/app/backend/.venv/bin:$PATH"
VOLUME ["/data"]
EXPOSE 8000
# One worker on purpose: room presence lives in this process's memory only.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn atrium.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-access-log --log-level warning --proxy-headers --forwarded-allow-ips='*'"]
