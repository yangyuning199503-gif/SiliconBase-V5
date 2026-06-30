#!/usr/bin/env python3
"""
SiliconBase Cloud API - 监控和健康检查模块
提供 Prometheus 指标收集和健康检查功能

作者: SiliconBase Team
版本: 1.0.0
"""

import asyncio
import os
import time
from contextvars import ContextVar

# PostgreSQL健康检查，使用core.memory中的PostgresConnectionPool
from typing import Any

import psutil
import requests

# Prometheus 指标导入
try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, Info, generate_latest
    from prometheus_client.core import CollectorRegistry
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    print("[Monitoring] prometheus-client 未安装，监控功能不可用")
    print("[Monitoring] 请执行: pip install prometheus-client psutil")

# ============================================================================
# Prometheus 指标定义
# ============================================================================

if PROMETHEUS_AVAILABLE:
    # 创建独立的注册表
    REGISTRY = CollectorRegistry()

    # 应用信息
    APP_INFO = Info('siliconbase_app', 'Application information', registry=REGISTRY)
    APP_INFO.info({'version': '1.0.0', 'name': 'SiliconBase Cloud API'})

    # 请求计数 - 按方法和端点
    REQUEST_COUNT = Counter(
        'siliconbase_requests_total',
        'Total requests',
        ['method', 'endpoint', 'status_code'],
        registry=REGISTRY
    )

    # 请求持续时间
    REQUEST_DURATION = Histogram(
        'siliconbase_request_duration_seconds',
        'Request duration in seconds',
        ['method', 'endpoint'],
        registry=REGISTRY
    )

    # 活跃请求数
    ACTIVE_REQUESTS = Gauge(
        'siliconbase_active_requests',
        'Number of active requests',
        registry=REGISTRY
    )

    # AI调用计数 - 按模型和状态
    AI_CALLS = Counter(
        'siliconbase_ai_calls_total',
        'Total AI calls',
        ['model', 'status', 'provider'],
        registry=REGISTRY
    )

    # AI调用持续时间
    AI_CALL_DURATION = Histogram(
        'siliconbase_ai_call_duration_seconds',
        'AI call duration in seconds',
        ['model', 'provider'],
        registry=REGISTRY
    )

    # 活跃会话数
    ACTIVE_SESSIONS = Gauge(
        'siliconbase_active_sessions',
        'Number of active sessions',
        registry=REGISTRY
    )

    # WebSocket连接数
    WEBSOCKET_CONNECTIONS = Gauge(
        'siliconbase_websocket_connections',
        'Number of active WebSocket connections',
        registry=REGISTRY
    )

    # 任务队列深度 - 按用户
    TASK_QUEUE_DEPTH = Gauge(
        'siliconbase_task_queue_depth',
        'Task queue depth per user',
        ['user_id'],
        registry=REGISTRY
    )

    # 任务状态计数
    TASK_STATUS = Counter(
        'siliconbase_tasks_total',
        'Total tasks by status',
        ['status', 'type'],
        registry=REGISTRY
    )

    # 系统内存使用
    MEMORY_USAGE = Gauge(
        'siliconbase_memory_usage_bytes',
        'Memory usage in bytes',
        ['type'],
        registry=REGISTRY
    )

    # 系统CPU使用
    CPU_USAGE = Gauge(
        'siliconbase_cpu_usage_percent',
        'CPU usage percentage',
        registry=REGISTRY
    )

    # 数据库连接状态
    DATABASE_HEALTH = Gauge(
        'siliconbase_database_health',
        'Database health status (1=healthy, 0=unhealthy)',
        ['type'],
        registry=REGISTRY
    )

    # Redis连接状态
    REDIS_HEALTH = Gauge(
        'siliconbase_redis_health',
        'Redis health status (1=healthy, 0=unhealthy)',
        registry=REGISTRY
    )

    # AI服务状态
    AI_SERVICE_HEALTH = Gauge(
        'siliconbase_ai_service_health',
        'AI service health status (1=healthy, 0=unhealthy)',
        ['provider'],
        registry=REGISTRY
    )

    # 错误计数
    ERROR_COUNT = Counter(
        'siliconbase_errors_total',
        'Total errors',
        ['type', 'endpoint'],
        registry=REGISTRY
    )


# ============================================================================
# 请求跟踪上下文
# ============================================================================

request_start_time_var: ContextVar[float | None] = ContextVar('request_start_time', default=None)


# ============================================================================
# 健康检查函数
# ============================================================================

async def check_database() -> dict[str, Any]:
    """检查 PostgreSQL 数据库连接状态"""
    result = {
        "status": "unhealthy",
        "type": "postgresql",
        "details": {
            "host": os.getenv("POSTGRES_HOST", "localhost"),
            "port": int(os.getenv("POSTGRES_PORT", "5432")),
            "database": os.getenv("POSTGRES_DB", "siliconbase")
        }
    }

    try:
        from core.memory.postgres_pool import AsyncPostgresPool
        pool = await AsyncPostgresPool.get_pool()
        async with pool.acquire() as conn:
            version = await conn.fetchval("SELECT version()")
            await conn.fetchval("SELECT count(*) FROM memories LIMIT 1")
            result["status"] = "healthy"
            result["details"]["version"] = version
    except Exception as e:
        result["status"] = "unhealthy"
        result["details"]["error"] = str(e)
        print(f"[Monitoring] 数据库健康检查失败: {e}")

    # 更新 Prometheus 指标
    if PROMETHEUS_AVAILABLE:
        DATABASE_HEALTH.labels(type="postgresql").set(1 if result["status"] == "healthy" else 0)

    return result


async def check_redis() -> dict[str, Any]:
    """检查 Redis 连接状态"""
    result = {
        "status": "unhealthy",
        "type": "redis",
        "response_time_ms": 0,
        "details": {}
    }

    start_time = time.time()

    try:
        from core.redis_backend import get_async_redis_storage

        storage = await get_async_redis_storage()
        if storage and await storage.is_available():
            client = await storage._pool.get_client()
            if client:
                # 测试连接
                await client.ping()
                info = await client.info()

                result["status"] = "healthy"
                result["details"]["version"] = info.get("redis_version", "unknown")
                result["details"]["connected_clients"] = info.get("connected_clients", 0)
                result["details"]["used_memory_human"] = info.get("used_memory_human", "unknown")
            else:
                result["status"] = "degraded"
                result["details"]["warning"] = "Redis client is None"
        else:
            result["status"] = "disabled"
            result["details"]["message"] = "Redis not configured, using memory backend"

    except Exception as e:
        result["status"] = "unhealthy"
        result["details"]["error"] = str(e)

    result["response_time_ms"] = round((time.time() - start_time) * 1000, 2)

    # 更新 Prometheus 指标
    if PROMETHEUS_AVAILABLE:
        if result["status"] == "healthy":
            REDIS_HEALTH.set(1)
        elif result["status"] == "disabled":
            REDIS_HEALTH.set(1)  # Disabled is OK, just not using it
        else:
            REDIS_HEALTH.set(0)

    return result


async def check_ai_service() -> dict[str, Any]:
    """检查 AI 服务可用性"""
    result = {
        "status": "unhealthy",
        "type": "ai_service",
        "response_time_ms": 0,
        "details": {}
    }

    start_time = time.time()

    try:
        import aiohttp

        from core.config import config

        # 从配置获取 AI 服务地址
        ai_config = config.get("ai", {})
        providers = ai_config.get("providers", {})
        ollama_config = providers.get("ollama", {})
        base_url = ollama_config.get("base_url", "http://localhost:11434")

        # 尝试连接 AI 服务（原生异步）
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session, session.get(f"{base_url}/api/tags") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = [m.get("name") for m in data.get("models", [])]

                    result["status"] = "healthy"
                    result["details"]["base_url"] = base_url
                    result["details"]["available_models"] = models[:5]  # 只显示前5个
                    result["details"]["total_models"] = len(models)
                else:
                    result["status"] = "unhealthy"
                    result["details"]["error"] = f"HTTP {resp.status}"

    except requests.exceptions.ConnectionError:
        result["status"] = "unhealthy"
        result["details"]["error"] = "无法连接到 AI 服务，请前往前端左侧工具栏 → AI模型选择进行配置"
    except Exception as e:
        result["status"] = "unhealthy"
        result["details"]["error"] = str(e)

    result["response_time_ms"] = round((time.time() - start_time) * 1000, 2)

    # 更新 Prometheus 指标
    if PROMETHEUS_AVAILABLE:
        AI_SERVICE_HEALTH.labels(provider="ai_service").set(1 if result["status"] == "healthy" else 0)

    return result


def get_memory_usage() -> dict[str, Any]:
    """获取内存使用情况"""
    result = {
        "status": "healthy",
        "type": "system",
        "details": {}
    }

    try:
        # 系统内存
        system_memory = psutil.virtual_memory()
        result["details"]["system"] = {
            "total_mb": round(system_memory.total / (1024 * 1024), 2),
            "available_mb": round(system_memory.available / (1024 * 1024), 2),
            "used_mb": round(system_memory.used / (1024 * 1024), 2),
            "percent": system_memory.percent
        }

        # 进程内存
        process = psutil.Process(os.getpid())
        process_memory = process.memory_info()
        result["details"]["process"] = {
            "rss_mb": round(process_memory.rss / (1024 * 1024), 2),
            "vms_mb": round(process_memory.vms / (1024 * 1024), 2)
        }

        # 更新 Prometheus 指标
        if PROMETHEUS_AVAILABLE:
            MEMORY_USAGE.labels(type="system_total").set(system_memory.total)
            MEMORY_USAGE.labels(type="system_used").set(system_memory.used)
            MEMORY_USAGE.labels(type="process_rss").set(process_memory.rss)

    except Exception as e:
        result["status"] = "unhealthy"
        result["details"]["error"] = str(e)

    return result


def get_cpu_usage() -> dict[str, Any]:
    """获取 CPU 使用情况"""
    result = {
        "status": "healthy",
        "details": {}
    }

    try:
        # 系统 CPU 使用率
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count = psutil.cpu_count()

        result["details"]["percent"] = cpu_percent
        result["details"]["count"] = cpu_count

        # 进程 CPU 使用率
        process = psutil.Process(os.getpid())
        process_cpu = process.cpu_percent(interval=0.1)
        result["details"]["process_percent"] = process_cpu

        # 更新 Prometheus 指标
        if PROMETHEUS_AVAILABLE:
            CPU_USAGE.set(cpu_percent)

    except Exception as e:
        result["status"] = "unhealthy"
        result["details"]["error"] = str(e)

    return result


async def perform_health_checks() -> dict[str, Any]:
    """执行所有健康检查"""
    start_time = time.time()

    # 并行执行所有检查
    db_check, redis_check, ai_check = await asyncio.gather(
        check_database(),
        check_redis(),
        check_ai_service(),
        return_exceptions=True
    )

    # 处理异常
    checks = {
        "database": db_check if not isinstance(db_check, Exception) else {
            "status": "unhealthy",
            "error": str(db_check)
        },
        "redis": redis_check if not isinstance(redis_check, Exception) else {
            "status": "unhealthy",
            "error": str(redis_check)
        },
        "ai_service": ai_check if not isinstance(ai_check, Exception) else {
            "status": "unhealthy",
            "error": str(ai_check)
        },
        "memory_usage": get_memory_usage(),
        "cpu_usage": get_cpu_usage()
    }

    # 确定整体状态
    critical_checks = ["database", "ai_service"]  # 关键服务
    all_healthy = all(
        checks[c]["status"] == "healthy"
        for c in critical_checks
        if c in checks and isinstance(checks[c], dict)
    )

    any_unhealthy = any(
        checks[c]["status"] == "unhealthy"
        for c in checks
        if c in checks and isinstance(checks[c], dict) and "status" in checks[c]
    )

    if all_healthy:
        overall_status = "healthy"
    elif any_unhealthy:
        overall_status = "degraded"
    else:
        overall_status = "unknown"

    return {
        "status": overall_status,
        "checks": checks,
        "timestamp": time.time(),
        "response_time_ms": round((time.time() - start_time) * 1000, 2)
    }


# ============================================================================
# 指标收集辅助函数
# ============================================================================

def record_request_start() -> float:
    """记录请求开始时间"""
    start_time = time.time()
    request_start_time_var.set(start_time)
    if PROMETHEUS_AVAILABLE:
        ACTIVE_REQUESTS.inc()
    return start_time


def record_request_end(method: str, endpoint: str, status_code: int):
    """记录请求结束"""
    if PROMETHEUS_AVAILABLE:
        ACTIVE_REQUESTS.dec()
        REQUEST_COUNT.labels(
            method=method.upper(),
            endpoint=endpoint,
            status_code=str(status_code)
        ).inc()

        start_time = request_start_time_var.get()
        if start_time:
            duration = time.time() - start_time
            REQUEST_DURATION.labels(
                method=method.upper(),
                endpoint=endpoint
            ).observe(duration)


def record_ai_call(model: str, provider: str, status: str, duration: float = 0):
    """记录 AI 调用"""
    if PROMETHEUS_AVAILABLE:
        AI_CALLS.labels(
            model=model or "unknown",
            provider=provider or "unknown",
            status=status
        ).inc()

        if duration > 0:
            AI_CALL_DURATION.labels(
                model=model or "unknown",
                provider=provider or "unknown"
            ).observe(duration)


def record_error(error_type: str, endpoint: str = "unknown"):
    """记录错误"""
    if PROMETHEUS_AVAILABLE:
        ERROR_COUNT.labels(
            type=error_type,
            endpoint=endpoint
        ).inc()


def update_session_count(count: int):
    """更新活跃会话数"""
    if PROMETHEUS_AVAILABLE:
        ACTIVE_SESSIONS.set(count)


def update_websocket_count(count: int):
    """更新 WebSocket 连接数"""
    if PROMETHEUS_AVAILABLE:
        WEBSOCKET_CONNECTIONS.set(count)


def update_task_queue_depth(user_id: str, count: int):
    """更新任务队列深度"""
    if PROMETHEUS_AVAILABLE:
        TASK_QUEUE_DEPTH.labels(user_id=user_id).set(count)


def record_task_status(status: str, task_type: str = "default"):
    """记录任务状态"""
    if PROMETHEUS_AVAILABLE:
        TASK_STATUS.labels(status=status, type=task_type).inc()


# ============================================================================
# Prometheus 指标导出
# ============================================================================

def get_prometheus_metrics() -> tuple:
    """
    获取 Prometheus 格式的指标数据

    Returns:
        tuple: (content_type, data)
    """
    if not PROMETHEUS_AVAILABLE:
        return "text/plain", b"# prometheus-client not installed"

    # 更新系统指标
    try:
        # 更新内存指标
        memory = psutil.virtual_memory()
        MEMORY_USAGE.labels(type="system_total").set(memory.total)
        MEMORY_USAGE.labels(type="system_used").set(memory.used)
        MEMORY_USAGE.labels(type="system_available").set(memory.available)

        # 更新 CPU 指标
        CPU_USAGE.set(psutil.cpu_percent())

        # 更新进程内存
        process = psutil.Process(os.getpid())
        proc_mem = process.memory_info()
        MEMORY_USAGE.labels(type="process_rss").set(proc_mem.rss)
        MEMORY_USAGE.labels(type="process_vms").set(proc_mem.vms)

    except Exception as e:
        print(f"[Monitoring] Error updating metrics: {e}")

    return CONTENT_TYPE_LATEST, generate_latest(REGISTRY)


# ============================================================================
# Kubernetes Probe 检查
# ============================================================================

async def readiness_check() -> dict[str, Any]:
    """
    Kubernetes Readiness Probe
    检查应用是否准备好接收流量
    """
    checks = await perform_health_checks()

    # Readiness: 需要数据库和基本功能正常
    is_ready = checks["checks"]["database"]["status"] == "healthy"

    return {
        "ready": is_ready,
        "status": "ready" if is_ready else "not_ready",
        "timestamp": time.time(),
        "checks": {
            "database": checks["checks"]["database"]["status"],
            "redis": checks["checks"]["redis"]["status"]
        }
    }


async def liveness_check() -> dict[str, Any]:
    """
    Kubernetes Liveness Probe
    检查应用是否存活（进程未死锁/卡死）
    """
    try:
        # 基本检查：进程是否响应
        process = psutil.Process(os.getpid())
        process_status = process.status()

        # 检查是否卡死（CPU使用率为0且运行时间长）
        cpu_percent = process.cpu_percent(interval=0.1)
        memory_info = process.memory_info()

        is_alive = process_status == psutil.STATUS_RUNNING

        return {
            "alive": is_alive,
            "status": "alive" if is_alive else "dead",
            "timestamp": time.time(),
            "details": {
                "process_status": process_status,
                "cpu_percent": cpu_percent,
                "memory_rss_mb": round(memory_info.rss / (1024 * 1024), 2)
            }
        }
    except Exception as e:
        return {
            "alive": False,
            "status": "error",
            "timestamp": time.time(),
            "error": str(e)
        }


# ============================================================================
# FastAPI 中间件
# ============================================================================

class MonitoringMiddleware:
    """监控中间件 - 用于 FastAPI"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "unknown")

        # 记录请求开始
        record_request_start()

        # 包装 send 以捕获响应状态码
        status_code = 200

        async def wrapped_send(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
            await send(message)

        try:
            await self.app(scope, receive, wrapped_send)
        except Exception as e:
            record_error(type(e).__name__, path)
            raise
        finally:
            record_request_end(method, path, status_code)


# ============================================================================
# 启动时检查
# ============================================================================

def check_monitoring_dependencies() -> dict[str, bool]:
    """检查监控依赖是否安装"""
    return {
        "prometheus_client": PROMETHEUS_AVAILABLE,
        "psutil": psutil is not None
    }


async def _main_test():
    """测试监控功能"""
    print("=" * 60)
    print("SiliconBase 监控模块测试")
    print("=" * 60)

    # 检查依赖
    deps = check_monitoring_dependencies()
    print("\n依赖检查:")
    for dep, available in deps.items():
        status = "✅ 可用" if available else "❌ 不可用"
        print(f"  {dep}: {status}")

    # 测试健康检查
    print("\n执行健康检查...")
    health = await perform_health_checks()
    print(f"整体状态: {health['status']}")
    print(f"响应时间: {health['response_time_ms']}ms")
    print("\n详细检查:")
    for check_name, check_result in health['checks'].items():
        print(f"\n  {check_name}:")
        if isinstance(check_result, dict):
            for k, v in check_result.items():
                print(f"    {k}: {v}")
        else:
            print(f"    {check_result}")

    # 测试 Prometheus 指标
    print("\n\nPrometheus 指标:")
    content_type, metrics = get_prometheus_metrics()
    print(f"Content-Type: {content_type}")
    print("指标预览 (前10行):")
    for line in metrics.decode().split('\n')[:10]:
        print(f"  {line}")


if __name__ == "__main__":
    asyncio.run(_main_test())
