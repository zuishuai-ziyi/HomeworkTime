@echo off
rem HomeworkTime 客户端打包脚本入口（双击运行）
rem 等价于在 client/ 目录执行: python build.py
cd /d "%~dp0"
python build.py
if errorlevel 1 pause