#!/bin/bash
# SiliconBase V5 - 完整启动脚本 (Linux/Mac)

set -e  # 遇到错误立即退出

echo "============================================"
echo "   SiliconBase V5 - 完整启动脚本"
echo "============================================"
echo ""

# 设置项目路径
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# 检测操作系统
OS="unknown"
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
fi

echo "[1/4] 检查虚拟环境..."
if [ ! -f ".venv/bin/python" ]; then
    echo "[错误] 虚拟环境不存在，请先创建:"
    echo "  python3 -m venv .venv"
    echo "  .venv/bin/pip install -r requirements.txt"
    exit 1
fi
echo "[OK] 虚拟环境已找到"
echo ""

echo "[2/4] 检查 PostgreSQL..."
if command -v pg_isready &> /dev/null; then
    if pg_isready -q; then
        echo "[OK] PostgreSQL 正在运行"
    else
        echo "[警告] PostgreSQL 未启动"
        echo "  如需启动: sudo service postgresql start"
    fi
else
    echo "[警告] 未找到 PostgreSQL 命令"
fi
echo ""

echo "[3/4] 检查 Ollama..."
if command -v ollama &> /dev/null; then
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "[OK] Ollama 正在运行"
    else
        echo "[警告] Ollama 可能未启动"
        echo "  如需启动: ollama serve"
    fi
else
    echo "[警告] 未找到 Ollama"
    echo "  请安装: https://ollama.com"
fi
echo ""

echo "[4/4] 启动后端 API 服务..."
echo "  服务地址: http://localhost:8600"
echo "  API 文档: http://localhost:8600/docs"
echo ""

# 使用nohup在后台启动
cd "$PROJECT_DIR"
nohup .venv/bin/python api/run.py > logs/backend.log 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > .backend.pid

echo "[OK] 后端服务启动中 (PID: $BACKEND_PID)，等待 5 秒..."
sleep 5

echo ""
echo "[5/4] 启动前端开发服务器..."
echo "  前端地址: http://localhost:5173"
echo ""

cd frontend
nohup npm run dev > ../logs/frontend.log 2>&1 &
FRONTEND_PID=$!
echo $FRONTEND_PID > ../.frontend.pid

echo "[OK] 前端服务启动中 (PID: $FRONTEND_PID)，等待 3 秒..."
sleep 3

echo ""
echo "============================================"
echo "   所有服务已启动！"
echo "============================================"
echo ""
echo "访问地址:"
echo "  - 前端界面: http://localhost:5173"
echo "  - 后端 API: http://localhost:8600"
echo "  - API 文档: http://localhost:8600/docs"
echo ""
echo "查看日志:"
echo "  tail -f logs/backend.log"
echo "  tail -f logs/frontend.log"
echo ""
echo "停止服务:"
echo "  ./stop_all.sh"
echo ""

# 保持脚本运行（可选）
# wait
