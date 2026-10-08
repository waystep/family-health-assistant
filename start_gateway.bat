@echo off
rem 家庭健康助手 - 网关启动（Windows）
chcp 65001 >nul
cd /d %~dp0
if not exist .venv (
  echo 首次运行：创建虚拟环境并安装依赖...
  py -3 -m venv .venv
  .venv\Scripts\pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)
.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8900
