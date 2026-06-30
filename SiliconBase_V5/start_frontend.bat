@echo off
chcp 65001 >nul
echo ==========================================
echo  SiliconBase V5 - 前端启动脚本
echo ==========================================
echo.

cd /d "%~dp0\frontend"

REM 检查npm
npm --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到npm，请确保Node.js已安装
    pause
    exit /b 1
)

echo [启动] 正在启动前端开发服务器...
echo [访问] http://localhost:5173
echo.

npm run dev

pause
