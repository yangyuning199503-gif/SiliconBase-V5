#!/usr/bin/env python3
"""
统一内容压缩模块
整合 MessageCompressor 和 ContextCompressor 的功能

设计目标:
1. 统一压缩逻辑，消除代码重复
2. 支持多种压缩策略（基于token数/基于消息数）
3. 保持向后兼容（原有类名作为别名）
4. 更好的可配置性和扩展性
"""

from typing import Any


def estimate_tokens(text: str) -> int:
    """
    估算文本的Token数量
    中文按2字符/token，英文按4字符/token，混合取平均值
    """
    if not text:
        return 0
    # 简单估算：平均2字符/token（中英文混合）
    return len(text) // 2 + 1


class ContentCompressor:
    """
    统一的内容压缩器

    整合 MessageCompressor 和 ContextCompressor 的功能，提供：
    - 基于token数量的智能压缩
    - 基于消息数量的分层压缩
    - 可配置的压缩策略
    - 丰富的元数据标记
    """

    # 默认阈值配置
    DEFAULT_THRESHOLDS = {
        "aggressive": {"token_limit": 2000, "target_tokens": 1000, "recent_keep": 4},
        "moderate": {"token_limit": 4000, "target_tokens": 2000, "recent_keep": 6},
        "minimal": {"token_limit": 6000, "target_tokens": 3000, "recent_keep": 10},
    }

    # 默认压缩参数（兼容 MessageCompressor）
    TOKEN_THRESHOLD = 3000       # 触发压缩的token阈值
    TARGET_TOKENS = 1500         # 压缩后目标token数
    RECENT_KEEP = 6              # 保留最近消息数

    def __init__(self,
                 mode: str = "moderate",
                 token_threshold: int | None = None,
                 target_tokens: int | None = None,
                 recent_keep: int | None = None,
                 max_total_messages: int = 50,
                 compress_threshold: int = 20,
                 preserve_system: bool = True):
        """
        初始化压缩器

        Args:
            mode: 压缩模式 ("aggressive" | "moderate" | "minimal")
            token_threshold: 自定义token阈值（覆盖mode配置）
            target_tokens: 自定义目标token数（覆盖mode配置）
            recent_keep: 自定义保留消息数（覆盖mode配置）
            max_total_messages: 最大总消息数限制
            compress_threshold: 基于消息数的压缩阈值
            preserve_system: 是否特殊处理system消息
        """
        # 从mode获取基础配置
        config = self.DEFAULT_THRESHOLDS.get(mode, self.DEFAULT_THRESHOLDS["moderate"])

        # 应用配置（自定义参数优先）
        self.token_threshold = token_threshold or config["token_limit"]
        self.target_tokens = target_tokens or config["target_tokens"]
        self.recent_keep = recent_keep or config["recent_keep"]

        # 其他配置
        self.max_total_messages = max_total_messages
        self.compress_threshold = compress_threshold
        self.preserve_system = preserve_system

        # 压缩统计
        self.compression_stats = {
            "total_compressions": 0,
            "tokens_saved": 0,
            "messages_compressed": 0
        }

    def compress(self, messages: list[dict],
                 strategy: str = "auto",
                 **kwargs) -> list[dict]:
        """
        压缩消息列表

        Args:
            messages: 消息列表
            strategy: 压缩策略 ("auto" | "token" | "count")
            **kwargs: 额外参数

        Returns:
            压缩后的消息列表
        """
        if not messages:
            return []

        # 自动选择策略
        if strategy == "auto":
            total_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)
            if total_tokens >= self.token_threshold:
                strategy = "token"
            elif len(messages) >= self.compress_threshold:
                strategy = "count"
            else:
                return messages

        # 根据策略执行压缩
        if strategy == "token":
            return self._compress_by_token(messages, **kwargs)
        elif strategy == "count":
            return self._compress_by_count(messages, **kwargs)
        else:
            return messages

    def _compress_by_token(self, messages: list[dict]) -> list[dict]:
        """
        基于token数量的压缩（兼容 MessageCompressor）
        """
        if len(messages) <= self.recent_keep:
            return messages

        # 计算当前token数
        total_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)

        if total_tokens < self.token_threshold:
            return messages

        # 分离system消息（如果需要保留）
        if self.preserve_system:
            system_msgs = [m for m in messages if m.get("role") == "system" and not m.get("_compressed")]
            normal_msgs = [m for m in messages if m.get("role") != "system" or m.get("_compressed")]
        else:
            system_msgs = []
            normal_msgs = messages

        # 需要压缩
        recent = normal_msgs[-self.recent_keep:]
        older = normal_msgs[:-self.recent_keep]

        # 压缩旧消息
        compressed_older = self._compress_old_messages(older)

        # 更新统计
        self.compression_stats["total_compressions"] += 1
        self.compression_stats["tokens_saved"] += max(0, total_tokens - self.target_tokens)
        self.compression_stats["messages_compressed"] += len(older)

        return system_msgs + compressed_older + recent

    def _compress_by_count(self, messages: list[dict]) -> list[dict]:
        """
        基于消息数量的压缩（兼容 ContextCompressor）
        """
        if len(messages) <= self.compress_threshold:
            return messages

        # 分离system消息和普通消息
        if self.preserve_system:
            system_msgs = [m for m in messages if m.get("role") == "system" and not m.get("_compressed")]
            normal_msgs = [m for m in messages if m.get("role") != "system" or m.get("_compressed")]
        else:
            system_msgs = []
            normal_msgs = messages

        if len(normal_msgs) <= self.compress_threshold:
            return messages

        # 分层策略
        recent = normal_msgs[-self.recent_keep:]
        older = normal_msgs[:-self.recent_keep]
        compressed_older = self._compress_old_messages(older)

        # 更新统计
        self.compression_stats["total_compressions"] += 1
        self.compression_stats["messages_compressed"] += len(older)

        return system_msgs + compressed_older + recent

    def _compress_old_messages(self, messages: list[dict]) -> list[dict]:
        """
        将旧消息压缩为摘要（统一实现）
        """
        if not messages:
            return []

        tool_calls = []
        key_events = []

        for msg in messages:
            content = msg.get("content", "")
            role = msg.get("role", "")

            # 提取工具调用
            if "【工具结果】" in content or "[工具结果]" in content:
                tool_name = "unknown"
                if "【工具结果】" in content:
                    parts = content.split("【工具结果】")
                    if len(parts) > 1:
                        tool_name = parts[1].split(":")[0].strip()[:20]
                success = "成功" in content or "✓" in content or "success" in content.lower()
                tool_calls.append(f"{tool_name}({'OK' if success else 'FAIL'})")

            # 提取关键事件
            if any(kw in content for kw in ["完成", "失败", "错误", "警告", "启动", "打开"]):
                summary = content[:60] + "..." if len(content) > 60 else content
                key_events.append(f"[{role}]{summary}")

        # 去重（保持顺序）
        tool_calls = list(dict.fromkeys(tool_calls))
        key_events = list(dict.fromkeys(key_events))

        # 构建摘要
        summary_parts = []
        if tool_calls:
            summary_parts.append(f"已执行({len(tool_calls)}次): " + ", ".join(tool_calls[-8:]))
        if key_events:
            summary_parts.append("关键事件: " + "; ".join(key_events[-5:]))

        summary_text = " | ".join(summary_parts) if summary_parts else "历史消息已压缩"

        return [{
            "role": "system",
            "content": f"[历史摘要] {summary_text}",
            "_compressed": True,
            "_original_count": len(messages),
            "_compressor": "ContentCompressor"
        }]

    def summarize_execution(self, history: list[dict]) -> str:
        """
        总结执行历史（从 ContextCompressor 迁移）
        """
        if not history:
            return "无执行记录"

        recent = history[-5:]
        summaries = []

        for h in recent:
            tool = h.get("tool", "unknown")
            success = h.get("success", False)
            result = h.get("result", {})

            if success:
                summaries.append(f"{tool}(成功)")
            else:
                # 提取错误信息
                error_msg = ""
                if isinstance(result, dict):
                    error_msg = result.get("user_message", "") or result.get("error", "")
                    if not error_msg:
                        error_msg = result.get("message", "")
                error_msg = str(error_msg)[:60] if error_msg else "未知错误"
                summaries.append(f"{tool}(失败: {error_msg})")

        return " -> ".join(summaries) if summaries else "无执行记录"

    def get_stats(self) -> dict[str, Any]:
        """获取压缩统计信息"""
        return self.compression_stats.copy()

    def reset_stats(self):
        """重置统计信息"""
        self.compression_stats = {
            "total_compressions": 0,
            "tokens_saved": 0,
            "messages_compressed": 0
        }


# ═══════════════════════════════════════════════════════════════
# 向后兼容：保留原有类名作为别名
# ═══════════════════════════════════════════════════════════════

class MessageCompressor(ContentCompressor):
    """
    【向后兼容】消息历史压缩器

    原 working_memory.py 中的 MessageCompressor，现在继承自 ContentCompressor
    保持完全相同的API和行为
    """

    # 保持原有类属性
    TOKEN_THRESHOLD = 3000
    TARGET_TOKENS = 1500
    RECENT_KEEP = 6

    def __init__(self):
        """初始化，使用原有默认配置"""
        super().__init__(
            mode="moderate",
            token_threshold=self.TOKEN_THRESHOLD,
            target_tokens=self.TARGET_TOKENS,
            recent_keep=self.RECENT_KEEP
        )

    @classmethod
    def compress(cls, messages: list[dict]) -> list[dict]:
        """
        【类方法】压缩消息历史（保持原有API）
        注意：直接调用父类的compress方法，避免递归
        """
        # 创建实例并使用父类的compress方法
        instance = cls()
        # 使用父类的compress方法，强制使用token策略
        return ContentCompressor.compress(instance, messages, strategy="token")

    @classmethod
    def _compress_old_messages(cls, messages: list[dict]) -> list[dict]:
        """
        【类方法】压缩旧消息（保持原有API）
        注意：直接调用父类的方法，避免递归
        """
        instance = cls()
        return ContentCompressor._compress_old_messages(instance, messages)


class ContextCompressor(ContentCompressor):
    """
    【向后兼容】上下文压缩管理器

    原 context_builder.py 中的 ContextCompressor，现在继承自 ContentCompressor
    保持完全相同的API和行为
    """

    def __init__(self,
                 max_total_messages: int = 50,
                 recent_keep: int = 10,
                 compress_threshold: int = 20,
                 max_summary_tokens: int = 500):
        """初始化，保持原有参数"""
        super().__init__(
            mode="moderate",
            recent_keep=recent_keep,
            max_total_messages=max_total_messages,
            compress_threshold=compress_threshold
        )
        self.max_summary_tokens = max_summary_tokens  # 保持原有属性

    def compress(self, messages: list[dict]) -> list[dict]:
        """
        压缩消息列表（保持原有API）
        """
        return super().compress(messages, strategy="count")

    def _compress_old_messages(self, messages: list[dict]) -> list[dict]:
        """
        压缩旧消息（保持原有行为，但使用统一实现）
        """
        if not messages:
            return []

        tool_calls = []
        important_events = []

        for msg in messages:
            content = msg.get("content", "")
            role = msg.get("role", "")

            # 识别工具结果
            if "【工具结果】" in content:
                tool_name = content.split("【工具结果】")[1].split(":")[0] if "【工具结果】" in content else "未知"
                success = "成功" in content or "success" in content.lower()
                tool_calls.append(f"{tool_name}({'成功' if success else '失败'})")

            # 识别重要事件
            if any(kw in content for kw in ["完成", "失败", "错误", "启动", "打开"]):
                summary = content[:50] + "..." if len(content) > 50 else content
                important_events.append(f"[{role}] {summary}")

        # 构建摘要
        summary_parts = []
        if tool_calls:
            summary_parts.append(f"已执行工具: {', '.join(tool_calls[-5:])}")
        if important_events:
            summary_parts.append(f"关键事件: {'; '.join(important_events[-3:])}")

        summary_text = "\n".join(summary_parts) if summary_parts else "历史对话已压缩"

        return [{
            "role": "system",
            "content": f"[历史摘要] {summary_text}",
            "_compressed": True,
            "_original_count": len(messages)
        }]

    def _summarize_execution(self, history: list[dict]) -> str:
        """
        总结执行历史（保持原有API）
        """
        return self.summarize_execution(history)


# 全局实例（向后兼容）
# 创建全局实例供旧代码直接使用
_default_compressor = ContentCompressor()


def compress_messages(messages: list[dict],
                      mode: str = "moderate",
                      **kwargs) -> list[dict]:
    """
    便捷函数：压缩消息

    Args:
        messages: 消息列表
        mode: 压缩模式
        **kwargs: 其他参数

    Returns:
        压缩后的消息列表
    """
    compressor = ContentCompressor(mode=mode, **kwargs)
    return compressor.compress(messages, strategy="auto")


def get_compressor(mode: str = "moderate", **kwargs) -> ContentCompressor:
    """
    获取压缩器实例

    Args:
        mode: 压缩模式
        **kwargs: 其他参数

    Returns:
        ContentCompressor实例
    """
    return ContentCompressor(mode=mode, **kwargs)


# ═══════════════════════════════════════════════════════════════
# 文件总结
# ═══════════════════════════════════════════════════════════════
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的统一压缩模块，整合原有分散的压缩逻辑。
#
# 【架构设计】
# - ContentCompressor: 统一压缩器，支持多种策略
# - MessageCompressor: 向后兼容类，继承自ContentCompressor
# - ContextCompressor: 向后兼容类，继承自ContentCompressor
# - 便捷函数: compress_messages, get_compressor
#
# 【向后兼容】
# - 原有类名保留，API完全一致
# - 原有类属性保留（TOKEN_THRESHOLD等）
# - 原有类方法保留（compress, _compress_old_messages等）
#
# 【使用方式】
# 1. 新代码推荐: from core.utils.compression import ContentCompressor
# 2. 向后兼容: from core.utils.compression import MessageCompressor, ContextCompressor
# 3. 便捷函数: from core.utils.compression import compress_messages
#
# 【关联文件】
# - working_memory.py: 使用MessageCompressor（现在指向本文件）
# - context_builder.py: 使用ContextCompressor（现在指向本文件）
# ═══════════════════════════════════════════════════════════════
