#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
  echo "虚拟环境不存在，请先运行 ./start.sh"
  exit 1
fi

source .venv/bin/activate
cd backend
PYTHONPATH=. exec uvicorn qbt_web.main:app --host 0.0.0.0 --port 8000
