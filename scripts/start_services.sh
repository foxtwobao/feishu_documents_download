#!/usr/bin/env bash
# Start FastAPI backend and Next.js frontend inside the container.
set -euo pipefail

BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
DEFAULT_API_BASE="http://localhost:${BACKEND_PORT}"
NEXT_PUBLIC_API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-${DEFAULT_API_BASE}}"

export NEXT_PUBLIC_API_BASE_URL

cleanup() {
  local pids=("${BACKEND_PID:-}" "${FRONTEND_PID:-}")
  if [[ -n "${pids[0]}" || -n "${pids[1]}" ]]; then
    echo
    echo "==> Shutting down services..."
  fi
  for pid in "${pids[@]}"; do
    if [[ -n "${pid}" ]]; then
      kill "${pid}" 2>/dev/null || true
    fi
  done
  for pid in "${pids[@]}"; do
    if [[ -n "${pid}" ]]; then
      wait "${pid}" 2>/dev/null || true
    fi
  done
}

trap cleanup EXIT INT TERM

echo "==> Starting backend on ${BACKEND_HOST}:${BACKEND_PORT}"
uvicorn larksync.web.app:create_app --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" &
BACKEND_PID=$!

pushd /app/webui-client >/dev/null
  echo "==> Starting frontend on ${FRONTEND_HOST}:${FRONTEND_PORT} (API: ${NEXT_PUBLIC_API_BASE_URL})"
  npm run start -- --hostname "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" &
  FRONTEND_PID=$!
popd >/dev/null

EXIT_STATUS=0
if ! wait -n "$BACKEND_PID" "$FRONTEND_PID"; then
  EXIT_STATUS=$?
fi

exit "$EXIT_STATUS"
