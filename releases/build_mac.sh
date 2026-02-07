#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DIST_DIR="${PROJECT_ROOT}/releases/dist-mac"
BUILD_DIR="${PROJECT_ROOT}/releases/build-mac"
SPEC_DIR="${PROJECT_ROOT}/releases/spec-mac"
VENV_DIR="${PROJECT_ROOT}/releases/.venv-mac"

python3 -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"

pip install --upgrade pip wheel
pip install -e "${PROJECT_ROOT}"
pip install pyinstaller

rm -rf "${DIST_DIR}" "${BUILD_DIR}" "${SPEC_DIR}"

pyinstaller \
  "${PROJECT_ROOT}/larksync/cli.py" \
  --name larksync \
  --onefile \
  --console \
  --clean \
  --distpath "${DIST_DIR}" \
  --workpath "${BUILD_DIR}" \
  --specpath "${SPEC_DIR}"

deactivate

echo "macOS binary available at ${DIST_DIR}/larksync"
