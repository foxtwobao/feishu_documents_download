#!/usr/bin/env bash
# Setup Python virtualenv and install backend & frontend dependencies.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
VENV_DIR="${PROJECT_ROOT}/.venv"

echo "==> Ensuring Python virtual environment..."
if [[ ! -d "${VENV_DIR}" ]]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
pip install --upgrade pip

echo "==> Installing backend dependencies..."
pushd "${PROJECT_ROOT}" >/dev/null
pip install -e ".[dev]"
popd >/dev/null

if [[ -d "${PROJECT_ROOT}/webui-client" ]]; then
  echo "==> Installing frontend dependencies (webui-client)..."
  pushd "${PROJECT_ROOT}/webui-client" >/dev/null
  if [[ -f package-lock.json ]] || [[ -d node_modules ]]; then
    npm install
  else
    npm install
  fi
  popd >/dev/null
else
  echo "==> Skipping frontend install (webui-client directory not found)."
fi

echo "==> All set."
