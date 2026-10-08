@echo off
rem 家庭健康助手 - 微信桥启动（需要 Windows + 微信桌面版已登录）
chcp 65001 >nul
cd /d %~dp0
if not exist .venv (
  echo 首次运行：创建虚拟环境并安装依赖...
  py -3 -m venv .venv
  .venv\Scripts\pip install -r requirements.txt wxauto -i https://pypi.tuna.tsinghua.edu.cn/simple
)
.venv\Scripts\pip show wxauto >nul 2>&1 || .venv\Scripts\pip install wxauto -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv\Scripts\python bridge\wechat_bridge.py
