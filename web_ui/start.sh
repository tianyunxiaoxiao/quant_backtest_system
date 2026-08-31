#!/usr/bin/env bash
set -e

# 切换到脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -x "$SCRIPT_DIR/../.venv/bin/python" ]; then
  PYTHON="$SCRIPT_DIR/../.venv/bin/python"
else
  PYTHON=python3
fi

# 1. 创建/激活 Python 虚拟环境
if [ ! -d ".venv" ]; then
  echo "创建 Python 虚拟环境..."
  "$PYTHON" -m venv .venv
fi
source .venv/bin/activate

python - <<'PY'
import sys

if sys.version_info < (3, 12):
    raise SystemExit(
        "web_ui 依赖 numpy 2.5.1，需要 Python 3.12+；请删除或移走 web_ui/.venv 后重试。"
    )
PY

# 2. 安装后端依赖
echo "安装后端依赖..."
pip install -q -r backend/requirements.txt

# 3. 安装并构建前端
cd frontend
if [ ! -d "node_modules" ]; then
  echo "安装前端依赖..."
  npm install
fi
echo "构建前端..."
npm run build
cd ..

# 4. 启动后端
echo "启动服务: http://localhost:8000"
cd backend
PYTHONPATH=. exec uvicorn qbt_web.main:app --host 0.0.0.0 --port 8000
