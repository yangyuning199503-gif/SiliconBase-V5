#!/bin/bash
# SiliconBase V5 - 停止脚本 (Linux/Mac)

echo "============================================"
echo "   SiliconBase V5 - 停止服务"
echo "============================================"
echo ""

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# 停止后端
if [ -f ".backend.pid" ]; then
    BACKEND_PID=$(cat .backend.pid)
    if kill -0 $BACKEND_PID 2>/dev/null; then
        echo "停止后端服务 (PID: $BACKEND_PID)..."
        kill $BACKEND_PID
        rm .backend.pid
        echo "[OK] 后端服务已停止"
    else
        echo "[信息] 后端服务未运行"
        rm -f .backend.pid
    fi
else
    echo "[信息] 未找到后端进程文件"
fi

# 停止前端
if [ -f ".frontend.pid" ]; then
    FRONTEND_PID=$(cat .frontend.pid)
    if kill -0 $FRONTEND_PID 2>/dev/null; then
        echo "停止前端服务 (PID: $FRONTEND_PID)..."
        kill $FRONTEND_PID
        rm .frontend.pid
        echo "[OK] 前端服务已停止"
    else
        echo "[信息] 前端服务未运行"
        rm -f .frontend.pid
    fi
else
    echo "[信息] 未找到前端进程文件"
fi

echo ""
echo "[OK] 所有服务已停止"
