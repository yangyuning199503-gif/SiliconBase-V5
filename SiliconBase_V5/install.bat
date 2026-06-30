@echo off
chcp 65001 >nul
title SiliconBase V5 - 一键安装

:: ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
:: SiliconBase V5 一键安装脚本 (Windows)
:: ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

echo.
echo ╔═══════════════════════════════════════════════════════════╗
echo ║                                                           ║
echo ║              SiliconBase V5 一键安装程序                  ║
echo ║                                                           ║
echo ╚═══════════════════════════════════════════════════════════╝
echo.

:: 检查管理员权限
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 请以管理员身份运行此脚本！
    pause
    exit /b 1
)

:: 检查Docker安装
echo [1/7] 检查 Docker 安装状态...
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] Docker 未安装！请先安装 Docker Desktop:
    echo   https://www.docker.com/products/docker-desktop
    pause
    exit /b 1
)
echo   ✓ Docker 已安装

:: 检查Docker Compose
echo [2/7] 检查 Docker Compose...
docker-compose --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   ✗ docker-compose 命令不存在，尝试使用 docker compose...
    docker compose version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [错误] Docker Compose 不可用！
        pause
        exit /b 1
    )
    set COMPOSE_CMD=docker compose
) else (
    set COMPOSE_CMD=docker-compose
)
echo   ✓ Docker Compose 可用

:: 检查目录
echo [3/7] 检查安装目录...
if not exist "docker-compose.yml" (
    echo [错误] 未找到 docker-compose.yml，请在项目根目录运行此脚本
    pause
    exit /b 1
)
echo   ✓ 安装目录正确

:: 生成随机密码
echo [4/7] 生成安全密码...
if not exist ".env" (
    for /f "tokens=*" %%a in ('powershell -Command "-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 20 | ForEach-Object { [char]$_ })"') do set RANDOM_PASSWORD=%%a
    
    echo # SiliconBase V5 环境配置 > .env
    echo # 自动生成于 %date% %time% >> .env
    echo. >> .env
    echo # PostgreSQL 密码 >> .env
    echo POSTGRES_PASSWORD=%RANDOM_PASSWORD% >> .env
    echo. >> .env
    echo # API配置 >> .env
    echo API_PORT=8600 >> .env
    echo WEBSOCKET_PORT=8601 >> .env
    echo. >> .env
    echo # 数据库配置 >> .env
    echo POSTGRES_HOST=postgres >> .env
    echo POSTGRES_PORT=5432 >> .env
    echo POSTGRES_DB=siliconbase >> .env
    echo POSTGRES_USER=siliconbase >> .env
    echo. >> .env
    echo # Redis配置 >> .env
    echo REDIS_HOST=redis >> .env
    echo REDIS_PORT=6379 >> .env
    echo. >> .env
    echo # ChromaDB配置 >> .env
    echo CHROMADB_HOST=chromadb >> .env
    echo CHROMADB_PORT=8000 >> .env
    
    echo   ✓ 已生成 .env 配置文件
) else (
    echo   ✓ .env 文件已存在，保留现有配置
)

:: 创建必要目录
echo [5/7] 创建数据目录...
if not exist "data" mkdir data
if not exist "logs" mkdir logs
if not exist "checkpoints" mkdir checkpoints
if not exist "database\init" mkdir database\init
echo   ✓ 数据目录已创建

:: 拉取镜像
echo [6/7] 拉取 Docker 镜像...
%COMPOSE_CMD% pull
echo   ✓ 镜像拉取完成

:: 启动服务
echo [7/7] 启动服务...
%COMPOSE_CMD% up -d --build

:: 等待服务启动
echo.
echo [等待] 等待服务初始化...
timeout /t 10 /nobreak >nul

:: 检查服务状态
echo.
echo [检查] 服务状态:
%COMPOSE_CMD% ps

echo.
echo ╔═══════════════════════════════════════════════════════════╗
echo ║                    安装完成！                             ║
echo ╠═══════════════════════════════════════════════════════════╣
echo ║                                                           ║
echo ║  访问地址:                                                ║
echo ║    前端界面: http://localhost:5173                        ║
echo ║    API文档:  http://localhost:8600/docs                   ║
echo ║    健康检查: http://localhost:8600/api/health             ║
echo ║                                                           ║
echo ║  常用命令:                                                ║
echo ║    查看日志: install.bat logs                             ║
echo ║    停止服务: install.bat stop                             ║
echo ║    重启服务: install.bat restart                          ║
echo ║    完全卸载: install.bat uninstall                        ║
echo ║                                                           ║
echo ╚═══════════════════════════════════════════════════════════╝
echo.
pause
exit /b 0

:: 处理命令行参数
:logs
%COMPOSE_CMD% logs -f
exit /b 0

:stop
%COMPOSE_CMD% down
echo 服务已停止
pause
exit /b 0

:restart
%COMPOSE_CMD% restart
echo 服务已重启
pause
exit /b 0

:uninstall
echo [警告] 这将删除所有数据！
set /p confirm="确定要卸载吗？(yes/no): "
if /i "%confirm%"=="yes" (
    %COMPOSE_CMD% down -v
    echo 已卸载并删除所有数据
) else (
    echo 取消卸载
)
pause
exit /b 0
