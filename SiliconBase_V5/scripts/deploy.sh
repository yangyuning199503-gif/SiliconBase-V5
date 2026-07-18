#!/bin/bash
# SiliconBase V5 生产部署脚本 (Linux/Mac)
# 版本: 1.0.0
# 使用方法: ./deploy.sh [环境]

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置
ENVIRONMENT="${1:-production}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

log_error() {
    echo -e "${RED}[✗]${NC} $1"
}

# 错误处理
error_exit() {
    log_error "$1"
    exit 1
}

# 打印Banner
echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║              SiliconBase V5 生产部署脚本                  ║"
echo "║                      版本 1.0.0                          ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""
log_info "部署环境: $ENVIRONMENT"
echo ""

# ============================================
# 步骤 1: 系统检查
# ============================================
echo "═══════════════════════════════════════════════════════════"
log_info "[1/10] 系统环境检查..."
echo "═══════════════════════════════════════════════════════════"

# 检查操作系统
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="Linux"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="Mac"
else
    log_warning "未知操作系统: $OSTYPE"
fi
log_info "操作系统: $OS"

# 检查Docker
if ! command -v docker &> /dev/null; then
    error_exit "Docker未安装，请先安装Docker: https://docs.docker.com/get-docker/"
fi
DOCKER_VERSION=$(docker --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
log_success "Docker已安装: $DOCKER_VERSION"

# 检查Docker Compose
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
    COMPOSE_VERSION=$(docker compose version --short)
elif docker-compose --version &> /dev/null; then
    COMPOSE_CMD="docker-compose"
    COMPOSE_VERSION=$(docker-compose --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
else
    error_exit "Docker Compose未安装"
fi
log_success "Docker Compose已安装: $COMPOSE_VERSION"

# 检查Docker守护进程
if ! docker info &> /dev/null; then
    error_exit "Docker守护进程未运行，请启动Docker服务"
fi
log_success "Docker守护进程运行正常"

# 检查Git
if ! command -v git &> /dev/null; then
    log_warning "Git未安装"
else
    GIT_VERSION=$(git --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
    log_success "Git已安装: $GIT_VERSION"
fi

echo ""

# ============================================
# 步骤 2: 代码更新
# ============================================
echo "═══════════════════════════════════════════════════════════"
log_info "[2/10] 更新代码..."
echo "═══════════════════════════════════════════════════════════"

if [ -d ".git" ]; then
    log_info "检测到Git仓库，拉取最新代码..."
    git fetch origin
    git pull origin main || log_warning "拉取代码失败，使用本地代码"
    log_success "代码更新完成"
else
    log_warning "未检测到Git仓库，跳过代码更新"
fi

echo ""

# ============================================
# 步骤 3: 环境配置
# ============================================
echo "═══════════════════════════════════════════════════════════"
log_info "[3/10] 配置环境变量..."
echo "═══════════════════════════════════════════════════════════"

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        log_warning ".env文件不存在，已从.env.example创建"
        log_warning "请编辑.env文件配置实际参数后再运行部署"
        echo ""
        read -p "是否现在编辑.env文件? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            ${EDITOR:-nano} .env
        fi
    else
        error_exit ".env.example文件不存在，无法创建配置"
    fi
else
    log_success ".env文件已存在"
fi

# 验证关键配置
if grep -q "your-" .env 2>/dev/null; then
    log_warning ".env文件中存在未修改的占位符值"
fi

echo ""

# ============================================
# 步骤 4: 目录准备
# ============================================
echo "═══════════════════════════════════════════════════════════"
log_info "[4/10] 准备数据目录..."
echo "═══════════════════════════════════════════════════════════"

mkdir -p data logs models config
chmod 755 data logs models config
log_success "数据目录准备完成"

echo ""

# ============================================
# 步骤 5: 镜像构建
# ============================================
echo "═══════════════════════════════════════════════════════════"
log_info "[5/10] 构建Docker镜像..."
echo "═══════════════════════════════════════════════════════════"

# 使用缓存构建
log_info "开始构建镜像（使用缓存）..."
$COMPOSE_CMD build

if [ $? -eq 0 ]; then
    log_success "Docker镜像构建成功"
else
    error_exit "Docker镜像构建失败"
fi

echo ""

# ============================================
# 步骤 6: 启动服务
# ============================================
echo "═══════════════════════════════════════════════════════════"
log_info "[6/10] 启动服务..."
echo "═══════════════════════════════════════════════════════════"

# 停止旧服务
log_info "停止旧服务..."
$COMPOSE_CMD down --remove-orphans 2>/dev/null || true

# 启动新服务
log_info "启动新服务..."
$COMPOSE_CMD up -d

if [ $? -eq 0 ]; then
    log_success "服务启动成功"
else
    error_exit "服务启动失败"
fi

# 等待服务初始化
log_info "等待服务初始化（10秒）..."
sleep 10

echo ""

# ============================================
# 步骤 7: 健康检查
# ============================================
echo "═══════════════════════════════════════════════════════════"
log_info "[7/10] 执行健康检查..."
echo "═══════════════════════════════════════════════════════════"

HEALTH_URL="http://localhost:8600/api/health"
MAX_RETRIES=30
RETRY_COUNT=0

log_info "检查服务健康状态: $HEALTH_URL"

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -f -s "$HEALTH_URL" > /dev/null 2>&1; then
        log_success "健康检查通过"
        break
    fi
    
    RETRY_COUNT=$((RETRY_COUNT + 1))
    log_info "等待服务就绪... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    log_error "健康检查失败，服务可能未正常启动"
    log_info "查看日志: $COMPOSE_CMD logs --tail=50 app"
    exit 1
fi

echo ""

# ============================================
# 步骤 8: 冒烟测试
# ============================================
echo "═══════════════════════════════════════════════════════════"
log_info "[8/10] 运行冒烟测试..."
echo "═══════════════════════════════════════════════════════════"

if [ -f "tests/test_smoke.py" ]; then
    # 检查Python是否可用
    if command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &> /dev/null; then
        PYTHON_CMD="python"
    else
        log_warning "Python未安装，跳过冒烟测试"
        PYTHON_CMD=""
    fi
    
    if [ -n "$PYTHON_CMD" ]; then
        log_info "运行冒烟测试..."
        if $PYTHON_CMD tests/test_smoke.py; then
            log_success "冒烟测试通过"
        else
            log_warning "冒烟测试失败，但部署将继续"
        fi
    fi
else
    log_warning "冒烟测试脚本不存在，跳过"
fi

echo ""

# ============================================
# 步骤 9: 服务状态
# ============================================
echo "═══════════════════════════════════════════════════════════"
log_info "[9/10] 服务状态检查..."
echo "═══════════════════════════════════════════════════════════"

echo ""
echo "容器状态:"
echo "───────────────────────────────────────────────────────────"
$COMPOSE_CMD ps

echo ""
echo "资源使用:"
echo "───────────────────────────────────────────────────────────"
docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.Status}}"

echo ""

# ============================================
# 步骤 10: 部署完成
# ============================================
echo "═══════════════════════════════════════════════════════════"
log_info "[10/10] 部署完成！"
echo "═══════════════════════════════════════════════════════════"

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                    部署成功！                            ║"
echo "╠═══════════════════════════════════════════════════════════╣"
echo "║  访问地址:                                               ║"
echo "║    • API 文档:    http://localhost:8600/docs             ║"
echo "║    • 健康检查:    http://localhost:8600/api/health       ║"
echo "║    • 监控指标:    http://localhost:8600/api/metrics      ║"
echo "║    • WebSocket:   ws://localhost:8600/ws/{user_id}       ║"
echo "╠═══════════════════════════════════════════════════════════╣"
echo "║  常用命令:                                               ║"
echo "║    • 查看日志:    $COMPOSE_CMD logs -f app               ║"
echo "║    • 重启服务:    $COMPOSE_CMD restart app               ║"
echo "║    • 停止服务:    $COMPOSE_CMD down                      ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# 健康检查详情
log_info "健康检查详情:"
curl -s http://localhost:8600/api/health | python3 -m json.tool 2>/dev/null || curl -s http://localhost:8600/api/health

echo ""
log_success "部署流程全部完成！"

# 记录部署日志
DEPLOY_LOG="logs/deploy-$(date +%Y%m%d-%H%M%S).log"
mkdir -p logs
echo "部署完成: $(date)" >> "$DEPLOY_LOG"
echo "环境: $ENVIRONMENT" >> "$DEPLOY_LOG"
echo "Docker版本: $DOCKER_VERSION" >> "$DEPLOY_LOG"
echo "Compose版本: $COMPOSE_VERSION" >> "$DEPLOY_LOG"
log_info "部署日志已保存: $DEPLOY_LOG"
