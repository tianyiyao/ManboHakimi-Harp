@echo off
REM ManboHakimi-Harp 一键打包脚本（双击运行）
REM 产物：dist\ManboHakimi-Harp.exe（单文件，普通用户无需安装 Python）

setlocal
cd /d "%~dp0"
chcp 65001 >nul

set "PYTHON=python"
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"

echo [1/5] 静态检查
"%PYTHON%" -m ruff check --select F821,F822,F823 .
if errorlevel 1 goto fail

echo [2/5] 回归测试
set "QT_QPA_PLATFORM=offscreen"
"%PYTHON%" -m unittest discover -s tests
if errorlevel 1 goto fail

echo [3/5] 应用离屏自检
"%PYTHON%" main.py --selftest
if errorlevel 1 goto fail

echo [4/5] 构建单文件 EXE
set "QT_QPA_PLATFORM="
"%PYTHON%" -m PyInstaller --noconfirm ManboHakimi-Harp.spec
if errorlevel 1 goto fail

echo [5/5] 打包产物离屏自检
powershell -NoProfile -Command "$env:QT_QPA_PLATFORM='offscreen'; $p=Start-Process -FilePath (Resolve-Path '.\dist\ManboHakimi-Harp.exe').Path -ArgumentList '--selftest' -Wait -PassThru -WindowStyle Hidden; exit $p.ExitCode"
if errorlevel 1 goto fail

echo.
echo ===== 测试和打包均通过 =====
echo 产物: dist\ManboHakimi-Harp.exe
pause
exit /b 0

:fail
echo.
echo ===== 检查失败，请查看上方日志 =====
echo 请确认当前 Python 环境已安装 requirements-build.txt
pause
exit /b 1
