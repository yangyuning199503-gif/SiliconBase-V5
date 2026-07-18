#!/bin/bash
# SiliconBase V5 Docker 入口脚本
# 用于初始化容器环境和启动服务

set -e

echo "=========================================="
echo "  SiliconBase V5 容器启动脚本"
echo "=========================================="

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查环境变量
log_info "检查环境变量..."

# 设置默认值
: "${STORAGE_BACKEND:=redis}"
: "${API_PORT:=8000}"
: "${STATUS_PORT:=8502}"
: "${WS_PORT:=8503}"
: "${OLLAMA_URL:=http://ollama:11434}"

log_info "STORAGE_BACKEND: $STORAGE_BACKEND"
log_info "API_PORT: $API_PORT"
log_info "OLLAMA_URL: $OLLAMA_URL"

# 等待依赖服务
wait_for_service() {
    local host=$1
    local port=$2
    local service_name=$3
    local max_attempts=${4:-30}
    
    log_info "等待 $service_name 服务就绪..."
    
    attempt=0
    while ! nc -z $host $port; do
        attempt=$((attempt + 1))
        if [ $attempt -ge $max_attempts ]; then
            log_error "$service_name 服务在 $max_attempts 次尝试后仍未就绪"
            return 1
        fi
        log_warning "$service_name 未就绪，第 $attempt 次重试..."
        sleep 2
    done
    
    log_success "$service_name 服务已就绪"
    return 0
}

# 检查Redis连接
if [ "$STORAGE_BACKEND" = "redis" ]; then
    # 从REDIS_URL解析主机和端口
    REDIS_HOST=$(echo $REDIS_URL | sed -E 's|redis://([^:]+):.*|\1|')
    REDIS_PORT=$(echo $REDIS_URL | sed -E 's|redis://[^:]+:([0-9]+).*|\1|')
    : "${REDIS_HOST:=redis}"
    : "${REDIS_PORT:=6379}"
    
    if ! wait_for_service $REDIS_HOST $REDIS_PORT "Redis"; then
        log_error "无法连接到Redis服务，请检查配置"
        exit 1
    fi
fi

# 检查Ollama连接（可选，不阻塞启动）
OLLAMA_HOST=$(echo $OLLAMA_URL | sed -E 's|http://([^:]+):.*|\1|')
OLLAMA_PORT=$(echo $OLLAMA_URL | sed -E 's|http://[^:]+:([0-9]+).*|\1|')
: "${OLLAMA_HOST:=ollama}"
: "${OLLAMA_PORT:=11434}"

if wait_for_service $OLLAMA_HOST $OLLAMA_PORT "Ollama" 10; then
    log_success "AI服务已就绪"
    
    # 检查默认模型是否可用
    log_info "检查AI模型..."
    sleep 2
else
    log_warning "AI服务暂时不可用，应用将继续启动"
fi

# 创建必要的目录
log_info "创建必要的目录..."
mkdir -p /app/data/state /app/data/user_configs /app/logs /app/models
chmod -R 755 /app/data /app/logs

# 检查配置文件
log_info "检查配置文件..."
if [ ! -f "/app/config/global.yaml" ]; then
    log_warning "全局配置文件不存在，将使用默认配置"
fi

# 验证Python环境
log_info "验证Python环境..."
python --version
pip --version

# 检查关键依赖
log_info "检查关键依赖..."
python -c "import fastapi, uvicorn, redis, torch" 2>/dev/null && log_success "关键依赖检查通过" || log_warning "部分依赖检查失败"

# 打印启动信息
echo ""
echo "=========================================="
echo "  启动 SiliconBase V5"
echo "=========================================="
echo "  API地址: http://0.0.0.0:$API_PORT"
echo "  状态服务: http://0.0.0.0:$STATUS_PORT"
echo "  WebSocket: ws://0.0.0.0:$WS_PORT"
echo "=========================================="
echo ""

# 根据传入的参数决定启动方式
if [ $# -eq 0 ]; then
    # 默认启动API服务
    log_info "启动API服务..."
    exec python api/run.py --host 0.0.0.0 --port $API_PORT
else
    # 执行传入的命令
    log_info "执行命令: $@"
    exec "$@"
fi
