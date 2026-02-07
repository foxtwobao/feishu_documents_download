# syntax=docker/dockerfile:1.6

# Build Next.js frontend
FROM node:20-bookworm-slim AS frontend-builder
WORKDIR /app/webui-client

COPY webui-client/package.json webui-client/package-lock.json ./
RUN npm ci

COPY webui-client/ ./
# Build frontend - API calls will be same-origin (no separate API URL needed)
RUN npm run build \
    && npm prune --omit=dev

# Runtime image
FROM python:3.11-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

# Install Node.js to run Next.js standalone server
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml README.md ./
COPY larksync ./larksync
COPY scripts ./scripts

RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install .

COPY . .

# Copy Next.js standalone build output
COPY --from=frontend-builder /app/webui-client/.next/standalone ./standalone
COPY --from=frontend-builder /app/webui-client/.next/static ./standalone/.next/static
COPY --from=frontend-builder /app/webui-client/public ./standalone/public

RUN chmod +x scripts/start_services.sh

# Single port architecture - only expose 8000
ENV BACKEND_HOST=0.0.0.0 \
    BACKEND_PORT=8000

EXPOSE 8000

ENTRYPOINT ["./scripts/start_services.sh"]
