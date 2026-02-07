#!/usr/bin/env bash
# Start FastAPI backend inside the container.
# Single-port architecture: FastAPI serves both API and frontend static files.
set -euo pipefail

BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_INTERNAL_PORT="${FRONTEND_INTERNAL_PORT:-3001}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"

cleanup() {
  if [[ -n "${FRONTEND_PID:-}" ]]; then
    kill "${FRONTEND_PID}" 2>/dev/null || true
    wait "${FRONTEND_PID}" 2>/dev/null || true
  fi
  if [[ -n "${BACKEND_PID:-}" ]]; then
    echo
    echo "==> Shutting down..."
    kill "${BACKEND_PID}" 2>/dev/null || true
    wait "${BACKEND_PID}" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

echo "============================================"
echo "  LarkSync Production Server"
echo "============================================"
echo "  Listening on: ${BACKEND_HOST}:${BACKEND_PORT}"
echo "============================================"
echo ""

# Start Next.js standalone server if available
STANDALONE_SERVER="/app/standalone/server.js"
if [[ -f "${STANDALONE_SERVER}" ]]; then
  echo "==> Starting frontend (Next.js standalone) on ${FRONTEND_HOST}:${FRONTEND_INTERNAL_PORT}..."
  export FRONTEND_DEV_URL="http://${FRONTEND_HOST}:${FRONTEND_INTERNAL_PORT}"
  (
    cd /app/standalone
    HOSTNAME="${FRONTEND_HOST}" PORT="${FRONTEND_INTERNAL_PORT}" node server.js
  ) &
  FRONTEND_PID=$!
else
  echo "==> Frontend standalone build not found, running API-only mode."
fi

# Start FastAPI (serves both API and frontend static files)
uvicorn larksync.web.app:create_app --factory --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" &
BACKEND_PID=$!

wait "$BACKEND_PID"
