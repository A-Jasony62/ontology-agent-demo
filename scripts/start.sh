#!/usr/bin/env bash
# 一键启动：建环境 → 装依赖 → 起服务 → 打开浏览器
# 等价于：make run（首次先 make setup）
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  echo "[1/3] 创建虚拟环境 .venv ..."
  python3 -m venv .venv
else
  echo "[1/3] 使用已有虚拟环境 .venv"
fi

echo "[2/3] 安装依赖 ..."
.venv/bin/pip install -q -r requirements.txt

echo "[3/3] 启动推理 API（http://127.0.0.1:8000）..."
if command -v open >/dev/null 2>&1; then
  (sleep 1 && open http://127.0.0.1:8000) >/dev/null 2>&1 &
fi
exec .venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000
