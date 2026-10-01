#!/usr/bin/env bash
# Genera backend/requirements-pinned.txt con versiones exactas, desde un entorno limpio.
set -euo pipefail
cd "$(dirname "$0")/.."

rm -rf .venv-pin
python -m venv .venv-pin
.venv-pin/bin/python -m pip install --upgrade pip -q
.venv-pin/bin/python -m pip install -r backend/requirements.txt -q
{
  echo "# Versiones exactas probadas. Instalar con: pip install -r backend/requirements-pinned.txt"
  .venv-pin/bin/python -m pip freeze --exclude-editable
} > backend/requirements-pinned.txt
rm -rf .venv-pin
echo "Listo: backend/requirements-pinned.txt"
