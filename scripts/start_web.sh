#!/bin/bash
# Start the LarkSync Web backend server

set -e

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Activate virtual environment if exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Default host and port
HOST="${LARKSYNC_HOST:-0.0.0.0}"
PORT="${LARKSYNC_PORT:-8000}"

echo "Starting LarkSync Web API on $HOST:$PORT..."
echo "API docs: http://$HOST:$PORT/docs"

# Start uvicorn with FastAPI app
exec uvicorn larksync.web.app:create_app --factory --host "$HOST" --port "$PORT" --reload
