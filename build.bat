@echo off
REM ManboHakimi-Harp 一键打包脚本（双击运行）
REM 产物： dist\ManboHakimi-Harp.exe （单文件，约 46MB，无需安装 Python）

setlocal
set VENV=C:\Users\Administrator\.workbuddy\binaries\python\envs\harpguide\Scripts

"%VENV%\python.exe" -m PyInstaller --noconfirm ManboHakimi-Harp.spec

if %errorlevel%==0 (
    echo.
    echo ===== 打包成功 =====
    echo 产物: dist\ManboHakimi-Harp.exe
    echo 可将 dist\ManboHakimi-Harp.exe 复制到任意目录运行
) else (
    echo.
    echo ===== 打包失败，请检查上方日志 =====
)
pause
