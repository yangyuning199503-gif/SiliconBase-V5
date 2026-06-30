#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SiliconBase V5 一键安装脚本 (Linux/macOS)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 打印函数
print_header() {
    echo ""
    echo -e "${CYAN}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}                                                           ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}              ${GREEN}SiliconBase V5 一键安装程序${NC}                  ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}                                                           ${CYAN}║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_info() {
    echo -e "${CYAN}ℹ${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# 检查依赖
check_dependencies() {
    print_info "检查依赖..."
    
    # 检查Docker
    if ! command -v docker &> /dev/null; then
        print_error "Docker 未安装！"
        echo "请访问 https://docs.docker.com/get-docker/ 安装 Docker"
        exit 1
    fi
    print_success "Docker 已安装"
    
    # 检查Docker Compose
    if command -v docker-compose &> /dev/null; then
        COMPOSE_CMD="docker-compose"
    elif docker compose version &> /dev/null 2>&1; then
        COMPOSE_CMD="docker compose"
    else
        print_error "Docker Compose 未安装！"
        exit 1
    fi
    print_success "Docker Compose 可用"
}

# 生成.env文件
generate_env() {
    print_info "生成环境配置文件..."
    
    if [ -f ".env" ]; then
        print_warning ".env 文件已存在，保留现有配置"
        return
    fi
    
    # 生成随机密码
    RANDOM_PASSWORD=$(openssl rand -base64 30 | tr -dc 'a-zA-Z0-9' | head -c 20)
    
    cat > .env << EOF
# SiliconBase V5 环境配置
# 自动生成于 $(date)

# PostgreSQL 密码
POSTGRES_PASSWORD=${RANDOM_PASSWORD}

# API配置
API_PORT=8600
WEBSOCKET_PORT=8601

# 数据库配置
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=siliconbase
POSTGRES_USER=siliconbase

# Redis配置
REDIS_HOST=redis
REDIS_PORT=6379

# ChromaDB配置
CHROMADB_HOST=chromadb
CHROMADB_PORT=8000
EOF
    
    print_success "已生成 .env 配置文件"
}

# 创建必要目录
create_directories() {
    print_info "创建数据目录..."
    mkdir -p data logs checkpoints database/init
    print_success "数据目录已创建"
}

# 拉取镜像
pull_images() {
    print_info "拉取 Docker 镜像..."
    $COMPOSE_CMD pull
    print_success "镜像拉取完成"
}

# 启动服务
start_services() {
    print_info "构建并启动服务..."
    $COMPOSE_CMD up -d --build
    print_success "服务启动完成"
}

# 等待服务就绪
wait_for_services() {
    print_info "等待服务初始化..."
    
    # 等待PostgreSQL
    print_info "  等待 PostgreSQL..."
    for i in {1..30}; do
        if $COMPOSE_CMD exec -T postgres pg_isready -U siliconbase -d siliconbase > /dev/null 2>&1; then
            print_success "  PostgreSQL 就绪"
            break
        fi
        sleep 2
    done
    
    # 等待API
    print_info "  等待 API 服务..."
    for i in {1..30}; do
        if curl -sf http://localhost:8600/api/health > /dev/null 2>&1; then
            print_success "  API 服务就绪"
            break
        fi
        sleep 2
    done
    
    print_success "所有服务已就绪"
}

# 显示完成信息
show_completion() {
    echo ""
    echo -e "${CYAN}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}                    ${GREEN}安装完成！${NC}                             ${CYAN}║${NC}"
    echo -e "${CYAN}╠═══════════════════════════════════════════════════════════╣${NC}"
    echo -e "${CYAN}║${NC}                                                           ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}  访问地址:                                                ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}    前端界面: ${YELLOW}http://localhost:5173${NC}                        ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}    API文档:  ${YELLOW}http://localhost:8600/docs${NC}                   ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}    健康检查: ${YELLOW}http://localhost:8600/api/health${NC}             ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}                                                           ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}  常用命令:                                                ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}    查看日志: ${YELLOW}$0 logs${NC}                                     ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}    停止服务: ${YELLOW}$0 stop${NC}                                     ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}    重启服务: ${YELLOW}$0 restart${NC}                                  ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}    完全卸载: ${YELLOW}$0 uninstall${NC}                                ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}                                                           ${CYAN}║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

# 显示服务状态
show_status() {
    $COMPOSE_CMD ps
}

# 查看日志
show_logs() {
    $COMPOSE_CMD logs -f
}

# 停止服务
stop_services() {
    print_info "停止服务..."
    $COMPOSE_CMD down
    print_success "服务已停止"
}

# 重启服务
restart_services() {
    print_info "重启服务..."
    $COMPOSE_CMD restart
    print_success "服务已重启"
}

# 卸载服务
uninstall_services() {
    print_warning "这将删除所有数据，包括数据库！"
    read -p "确定要卸载吗？(yes/no): " confirm
    if [ "$confirm" = "yes" ]; then
        print_info "卸载服务并删除数据..."
        $COMPOSE_CMD down -v
        rm -rf data logs
        print_success "已卸载并删除所有数据"
    else
        print_info "取消卸载"
    fi
}

# 主安装流程
main_install() {
    print_header
    check_dependencies
    generate_env
    create_directories
    pull_images
    start_services
    wait_for_services
    show_status
    show_completion
}

# 命令处理
case "${1:-install}" in
    install)
        main_install
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs
        ;;
    stop)
        stop_services
        ;;
    restart)
        restart_services
        ;;
    uninstall)
        uninstall_services
        ;;
    *)
        echo "用法: $0 {install|status|logs|stop|restart|uninstall}"
        exit 1
        ;;
esac
