#!/usr/bin/env bash
set -euo pipefail

if [ ! -f backend/requirements.txt ]; then
  echo "backend/requirements.txt not found"
  exit 1
fi

python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
pip freeze > backend/requirements-pinned.txt
echo "Pinned requirements written to backend/requirements-pinned.txt"
