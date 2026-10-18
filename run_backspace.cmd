@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv-ocr\Scripts\python.exe" (
  echo Python environment is missing. Follow the setup steps in README.md first.
  pause
  exit /b 1
)
"%~dp0.venv-ocr\Scripts\python.exe" "%~dp0scripts\start_backspace.py"
if errorlevel 1 pause
