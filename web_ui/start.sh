#!/usr/bin/env bash
set -e

# 切换到脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON=python3

# 1. 创建/激活 Python 虚拟环境
if [ ! -d ".venv" ]; then
  echo "创建 Python 虚拟环境..."
  "$PYTHON" -m venv .venv
fi
source .venv/bin/activate

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
