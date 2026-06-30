@echo off
chcp 65001 >nul
title SiliconBase V5 - 启动器

echo ============================================
echo    SiliconBase V5 - 完整启动脚本
echo ============================================
echo.

REM 设置项目路径
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

echo [1/4] 检查虚拟环境...
if not exist ".venv\Scripts\python.exe" (
    echo [错误] 虚拟环境不存在，请先运行 install.bat 完成安装
    pause
    exit /b 1
)
echo [OK] 虚拟环境已找到
echo.

echo [2/4] 检查 PostgreSQL 服务...
netstat -ano | findstr ":5432" >nul
if %errorlevel% equ 0 (
    echo [OK] PostgreSQL 服务已运行 (端口5432)
) else (
    echo [警告] PostgreSQL 服务未检测到
    echo   如果您使用 SQLite，可以忽略此警告
    echo   如果使用 PostgreSQL，请先启动数据库服务
    timeout /t 3 /nobreak >nul
)
echo.

echo [3/4] 检查 Ollama 服务...
netstat -ano | findstr ":11434" >nul
if %errorlevel% equ 0 (
    echo [OK] Ollama 服务已运行 (端口11434)
) else (
    echo [提示] Ollama 服务未运行
    echo   如需使用本地模型，请先启动 Ollama
    echo   或使用其他模型连接器 (OpenAI/DeepSeek等)
)
echo.

echo [4/4] 启动后端和前端服务...
echo.
echo   后端服务:
echo     地址: http://localhost:8600
echo     API文档: http://localhost:8600/docs
echo.

start "SiliconBase Backend" cmd /k "cd /d "%PROJECT_DIR%" && .venv\Scripts\python.exe api\run.py"

echo   [OK] 后端服务启动中，等待 5 秒...
timeout /t 5 /nobreak >nul
echo.

echo   前端服务:
echo     地址: http://localhost:5173
echo.

cd frontend
start "SiliconBase Frontend" cmd /k "npm run dev"

echo   [OK] 前端服务启动中，等待 3 秒...
timeout /t 3 /nobreak >nul
echo.

echo [5/4] 服务启动完成检查...
echo.

REM 检查后端端口
netstat -ano | findstr ":8600" >nul
if %errorlevel% equ 0 (
    echo   [OK] 后端服务已启动
) else (
    echo   [警告] 后端服务可能启动失败，请检查窗口输出
)

REM 检查前端端口
netstat -ano | findstr ":5173" >nul
if %errorlevel% equ 0 (
    echo   [OK] 前端服务已启动
) else (
    echo   [等待] 前端服务启动中...
)

echo.
echo ============================================
echo    所有服务已启动！
echo ============================================
echo.
echo 访问地址:
echo   - 前端界面: http://localhost:5173
echo   - 后端 API: http://localhost:8600
echo   - API 文档: http://localhost:8600/docs
echo.
echo 常用命令:
echo   - 查看健康: curl http://localhost:8600/api/health
echo   - 停止服务: 双击 stop_all.bat
echo.
echo Ollama 提示:
echo   - 如需使用本地模型，请确保 Ollama 已启动
echo   - Ollama 下载: https://ollama.com
echo   - 启动命令: ollama serve
echo.
pause >nul
