@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv-ocr\Scripts\python.exe" (
  echo Python environment is missing. Follow README.md first.
  pause
  exit /b 1
)
set PYTHONIOENCODING=utf-8
chcp 65001 >nul
"%~dp0.venv-ocr\Scripts\python.exe" "%~dp0scripts\start_private_access.py"
if errorlevel 1 pause
