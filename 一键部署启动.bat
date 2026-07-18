@echo off
chcp 65001 >nul
title SiliconBase V5 - 一键部署启动
setlocal EnableDelayedExpansion

echo  =========================================
echo  =                                       =
echo  =      SiliconBase V5 一键部署启动       =
echo  =                                       =
echo  =========================================
echo.

REM 设置项目路径
set "PROJECT_DIR=%~dp0SiliconBase_V5"
cd /d "%PROJECT_DIR%"

echo [1/5] 检查虚拟环境...
if not exist ".venv\Scripts\python.exe" (
    echo [错误] 虚拟环境不存在，请先运行 install.bat 完成安装
    pause
    exit /b 1
)
echo [OK] 虚拟环境已找到
echo.

echo [2/5] 检查 PostgreSQL 服务...
netstat -ano | findstr ":5432" >nul
if %errorlevel% equ 0 (
    echo [OK] PostgreSQL 服务已运行 - 端口5432
) else (
    echo [警告] PostgreSQL 服务未检测到
    echo   如果您使用 SQLite，可以忽略此警告
    echo   如果使用 PostgreSQL，请先启动数据库服务
    timeout /t 3 /nobreak >nul
)
echo.

echo [3/5] 检查 Redis 服务...
netstat -ano | findstr ":6379" | findstr "LISTENING" >nul
if %errorlevel% equ 0 (
    echo [OK] Redis 已在运行 - 端口6379
) else (
    echo [启动] 正在启动 Redis...
    set "REDIS_SERVER=%~dp0tools\redis\redis-server.exe"
    set "REDIS_CONF=%~dp0tools\redis\redis.windows.conf"
    if exist "!REDIS_SERVER!" (
        start "Redis" cmd /c "cd /d %~dp0tools\redis && redis-server.exe redis.windows.conf"
        timeout /t 3 /nobreak >nul
        netstat -ano | findstr ":6379" | findstr "LISTENING" >nul
        if !errorlevel! equ 0 (
            echo [OK] Redis 启动成功
        ) else (
            echo [警告] Redis 可能启动失败，将使用内存缓存
        )
    ) else (
        echo [警告] 未找到 redis-server.exe，将使用内存缓存替代
    )
)
echo.

echo [4/5] 检查 Ollama 服务...
netstat -ano | findstr ":11434" >nul
if %errorlevel% equ 0 (
    echo [OK] Ollama 服务已运行 - 端口11434
) else (
    echo [启动] 正在启动 Ollama...
    ollama --version >nul 2>&1
    if !errorlevel! equ 0 (
        start "Ollama" cmd /c "ollama serve"
        timeout /t 5 /nobreak >nul
        netstat -ano | findstr ":11434" >nul
        if !errorlevel! equ 0 (
            echo [OK] Ollama 启动成功
        ) else (
            echo [警告] Ollama 启动失败，请手动运行 ollama serve
        )
    ) else (
        echo [警告] 未找到 ollama 命令，如需本地模型请手动安装
        echo   下载地址: https://ollama.com
    )
)
echo.

echo [5/5] 启动后端和前端服务...
echo.
echo   后端服务:
echo     地址: http://localhost:8600
echo     API文档: http://localhost:8600/docs
echo.

start "SiliconBase Backend" cmd /k "cd /d "%PROJECT_DIR%" && .venv\Scripts\python.exe start_unified.py"

echo   [OK] 后端服务启动中，等待 8 秒...
timeout /t 8 /nobreak >nul
echo.

echo   前端服务:
echo     地址: http://localhost:5173
echo.

cd frontend
start "SiliconBase Frontend" cmd /k "npm run dev"

echo   [OK] 前端服务启动中，等待 3 秒...
timeout /t 3 /nobreak >nul
echo.

echo [6/5] 服务启动完成检查...
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
echo  =========================================
echo     所有服务已启动！
echo  =========================================
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
