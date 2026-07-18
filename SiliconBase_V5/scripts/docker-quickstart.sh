#!/bin/bash
# SiliconBase V5 Docker 快速启动脚本
# 用法: ./docker-quickstart.sh [command]

set -e

# 颜色输出
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查Docker
check_docker() {
    if ! command -v docker &> /dev/null; then
        error "Docker 未安装，请先安装 Docker"
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        error "Docker Compose 未安装，请先安装 Docker Compose"
        exit 1
    fi
    
    # 检查Docker守护进程
    if ! docker info &> /dev/null; then
        error "Docker 守护进程未运行，请启动 Docker"
        exit 1
    fi
    
    success "Docker 环境检查通过"
}

# 初始化环境
init() {
    log "初始化 SiliconBase V5 Docker 环境..."
    
    # 检查 .env 文件
    if [ ! -f ".env" ]; then
        log "创建 .env 配置文件..."
        cp .env.example .env
        success ".env 文件已创建，请根据需要修改配置"
    else
        warn ".env 文件已存在，跳过创建"
    fi
    
    # 创建必要目录
    mkdir -p data models logs config
    
    success "初始化完成"
}

# 启动服务
start() {
    log "启动 SiliconBase V5 服务..."
    
    # 检查 .env 文件
    if [ ! -f ".env" ]; then
        init
    fi
    
    # 构建并启动
    docker-compose up -d --build
    
    success "服务启动成功！"
    echo ""
    echo "访问地址:"
    echo "  - API 文档: http://localhost:8600/docs"
    echo "  - API 服务: http://localhost:8600"
    echo "  - 状态服务: http://localhost:8600"
    echo ""
    echo "查看日志: docker-compose logs -f"
}

# 停止服务
stop() {
    log "停止 SiliconBase V5 服务..."
    docker-compose down
    success "服务已停止"
}

# 完全清理
clean() {
    warn "这将删除所有容器和数据卷！"
    read -p "确定要继续吗? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        docker-compose down -v
        docker system prune -f
        success "清理完成"
    else
        log "取消清理"
    fi
}

# 查看状态
status() {
    echo "容器状态:"
    docker-compose ps
    echo ""
    echo "资源使用:"
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.Status}}"
}

# 查看日志
logs() {
    if [ -z "$1" ]; then
        docker-compose logs -f
    else
        docker-compose logs -f "$1"
    fi
}

# 重启服务
restart() {
    log "重启 SiliconBase V5 服务..."
    docker-compose restart
    success "服务已重启"
}

# 更新服务
update() {
    log "更新 SiliconBase V5 服务..."
    docker-compose pull
    docker-compose up -d --build
    success "服务已更新"
}

# 显示帮助
help() {
    cat << EOF
SiliconBase V5 Docker 快速启动脚本

用法: $0 [command]

命令:
    init      初始化环境（创建 .env 文件和目录）
    start     启动所有服务
    stop      停止所有服务
    restart   重启服务
    status    查看服务状态
    logs      查看日志 [service_name]
    clean     清理所有容器和数据（危险！）
    update    更新并重启服务
    help      显示此帮助

示例:
    $0 init           # 首次运行，初始化环境
    $0 start          # 启动服务
    $0 logs app       # 查看应用日志
    $0 logs -f        # 实时查看所有日志

EOF
}

# 主程序
case "${1:-help}" in
    init)
        check_docker
        init
        ;;
    start)
        check_docker
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    logs)
        logs "$2"
        ;;
    clean)
        clean
        ;;
    update)
        check_docker
        update
        ;;
    help|--help|-h)
        help
        ;;
    *)
        error "未知命令: $1"
        help
        exit 1
        ;;
esac
