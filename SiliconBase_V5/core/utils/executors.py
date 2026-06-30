#!/usr/bin/env python3
"""
全局 Executor 管理器 - 统一线程池管理
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
解决项目内 13+ 个 ThreadPoolExecutor 各自为政、线程总数不可控的问题。

设计原则：
- 按用途分类管理，不按模块隔离
- CPU/GPU-bound 池严格限制 worker 数
- I/O-bound 池可设较高 worker 数
- lifespan shutdown 统一释放，atexit 兜底
"""

import atexit
import contextlib
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# ═════════════════════════════════════════════════════════════════════════════
# 分类线程池定义
# ═════════════════════════════════════════════════════════════════════════════

class ExecutorManager:
    """全局 Executor 管理器 - 按用途分类"""

    # I/O 密集型通用池（DB、文件、HTTP 桥接）
    IO_POOL: ThreadPoolExecutor | None = None
    IO_MAX_WORKERS = 16

    # Agent Loop 后台任务池（高并发 Hook 回调、后台进化等）
    AGENT_POOL: ThreadPoolExecutor | None = None
    AGENT_MAX_WORKERS = 10

    # 视觉/GPU 严格受限池（截图、OCR、视觉模型）
    VISION_POOL: ThreadPoolExecutor | None = None
    VISION_MAX_WORKERS = 2

    # 工具执行隔离池（沙箱、高危操作）
    TOOL_POOL: ThreadPoolExecutor | None = None
    TOOL_MAX_WORKERS = 8

    # LLM 桥接池（替代各 provider 独立池 + ai_adapter 池）
    LLM_POOL: ThreadPoolExecutor | None = None
    LLM_MAX_WORKERS = 4

    _initialized = False
    _lock = False  # 简单初始化锁

    @classmethod
    def _init(cls):
        """延迟初始化所有线程池"""
        if cls._initialized or cls._lock:
            return
        cls._lock = True

        cls.IO_POOL = ThreadPoolExecutor(
            max_workers=cls.IO_MAX_WORKERS,
            thread_name_prefix="sb_io_"
        )
        cls.AGENT_POOL = ThreadPoolExecutor(
            max_workers=cls.AGENT_MAX_WORKERS,
            thread_name_prefix="sb_agent_"
        )
        cls.VISION_POOL = ThreadPoolExecutor(
            max_workers=cls.VISION_MAX_WORKERS,
            thread_name_prefix="sb_vision_"
        )
        cls.TOOL_POOL = ThreadPoolExecutor(
            max_workers=cls.TOOL_MAX_WORKERS,
            thread_name_prefix="sb_tool_"
        )
        cls.LLM_POOL = ThreadPoolExecutor(
            max_workers=cls.LLM_MAX_WORKERS,
            thread_name_prefix="sb_llm_"
        )

        cls._initialized = True
        logger.info("[ExecutorManager] 全局线程池初始化完成: IO=%d, AGENT=%d, VISION=%d, TOOL=%d, LLM=%d",
                     cls.IO_MAX_WORKERS, cls.AGENT_MAX_WORKERS, cls.VISION_MAX_WORKERS,
                     cls.TOOL_MAX_WORKERS, cls.LLM_MAX_WORKERS)

    @classmethod
    def get_executor(cls, name: str) -> ThreadPoolExecutor:
        """按名称获取线程池

        Args:
            name: 池名称 - io / agent / vision / tool / llm

        Returns:
            ThreadPoolExecutor 实例
        """
        if not cls._initialized:
            cls._init()

        pool_map = {
            "io": cls.IO_POOL,
            "agent": cls.AGENT_POOL,
            "vision": cls.VISION_POOL,
            "tool": cls.TOOL_POOL,
            "llm": cls.LLM_POOL,
        }
        pool = pool_map.get(name)
        if pool is None:
            raise ValueError(f"未知的线程池名称: {name}，可选: {list(pool_map.keys())}")
        return pool

    @classmethod
    def shutdown_all(cls, wait: bool = True, cancel_futures: bool = False):
        """关闭所有线程池

        Args:
            wait: 是否等待正在执行的任务完成
            cancel_futures: 是否取消待执行的任务（Python 3.9+）
        """
        for name, pool in [
            ("io", cls.IO_POOL),
            ("agent", cls.AGENT_POOL),
            ("vision", cls.VISION_POOL),
            ("tool", cls.TOOL_POOL),
            ("llm", cls.LLM_POOL),
        ]:
            if pool is not None:
                try:
                    kwargs = {"wait": wait}
                    # Python 3.9+ 支持 cancel_futures
                    kwargs["cancel_futures"] = cancel_futures
                    pool.shutdown(**kwargs)
                    logger.info("[ExecutorManager] %s 线程池已关闭", name)
                except Exception as e:
                    logger.error("[ExecutorManager] 关闭 %s 线程池失败: %s", name, e)
        cls._initialized = False
        cls._lock = False

    @classmethod
    def get_stats(cls) -> dict[str, int]:
        """获取各池活跃线程数估算"""
        if not cls._initialized:
            cls._init()
        stats = {}
        for name, pool in [
            ("io", cls.IO_POOL),
            ("agent", cls.AGENT_POOL),
            ("vision", cls.VISION_POOL),
            ("tool", cls.TOOL_POOL),
            ("llm", cls.LLM_POOL),
        ]:
            if pool is not None:
                stats[name] = len(pool._threads)  # 内部估算
            else:
                stats[name] = 0
        return stats


# ═════════════════════════════════════════════════════════════════════════════
# 便捷函数
# ═════════════════════════════════════════════════════════════════════════════

def get_executor(name: str) -> ThreadPoolExecutor:
    """获取指定名称的全局线程池"""
    return ExecutorManager.get_executor(name)


def get_global_executor(name: str = "llm", max_workers: int = None) -> ThreadPoolExecutor:
    """向后兼容的便捷函数（原 ai_adapter.py 等模块使用）

    新代码建议直接使用 get_executor("llm") 等明确名称。

    Args:
        name: 池名称或旧模块别名
        max_workers: 已废弃，各池大小由 ExecutorManager 分类常量决定
    """
    if max_workers is not None:
        logger.debug("[ExecutorManager] get_global_executor 的 max_workers 参数已废弃，"
                     "使用分类池固定大小")
    # 将通用调用映射到合适的池
    name_map = {
        "ai_adapter": "llm",
        "agent_loop": "agent",
        "vision": "vision",
        "tool": "tool",
        "default": "io",
    }
    mapped = name_map.get(name, name)
    return ExecutorManager.get_executor(mapped)


def shutdown_all_executors(wait: bool = True, cancel_futures: bool = False):
    """关闭所有全局线程池（供 lifespan shutdown 调用）"""
    ExecutorManager.shutdown_all(wait=wait, cancel_futures=cancel_futures)


# ═════════════════════════════════════════════════════════════════════════════
# 启动时注册 atexit 兜底
# ═════════════════════════════════════════════════════════════════════════════

def _atexit_cleanup():
    """进程退出时自动关闭所有线程池"""
    with contextlib.suppress(Exception):
        ExecutorManager.shutdown_all(wait=False, cancel_futures=True)
        # atexit 阶段避免打印异常到 stdout

atexit.register(_atexit_cleanup)
