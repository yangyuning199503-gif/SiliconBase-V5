"""
SiliconBase Cloud API 中间件

包含限流、日志、认证等中间件
"""

import asyncio
import logging
import time
from collections.abc import Callable
from functools import wraps

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# 设置日志（禁用basicConfig，避免在Windows上stdout句柄关闭时引发I/O错误）
# logging.basicConfig(level=logging.INFO)  # 【修复】已移除，由core.logger统一配置
logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """限流中间件"""

    def __init__(self, app, max_requests: int = 60, window: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window = window
        self.requests: dict = {}
        self._lock = asyncio.Lock()  # 添加锁保护线程安全

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 获取客户端IP
        client_ip = request.client.host if request.client else "unknown"
        current_time = time.time()

        async with self._lock:
            # 清理过期请求记录
            if client_ip in self.requests:
                self.requests[client_ip] = [
                    t for t in self.requests[client_ip]
                    if current_time - t < self.window
                ]
            else:
                self.requests[client_ip] = []

            # 检查限流
            if len(self.requests.get(client_ip, [])) >= self.max_requests:
                logger.error(f"[RateLimit] IP {client_ip} 触发限流，请求数: {len(self.requests[client_ip])}")
                return Response(
                    content='{"error": "Rate limit exceeded"}',
                    status_code=429,
                    media_type="application/json"
                )

            # 记录请求
            self.requests[client_ip].append(current_time)

            # 内存保护：清理长期不活跃的IP
            self._cleanup_inactive_ips(current_time)

        return await call_next(request)

    def _cleanup_inactive_ips(self, current_time: float):
        """清理超过1小时不活跃的IP，防止内存无限增长"""
        inactive_threshold = 3600  # 1小时
        inactive_ips = [
            ip for ip, timestamps in self.requests.items()
            if timestamps and current_time - max(timestamps) > inactive_threshold
        ]
        for ip in inactive_ips:
            del self.requests[ip]
            logger.debug(f"[RateLimit] 清理不活跃IP: {ip}")


class LoggingMiddleware(BaseHTTPMiddleware):
    """日志中间件"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()

        # 记录请求
        logger.info(f"[{request.method}] {request.url.path} - Client: {request.client.host if request.client else 'unknown'}")

        response = await call_next(request)

        # 记录响应
        duration = time.time() - start_time
        logger.info(f"[{request.method}] {request.url.path} - Status: {response.status_code} - Duration: {duration:.3f}s")

        return response


def cache_response(seconds: int):
    """响应缓存装饰器（用于特定端点）"""
    def decorator(func: Callable):
        cache = {}

        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 生成缓存键
            cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
            current_time = time.time()

            # 检查缓存
            if cache_key in cache:
                result, timestamp = cache[cache_key]
                if current_time - timestamp < seconds:
                    return result

            # 执行函数
            result = await func(*args, **kwargs)
            cache[cache_key] = (result, current_time)

            return result

        return wrapper
    return decorator
