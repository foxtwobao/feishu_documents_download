# syntax=docker/dockerfile:1.6

FROM node:20-bookworm-slim AS frontend-builder
WORKDIR /app/webui-client

COPY webui-client/package.json webui-client/package-lock.json ./
RUN npm ci

COPY webui-client/ ./
ENV NEXT_PUBLIC_API_BASE_URL="http://localhost:8000"
RUN npm run build \
    && npm prune --omit=dev

FROM node:20-bookworm-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf python3 /usr/bin/python \
    && ln -sf pip3 /usr/bin/pip

COPY pyproject.toml README.md ./
COPY larksync ./larksync
COPY scripts ./scripts

RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install .

COPY . .

COPY --from=frontend-builder /app/webui-client/.next ./webui-client/.next
COPY --from=frontend-builder /app/webui-client/node_modules ./webui-client/node_modules
COPY --from=frontend-builder /app/webui-client/package.json ./webui-client/package.json
COPY --from=frontend-builder /app/webui-client/package-lock.json ./webui-client/package-lock.json

RUN chmod +x scripts/start_services.sh

ENV BACKEND_HOST=0.0.0.0 \
    BACKEND_PORT=8000 \
    FRONTEND_HOST=0.0.0.0 \
    FRONTEND_PORT=3000

EXPOSE 8000
EXPOSE 3000

ENTRYPOINT ["./scripts/start_services.sh"]
