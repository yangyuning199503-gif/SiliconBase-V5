#!/usr/bin/env python3
"""
工具反馈过滤器 V1.0
基于意识系统的三层反馈过滤机制

核心功能：
- Silent (静默层): 仅记录到L5执行记忆，不进入AI上下文
- Observable (可观测层): 简短摘要进入AI上下文
- Interactive (交互层): 完整反馈给AI处理

设计理念：
参考 life_presence.py 的 SmartAnnouncer 实现，通过工具类型分类、错误码升级、
冷却机制等策略，智能决定工具反馈如何呈现给AI，避免信息过载。

作者: SiliconBase Team
版本: 1.0.0
"""

# ========================================
# 标准库导入
# ========================================
import time  # 时间相关功能
from collections import deque  # 双端队列
from dataclasses import dataclass  # 数据类
from enum import Enum  # 枚举类型
from typing import Any  # 类型提示

# ========================================
# 核心接口导入
# ========================================

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
            _logger = logging.getLogger('tool_feedback_filter')
    return _logger


# ========================================
# 反馈级别枚举
# ========================================
class FeedbackLevel(Enum):
    """
    反馈级别枚举

    决定工具执行结果如何呈现给AI：
    - SILENT: 仅记录到记忆系统，不进入AI上下文（后台任务）
    - OBSERVABLE: 简短摘要进入AI上下文（值得关注的任务）
    - INTERACTIVE: 完整反馈，AI需要处理决策（关键任务）
    """
    SILENT = "silent"           # 静默层 - 仅记录到L5执行记忆
    OBSERVABLE = "observable"   # 可观测层 - 简短摘要
    INTERACTIVE = "interactive" # 交互层 - 完整反馈


# ========================================
# 反馈决策数据类
# ========================================
@dataclass
class FeedbackDecision:
    """
    反馈决策结果

    Attributes:
        level: 反馈级别
        content: 格式化后的内容（SILENT级别时为None）
        reason: 决策原因（用于调试和日志）
        should_record_to_memory: 是否记录到L5执行记忆
    """
    level: FeedbackLevel
    content: str | None
    reason: str
    should_record_to_memory: bool = True


# ========================================
# 工具反馈配置
# ========================================
class ToolFeedbackConfig:
    """
    工具反馈配置 - 基于工具类型决定反馈级别

    参考 life_presence.py 的 IMPORTANT_TOOLS 模式，
    将工具按功能分为不同类别，决定其反馈级别。
    """

    # Silent 工具：后台自动任务，无需AI关注
    # 这些工具通常由系统自动调用，AI不需要知道细节
    SILENT_TOOLS = [
        # 检查点和记忆相关（系统自动管理）
        "checkpoint_save", "checkpoint_auto_save",
        "memory_add_internal", "memory_add_background",
        "context_update", "context_refresh",
        # 系统监控和心跳
        "heartbeat", "status_ping",
        "metric_record", "metric_report",
        # 缓存和清理
        "cache_refresh", "cache_cleanup",
        "file_cleanup", "temp_cleanup",
        # 审计日志（自动记录）
        "audit_log_internal", "audit_auto",
    ]

    # Observable 工具：值得关注但只需简短摘要
    # 这些工具提供信息但不需要AI深度处理
    OBSERVABLE_TOOLS = [
        # 文件查询类
        "file_list", "file_search", "file_stat",
        # 系统信息查询
        "system_info", "process_list", "process_stat",
        # 剪贴板和屏幕
        "clipboard_read", "clipboard_get",
        "screen_capture", "screen_stat",
        # 搜索类
        "web_search", "memory_search", "semantic_search",
        # 窗口查询
        "window_get", "window_list", "window_stat",
        # 感知类（成功时降级）
        "pixel_capture", "pixel_color", "pixel_stat",
        "template_match", "find_screen_element",
    ]

    # 错误码升级规则：特定错误码强制升级到 INTERACTIVE
    # 即使原本是 Silent/Observable 工具，遇到这些错误也需要AI处理
    ERROR_CODE_UPGRADE = [
        # 权限相关（需要AI决策如何提示用户）
        "PERMISSION_DENIED", "PERM_ADMIN_DENIED", "PERM_UAC_FAILED",
        # 工具相关（需要AI选择替代方案）
        "TOOL_NOT_FOUND", "TOOL_EXECUTION_ERROR", "INVALID_PARAMS",
        # 用户介入（必须通知AI）
        "USER_INTERVENTION_NEEDED",
        # 认证和资源
        "AUTH_FAILED", "RESOURCE_NOT_FOUND",
        # 文件操作严重错误
        "FILE_NOT_FOUND", "PATH_NOT_FOUND", "WRITE_ERROR", "DELETE_ERROR",
        # 超时（可能需要重试策略）
        "TOOL_TIMEOUT", "AI_TIMEOUT",
    ]

    # 成功降级规则：特定工具即使成功也只给简短反馈
    # 这些工具成功时不需要详细反馈
    SUCCESS_DOWNGRADE = [
        # 感知类工具（成功就是成功，不需要细节）
        "pixel_capture", "pixel_color", "pixel_stat",
        "screen_capture", "screen_ocr", "window_ocr",
        "template_match", "find_screen_element",
        # 窗口操作成功
        "window_get", "window_list", "window_stat",
        # 剪贴板读取
        "clipboard_read", "clipboard_get",
    ]

    # 冷却时间配置（秒）
    COOLDOWN_SECONDS = 30

    # 重复检测历史长度
    HISTORY_SIZE = 50


# ========================================
# 工具反馈过滤器 - 核心类
# ========================================
class ToolFeedbackFilter:
    """
    工具反馈过滤器

    职责：根据工具类型、执行结果、用户状态决定反馈级别
    模式：参考 SmartAnnouncer 的实现风格

    决策优先级（从高到低）：
    1. 错误码检查 - 重要错误强制升级到 INTERACTIVE
    2. 工具类型映射 - SILENT/OBSERVABLE/INTERACTIVE 分类
    3. 冷却时间检查 - 避免同类工具重复反馈
    4. 成功状态检查 - 特定工具成功时降级

    示例：
        filter = ToolFeedbackFilter()
        decision = filter.filter_feedback("file_list", result, user_id="user_123")
        # decision.level 可能是 FeedbackLevel.OBSERVABLE
    """

    def __init__(self, config: ToolFeedbackConfig | None = None):
        """
        初始化反馈过滤器

        Args:
            config: 配置对象，使用默认配置 if None
        """
        self._config = config or ToolFeedbackConfig()

        # 冷却时间追踪：tool_id -> last_feedback_time
        self._last_feedback_time: dict[str, float] = {}

        # 去重历史：记录最近的反馈内容
        self._feedback_history: deque = deque(maxlen=self._config.HISTORY_SIZE)

        _get_logger().debug("[ToolFeedbackFilter] 初始化完成")

    def filter_feedback(
        self,
        tool_id: str,
        result: dict[str, Any],
        user_id: str = "default",
        execution_context: dict[str, Any] | None = None
    ) -> FeedbackDecision:
        """
        主过滤方法 - 决定工具反馈的呈现方式

        决策流程：
        1. 检查错误码 - 重要错误强制升级
        2. 检查工具类型 - 分类映射
        3. 检查冷却时间 - 避免重复反馈
        4. 检查成功降级规则

        Args:
            tool_id: 工具ID
            result: 工具执行结果（包含 success, error_code, user_message, data 等）
            user_id: 用户ID（用于用户隔离）
            execution_context: 执行上下文（可选，用于更精细的决策）

        Returns:
            FeedbackDecision: 反馈决策结果
        """
        # 参数校验
        if not isinstance(result, dict):
            _get_logger().warning(f"[ToolFeedbackFilter] 无效的结果类型: {type(result)}")
            return FeedbackDecision(
                level=FeedbackLevel.INTERACTIVE,
                content=str(result)[:200],
                reason="结果格式异常，降级到INTERACTIVE处理"
            )

        success = result.get("success", False)
        error_code = result.get("error_code")

        # 1. 错误码检查（最高优先级）
        if error_code and error_code in self._config.ERROR_CODE_UPGRADE:
            return FeedbackDecision(
                level=FeedbackLevel.INTERACTIVE,
                content=self._format_full_feedback(tool_id, result),
                reason=f"关键错误码: {error_code}"
            )

        # 2. 工具类型映射
        if tool_id in self._config.SILENT_TOOLS:
            # Silent 级别：不进入AI上下文，只记录记忆
            return FeedbackDecision(
                level=FeedbackLevel.SILENT,
                content=None,
                reason=f"工具 {tool_id} 属于静默类型",
                should_record_to_memory=True
            )

        if tool_id in self._config.OBSERVABLE_TOOLS:
            # 检查冷却时间
            if self._is_in_cooldown(tool_id):
                return FeedbackDecision(
                    level=FeedbackLevel.SILENT,
                    content=None,
                    reason=f"工具 {tool_id} 冷却期内，跳过重复反馈"
                )

            # 检查成功降级
            if success and tool_id in self._config.SUCCESS_DOWNGRADE:
                # 成功时降级为 SILENT
                return FeedbackDecision(
                    level=FeedbackLevel.SILENT,
                    content=None,
                    reason=f"工具 {tool_id} 成功执行，降级为静默",
                    should_record_to_memory=True
                )

            # 记录反馈时间（用于冷却计算）
            self._record_feedback_time(tool_id)

            return FeedbackDecision(
                level=FeedbackLevel.OBSERVABLE,
                content=self._format_summary(tool_id, result),
                reason=f"工具 {tool_id} 属于可观测类型"
            )

        # 3. 默认 Interactive
        return FeedbackDecision(
            level=FeedbackLevel.INTERACTIVE,
            content=self._format_full_feedback(tool_id, result),
            reason=f"工具 {tool_id} 默认完整反馈"
        )

    def _is_in_cooldown(self, tool_id: str) -> bool:
        """
        检查工具是否处于冷却期

        参考 life_presence.py 的冷却机制，
        避免同类工具在短时间内重复反馈。

        Args:
            tool_id: 工具ID

        Returns:
            bool: True表示处于冷却期
        """
        last_time = self._last_feedback_time.get(tool_id)
        if last_time is None:
            return False

        elapsed = time.time() - last_time
        return elapsed < self._config.COOLDOWN_SECONDS

    def _record_feedback_time(self, tool_id: str):
        """记录工具反馈时间"""
        self._last_feedback_time[tool_id] = time.time()

    def _format_summary(self, tool_id: str, result: dict[str, Any]) -> str:
        """
        生成一句话摘要（Observable 级别）

        简洁明了，适合AI快速扫描。

        Args:
            tool_id: 工具ID
            result: 工具执行结果

        Returns:
            str: 简短摘要
        """
        success = result.get("success", False)
        message = result.get("user_message", "")
        status_icon = "✓" if success else "✗"

        # 截断过长的消息
        if message and len(message) > 50:
            message = message[:47] + "..."

        return f"[{status_icon}] {tool_id}: {message}"

    def _format_full_feedback(self, tool_id: str, result: dict[str, Any]) -> str:
        """
        生成完整反馈（Interactive 级别）

        参考 ToolManager.format_feedback_for_ai 的逻辑，
        提供详细信息供AI决策。

        Args:
            tool_id: 工具ID
            result: 工具执行结果

        Returns:
            str: 完整反馈文本
        """
        success = result.get("success", False)
        data = result.get("data", {})
        message = result.get("user_message", "")
        error_code = result.get("error_code")

        parts = [f"[工具执行结果] {tool_id}"]
        parts.append(f"状态: {'成功' if success else '失败'}")

        if message:
            parts.append(f"消息: {message}")

        if error_code:
            parts.append(f"错误码: {error_code}")

        if data:
            data_str = str(data)
            if len(data_str) > 200:
                data_str = data_str[:197] + "..."
            parts.append(f"数据: {data_str}")

        return "\n".join(parts)

    def get_stats(self) -> dict[str, Any]:
        """
        获取过滤器统计信息

        Returns:
            Dict: 统计信息
        """
        return {
            "cooldown_map_size": len(self._last_feedback_time),
            "history_size": len(self._feedback_history),
            "config": {
                "silent_tools_count": len(self._config.SILENT_TOOLS),
                "observable_tools_count": len(self._config.OBSERVABLE_TOOLS),
                "cooldown_seconds": self._config.COOLDOWN_SECONDS,
            }
        }

    def reset_cooldown(self, tool_id: str | None = None):
        """
        重置冷却时间

        Args:
            tool_id: 指定工具ID，None则重置所有
        """
        if tool_id:
            self._last_feedback_time.pop(tool_id, None)
            _get_logger().debug(f"[ToolFeedbackFilter] 重置 {tool_id} 冷却时间")
        else:
            self._last_feedback_time.clear()
            _get_logger().debug("[ToolFeedbackFilter] 重置所有冷却时间")


# ========================================
# 便捷函数
# ========================================
def create_filter(config: ToolFeedbackConfig | None = None) -> ToolFeedbackFilter:
    """
    创建反馈过滤器实例

    Args:
        config: 配置对象

    Returns:
        ToolFeedbackFilter: 过滤器实例
    """
    return ToolFeedbackFilter(config)


# ========================================
# 模块导出
# ========================================
__all__ = [
    'FeedbackLevel',
    'FeedbackDecision',
    'ToolFeedbackConfig',
    'ToolFeedbackFilter',
    'create_filter',
]
