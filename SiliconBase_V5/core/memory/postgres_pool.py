#!/usr/bin/env python3
"""
异步 PostgreSQL 连接池 - 从 async_memory.py 迁移的核心基础设施
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
原位于 core.memory.async_memory，因 async_memory 整体废弃，仅提取 AsyncPostgresPool。
"""
import asyncio
import contextlib
import os
import time

import asyncpg

from core.logger import logger

# 连接池重试冷却期（秒）
POOL_RETRY_COOLDOWN = 60


class AsyncPostgresPool:
    """异步 PostgreSQL 连接池 - 与同步版 PostgresConnectionPool 完全隔离

    修复说明：原单例模式在跨事件循环场景下会关闭旧池，导致正在使用的连接被强制中断。
    现改为按事件循环隔离的实例字典，每个事件循环拥有独立连接池，互不干扰。
    """
    _instances_by_loop: dict[int, asyncpg.Pool] = {}
    _pool_failed_at: float | None = None
    _pool_lock: asyncio.Lock | None = None

    @classmethod
    def _get_loop_id(cls) -> int | None:
        try:
            return id(asyncio.get_running_loop())
        except RuntimeError:
            return None

    @classmethod
    def _is_pool_stale(cls, pool: asyncpg.Pool | None) -> bool:
        """检测单个连接池是否已不可用"""
        if pool is None:
            return True
        try:
            if getattr(pool, '_closing', False):
                return True
            pool_loop = pool._loop  # type: ignore
            current_loop = asyncio.get_running_loop()
            if pool_loop is not current_loop:
                return True
        except (AttributeError, RuntimeError):
            return True
        return False

    @classmethod
    async def get_pool(cls) -> asyncpg.Pool:
        loop_id = cls._get_loop_id()
        if loop_id is None:
            raise RuntimeError("[AsyncPostgresPool] 必须在运行的事件循环中调用 get_pool()")

        existing = cls._instances_by_loop.get(loop_id)
        if not cls._is_pool_stale(existing):
            return existing  # type: ignore

        # 只清理当前 loop 的失效池，不影响其他 loop 的池
        if existing is not None:
            with contextlib.suppress(Exception):
                await existing.close()
            cls._instances_by_loop.pop(loop_id, None)

        if cls._pool_failed_at is not None:
            elapsed = time.time() - cls._pool_failed_at
            if elapsed < POOL_RETRY_COOLDOWN:
                raise ConnectionError(
                    f"[AsyncPostgresPool] PostgreSQL连接池处于冷却期，"
                    f"{POOL_RETRY_COOLDOWN - int(elapsed)}秒后自动重试"
                )
            cls._pool_failed_at = None

        if cls._pool_lock is None or cls._is_pool_stale_lock():
            cls._pool_lock = asyncio.Lock()

        lock = cls._pool_lock
        async with lock:
            # 双重检查
            existing = cls._instances_by_loop.get(loop_id)
            if not cls._is_pool_stale(existing):
                return existing  # type: ignore

            password = ""
            try:
                from pathlib import Path

                from dotenv import dotenv_values
                env_path = Path(__file__).parent.parent.parent / '.env'
                if env_path.exists():
                    env = dotenv_values(env_path)
                    password = env.get('POSTGRES_PASSWORD', '')
            except Exception:
                pass
            if not password:
                password = os.getenv("POSTGRES_PASSWORD", "")

            host = os.getenv("POSTGRES_HOST", "localhost")
            port = int(os.getenv("POSTGRES_PORT", "5432"))
            database = os.getenv("POSTGRES_DB", "siliconbase")
            user = os.getenv("POSTGRES_USER", "postgres")

            last_error = None
            for attempt in range(3):
                try:
                    pool = await asyncpg.create_pool(
                        host=host,
                        port=port,
                        database=database,
                        user=user,
                        password=password,
                        min_size=1,
                        max_size=10,
                        command_timeout=60,
                        ssl=False,
                    )
                    async with pool.acquire() as conn:
                        await conn.fetch("SELECT 1")
                    cls._pool_failed_at = None
                    cls._instances_by_loop[loop_id] = pool
                    logger.info("[AsyncPostgresPool] asyncpg 连接池已初始化且连接验证通过")
                    return pool
                except Exception as e:
                    last_error = e
                    if attempt < 2:
                        backoff = 2 ** (attempt + 1)
                        logger.warning(f"[AsyncPostgresPool] 连接池初始化失败（第{attempt + 1}次），{backoff}秒后重试: {e}")
                        await asyncio.sleep(backoff)
                    else:
                        logger.error(f"[AsyncPostgresPool] 连接池初始化失败（第{attempt + 1}次），所有重试已耗尽: {e}")

            cls._pool_failed_at = time.time()
            raise ConnectionError(f"[AsyncPostgresPool] PostgreSQL连接池初始化失败（已重试3次）: {last_error}") from last_error

    @classmethod
    def _is_pool_stale_lock(cls) -> bool:
        """检查锁是否绑定到当前事件循环"""
        if cls._pool_lock is None:
            return True
        try:
            return cls._pool_lock._loop is not asyncio.get_running_loop()  # type: ignore
        except (AttributeError, RuntimeError):
            return True
