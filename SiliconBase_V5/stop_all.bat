@echo off
chcp 65001 >nul
title SiliconBase V5 - 停止服务

echo ============================================
echo    SiliconBase V5 - 停止服务
echo ============================================
echo.

REM 查找并停止后端服务
for /f "tokens=2" %%a in ('tasklist ^| findstr "python.exe"') do (
    echo 停止后端进程 (PID: %%a)...
    taskkill /PID %%a /F >nul 2>&1
)

REM 查找并停止前端服务
for /f "tokens=2" %%a in ('tasklist ^| findstr "node.exe"') do (
    echo 停止前端进程 (PID: %%a)...
    taskkill /PID %%a /F >nul 2>&1
)

echo.
echo [OK] 所有服务已停止
pause
