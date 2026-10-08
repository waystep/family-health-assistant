#!/bin/bash
# 家庭健康助手 - 网关启动（macOS 本机测试用）
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "首次运行：创建虚拟环境并安装依赖…"
  python3.11 -m venv .venv
  .venv/bin/pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
fi
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8900
