#!/usr/bin/env bash
# Start backend FastAPI and frontend Next.js dev server.
# All traffic goes through port 8000 (single-port architecture).
# Next.js runs on internal port 3001, proxied by FastAPI.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "Virtual environment not found at ${VENV_DIR}."
  echo "Run scripts/install_dependencies.sh first."
  exit 1
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

# Single port for external access
BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"

# Internal port for Next.js dev server (not exposed externally)
FRONTEND_INTERNAL_PORT="${FRONTEND_INTERNAL_PORT:-3001}"
FRONTEND_DEV_URL="http://localhost:${FRONTEND_INTERNAL_PORT}"

cleanup() {
  echo
  echo "==> Stopping services..."
  pkill -P $$ || true
}

trap cleanup EXIT INT TERM

# Start Next.js dev server on internal port first
if [[ -d "${PROJECT_ROOT}/webui-client" ]]; then
  echo "==> Starting frontend (Next.js dev server) on internal port ${FRONTEND_INTERNAL_PORT}..."
  pushd "${PROJECT_ROOT}/webui-client" >/dev/null
  # Next.js only listens on localhost (internal only)
  npm run dev -- --hostname localhost --port "${FRONTEND_INTERNAL_PORT}" &
  FRONTEND_PID=$!
  popd >/dev/null
  
  # Wait for Next.js to start
  echo "==> Waiting for frontend to be ready..."
  for i in {1..30}; do
    if curl -s "http://localhost:${FRONTEND_INTERNAL_PORT}" >/dev/null 2>&1; then
      echo "==> Frontend ready."
      break
    fi
    sleep 1
  done
else
  echo "==> Frontend directory not found, skipping Next.js dev server."
  FRONTEND_DEV_URL=""
fi

# Export for FastAPI to use
export FRONTEND_DEV_URL

echo "==> Starting backend on ${BACKEND_HOST}:${BACKEND_PORT}..."
echo "    (Frontend proxied from ${FRONTEND_DEV_URL})"
uvicorn larksync.web.app:create_app --factory --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" --reload &
BACKEND_PID=$!

echo ""
echo "============================================"
echo "  LarkSync Development Server"
echo "============================================"
echo "  Access URL: http://localhost:${BACKEND_PORT}"
echo "  API Docs:   http://localhost:${BACKEND_PORT}/docs"
echo "============================================"
echo ""
echo "Press Ctrl+C to stop."
wait
