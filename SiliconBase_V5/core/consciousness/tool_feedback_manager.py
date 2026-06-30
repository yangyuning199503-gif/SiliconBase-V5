#!/usr/bin/env python3
"""
工具反馈管理器 V1.0
管理工具反馈过滤器的生命周期和全局访问

核心职责：
1. 管理 ToolFeedbackFilter 实例（按用户隔离）
2. 提供便捷访问接口（单例模式）
3. 统计和监控反馈过滤情况
4. 集成L5执行记忆系统

设计理念：
参考 subconscious_engine.py 的 WeakConnectionManager 实现，
支持按用户隔离状态，提供统一的管理接口。

作者: SiliconBase Team
版本: 1.0.0
"""

# ========================================
# 标准库导入
# ========================================
import threading  # 多线程支持，用于锁机制
from typing import Any  # 类型提示

# ========================================
# 本地导入
# ========================================
from core.consciousness.tool_feedback_filter import (
    FeedbackDecision,
    FeedbackLevel,
    ToolFeedbackConfig,
    ToolFeedbackFilter,
)

# ========================================
# 延迟导入变量 - 避免循环依赖
# ========================================
_logger = None  # 日志对象缓存


def _get_logger():
    """延迟获取logger实例 - 解决循环依赖问题"""
    global _logger
    if _logger is None:
        try:
            from core.logger import logger
            _logger = logger
        except ImportError:
            import logging
            _logger = logging.getLogger('tool_feedback_manager')
    return _logger


# ========================================
# 工具反馈管理器 - 单例模式
# ========================================
class ToolFeedbackManager:
    """
    工具反馈管理器 - 单例模式

    职责：
    1. 管理 ToolFeedbackFilter 实例（按用户隔离）
    2. 提供便捷访问接口
    3. 统计和监控

    使用方式：
        # 获取全局实例
        from core.consciousness.tool_feedback_manager import tool_feedback_manager

        # 处理工具结果
        should_add, content = tool_feedback_manager.process_tool_result(
            tool_id="file_list",
            result={"success": True, "user_message": "找到3个文件"},
            user_id="user_123"
        )

    线程安全：
        所有方法都使用 RLock 保护，确保多线程安全。
    """

    # 单例实例
    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        """单例模式实现"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化管理器"""
        if self._initialized:
            return

        self._initialized = True

        # 用户过滤器缓存：user_id -> ToolFeedbackFilter
        self._filters: dict[str, ToolFeedbackFilter] = {}

        # 线程锁
        self._lock = threading.RLock()

        # 全局统计
        self._stats = {
            'total_filtered': 0,
            'silent_count': 0,
            'observable_count': 0,
            'interactive_count': 0,
        }

        # 用户统计：user_id -> stats_dict
        self._user_stats: dict[str, dict[str, int]] = {}

        # 全局配置（可被覆盖）
        self._config = ToolFeedbackConfig()

        # 是否启用过滤（紧急关闭开关）
        self._enabled = True

        _get_logger().info("[ToolFeedbackManager] 初始化完成")

    def get_filter(self, user_id: str = "default") -> ToolFeedbackFilter:
        """
        获取用户的反馈过滤器

        如果不存在则自动创建。

        Args:
            user_id: 用户ID

        Returns:
            ToolFeedbackFilter: 过滤器实例
        """
        with self._lock:
            if user_id not in self._filters:
                self._filters[user_id] = ToolFeedbackFilter(self._config)
                self._user_stats[user_id] = {
                    'total_filtered': 0,
                    'silent_count': 0,
                    'observable_count': 0,
                    'interactive_count': 0,
                }
                _get_logger().info(
                    f"[ToolFeedbackManager] 为用户 {user_id} 创建过滤器"
                )
            return self._filters[user_id]

    async def process_tool_result(
        self,
        tool_id: str,
        result: dict[str, Any],
        user_id: str = "default",
        working_memory: Any | None = None
    ) -> tuple[bool, str | None]:
        """
        处理工具结果的主入口

        这是过滤系统的核心方法，决定工具反馈是否应进入AI上下文。

        Args:
            tool_id: 工具ID
            result: 工具执行结果
            user_id: 用户ID
            working_memory: 工作记忆对象（可选）

        Returns:
            Tuple[bool, Optional[str]]:
                - should_add_to_context: 是否应添加到AI上下文
                - formatted_content: 格式化后的内容（如果应该添加）
        """
        # 如果禁用，直接返回完整反馈
        if not self._enabled:
            return True, self._format_fallback(tool_id, result)

        try:
            # 获取过滤器并执行过滤
            filter_instance = self.get_filter(user_id)
            decision = filter_instance.filter_feedback(tool_id, result, user_id)

            # 更新统计
            self._update_stats(decision.level, user_id)

            # 记录到L5记忆（如果配置为需要）
            if decision.should_record_to_memory:
                self._record_to_execution_memory(tool_id, result, user_id, decision)

            # 根据级别返回
            if decision.level == FeedbackLevel.SILENT:
                _get_logger().debug(
                    f"[ToolFeedbackManager] Silent: {tool_id}, 原因: {decision.reason}"
                )
                return False, None

            elif decision.level == FeedbackLevel.OBSERVABLE:
                _get_logger().info(
                    f"[ToolFeedbackManager] Observable: {tool_id}, "
                    f"摘要: {decision.content[:50] if decision.content else 'N/A'}"
                )
                return True, decision.content

            else:  # INTERACTIVE
                _get_logger().info(
                    f"[ToolFeedbackManager] Interactive: {tool_id}, 完整反馈"
                )
                return True, decision.content

        except Exception as e:
            # 过滤失败不应影响工具执行，记录日志并回退
            _get_logger().error(
                f"[SILENT_FAILURE_BLOCKED][ToolFeedbackManager] "
                f"过滤失败: {e}, tool_id={tool_id}",
                exc_info=True
            )
            return True, self._format_fallback(tool_id, result)

    def _format_fallback(self, tool_id: str, result: dict[str, Any]) -> str:
        """
        回退格式化方法

        当过滤失败时使用，提供基本的格式化功能。

        Args:
            tool_id: 工具ID
            result: 工具执行结果

        Returns:
            str: 格式化后的反馈
        """
        success = result.get("success", False)
        message = result.get("user_message", "")
        status = "成功" if success else "失败"
        return f"[工具执行] {tool_id}: {status} - {message}"

    def _record_to_execution_memory(
        self,
        tool_id: str,
        result: dict[str, Any],
        user_id: str,
        decision: FeedbackDecision
    ):
        """
        记录到L5执行记忆

        复用现有的 execution_memory_manager 机制。

        Args:
            tool_id: 工具ID
            result: 工具执行结果
            user_id: 用户ID
            decision: 反馈决策
        """
        try:
            # 延迟导入避免循环依赖
            from core.memory.execution_memory import execution_memory_manager

            execution_memory_manager.add_record(
                user_id=user_id,
                action_type="tool_execution",
                action_details={
                    "tool_id": tool_id,
                    "result_summary": result.get("user_message", "")[:100],
                    "success": result.get("success", False),
                    "feedback_level": decision.level.value,
                    "feedback_reason": decision.reason,
                }
            )
            _get_logger().debug(
                f"[ToolFeedbackManager] 已记录到L5记忆: {tool_id}"
            )
        except ImportError:
            # L5记忆不可用，静默忽略
            _get_logger().debug(
                f"[ToolFeedbackManager] L5记忆不可用，跳过记录: {tool_id}"
            )
        except Exception as e:
            # 记录失败不应影响主流程
            _get_logger().warning(
                f"[ToolFeedbackManager] 记录到L5记忆失败: {e}"
            )

    def _update_stats(self, level: FeedbackLevel, user_id: str):
        """
        更新统计

        Args:
            level: 反馈级别
            user_id: 用户ID
        """
        with self._lock:
            # 更新全局统计
            self._stats['total_filtered'] += 1
            if level == FeedbackLevel.SILENT:
                self._stats['silent_count'] += 1
            elif level == FeedbackLevel.OBSERVABLE:
                self._stats['observable_count'] += 1
            else:
                self._stats['interactive_count'] += 1

            # 更新用户统计
            if user_id in self._user_stats:
                self._user_stats[user_id]['total_filtered'] += 1
                if level == FeedbackLevel.SILENT:
                    self._user_stats[user_id]['silent_count'] += 1
                elif level == FeedbackLevel.OBSERVABLE:
                    self._user_stats[user_id]['observable_count'] += 1
                else:
                    self._user_stats[user_id]['interactive_count'] += 1

    def get_stats(self, user_id: str | None = None) -> dict[str, Any]:
        """
        获取过滤统计

        Args:
            user_id: 用户ID，None则返回全局统计

        Returns:
            Dict: 统计信息
        """
        with self._lock:
            if user_id is None:
                return {
                    'global': self._stats.copy(),
                    'users': {
                        uid: stats.copy()
                        for uid, stats in self._user_stats.items()
                    },
                    'user_count': len(self._filters),
                }
            else:
                return {
                    'user_id': user_id,
                    'stats': self._user_stats.get(user_id, {
                        'total_filtered': 0,
                        'silent_count': 0,
                        'observable_count': 0,
                        'interactive_count': 0,
                    }).copy(),
                }

    def reset_stats(self, user_id: str | None = None):
        """
        重置统计

        Args:
            user_id: 用户ID，None则重置所有
        """
        with self._lock:
            if user_id is None:
                self._stats = {
                    'total_filtered': 0,
                    'silent_count': 0,
                    'observable_count': 0,
                    'interactive_count': 0,
                }
                self._user_stats.clear()
                _get_logger().info("[ToolFeedbackManager] 重置所有统计")
            else:
                if user_id in self._user_stats:
                    self._user_stats[user_id] = {
                        'total_filtered': 0,
                        'silent_count': 0,
                        'observable_count': 0,
                        'interactive_count': 0,
                    }
                _get_logger().info(
                    f"[ToolFeedbackManager] 重置用户 {user_id} 统计"
                )

    def clear_user_filter(self, user_id: str):
        """
        清除用户的过滤器（用户会话结束时调用）

        Args:
            user_id: 用户ID
        """
        with self._lock:
            if user_id in self._filters:
                del self._filters[user_id]
                _get_logger().info(
                    f"[ToolFeedbackManager] 清除用户 {user_id} 过滤器"
                )

    def set_enabled(self, enabled: bool):
        """
        启用/禁用过滤系统

        用于紧急关闭或调试。

        Args:
            enabled: 是否启用
        """
        self._enabled = enabled
        _get_logger().warning(
            f"[ToolFeedbackManager] 过滤系统已{'启用' if enabled else '禁用'}"
        )

    def is_enabled(self) -> bool:
        """检查过滤系统是否启用"""
        return self._enabled


# ========================================
# 全局实例
# ========================================
tool_feedback_manager = ToolFeedbackManager()


# ========================================
# 便捷函数
# ========================================
def get_manager() -> ToolFeedbackManager:
    """获取全局管理器实例"""
    return tool_feedback_manager


async def process_tool_result(
    tool_id: str,
    result: dict[str, Any],
    user_id: str = "default",
    working_memory: Any | None = None
) -> tuple[bool, str | None]:
    """
    便捷函数：处理工具结果

    等价于 tool_feedback_manager.process_tool_result()

    Args:
        tool_id: 工具ID
        result: 工具执行结果
        user_id: 用户ID
        working_memory: 工作记忆对象

    Returns:
        Tuple[bool, Optional[str]]: (是否添加到上下文, 格式化内容)
    """
    return await tool_feedback_manager.process_tool_result(
        tool_id, result, user_id, working_memory
    )


def get_stats(user_id: str | None = None) -> dict[str, Any]:
    """
    便捷函数：获取统计

    Args:
        user_id: 用户ID

    Returns:
        Dict: 统计信息
    """
    return tool_feedback_manager.get_stats(user_id)


# ========================================
# 模块导出
# ========================================
__all__ = [
    'ToolFeedbackManager',
    'tool_feedback_manager',
    'get_manager',
    'process_tool_result',
    'get_stats',
]
