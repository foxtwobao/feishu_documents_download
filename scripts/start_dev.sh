#!/usr/bin/env bash
# Start backend FastAPI (uvicorn) and frontend Next.js dev server.
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

BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"

cleanup() {
  echo
  echo "==> Stopping services..."
  pkill -P $$ || true
}

trap cleanup EXIT INT TERM

echo "==> Starting backend on ${BACKEND_HOST}:${BACKEND_PORT}..."
uvicorn larksync.web.app:create_app --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" --reload &
BACKEND_PID=$!

if [[ -d "${PROJECT_ROOT}/webui-client" ]]; then
  API_BASE_URL="$(python3 - <<'PY'
from urllib.parse import urlsplit
from pathlib import Path

from larksync.config import load_config

config = load_config(Path("config.toml"))
callback = config.web.oauth.callback_url if config and config.web and config.web.oauth else None
if callback:
    parts = urlsplit(callback)
    if parts.scheme and parts.netloc:
        print(f"{parts.scheme}://{parts.netloc}")
        raise SystemExit
print("http://localhost:8000")
PY
)"
  export NEXT_PUBLIC_API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-$API_BASE_URL}"

  echo "==> Starting frontend (Next.js dev server) on port ${FRONTEND_PORT:-3000}..."
  pushd "${PROJECT_ROOT}/webui-client" >/dev/null
  npm run dev &
  FRONTEND_PID=$!
  popd >/dev/null
else
  echo "==> Frontend directory not found; skipping npm dev server."
fi

echo "==> Services running. Press Ctrl+C to stop."
wait
