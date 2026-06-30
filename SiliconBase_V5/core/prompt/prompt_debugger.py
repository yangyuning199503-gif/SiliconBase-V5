#!/usr/bin/env python3
"""
提示词调试模块
用于保存和获取AI实际收到的完整提示词，支持前端调试功能

功能：
1. 保存最后一次发送给AI的完整system_prompt
2. 记录提示词的各个组成部分
3. 提供API接口供前端查询
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from core.logger import logger

# 线程安全的存储
_prompt_storage: dict[str, 'PromptDebugInfo'] = {}
_storage_lock = threading.Lock()

# 默认保存的最大历史记录数
MAX_HISTORY_SIZE = 10


@dataclass
class PromptComponent:
    """提示词组件"""
    name: str
    content: str
    description: str = ""
    order: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "content": self.content,
            "description": self.description,
            "order": self.order,
            "token_count": estimate_tokens(self.content)
        }


@dataclass
class PromptDebugInfo:
    """提示词调试信息"""
    user_id: str
    full_prompt: str
    components: list[PromptComponent] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    session_id: str | None = None
    query: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "full_prompt": self.full_prompt,
            "components": [c.to_dict() for c in sorted(self.components, key=lambda x: x.order)],
            "timestamp": self.timestamp,
            "formatted_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.timestamp)),
            "session_id": self.session_id,
            "query": self.query,
            "total_tokens": estimate_tokens(self.full_prompt),
            "preview": self.full_prompt[:500] + "..." if len(self.full_prompt) > 500 else self.full_prompt
        }


def estimate_tokens(text: str) -> int:
    """
    估算文本的token数量
    使用简单启发式：中文字符约1.5个token，英文单词约1.3个token
    """
    if not text:
        return 0

    # 统计中文字符
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    # 统计英文单词（粗略估计）
    english_words = len(text.split())
    # 其他字符
    other_chars = len(text) - chinese_chars

    # 估算token数
    tokens = int(chinese_chars * 1.5 + english_words * 1.3 + other_chars * 0.25)
    return max(1, tokens)


def save_last_prompt(
    user_id: str,
    full_system_prompt: str,
    components_data: dict[str, Any] | None = None,
    session_id: str | None = None,
    query: str | None = None
) -> None:
    """
    保存最后一次使用的完整提示词

    Args:
        user_id: 用户ID
        full_system_prompt: 完整的系统提示词
        components_data: 提示词组成部分数据，包含：
            - base_prompt: 基础提示词
            - three_views: 三观提示词
            - memory: 记忆上下文
            - experience: 经验上下文
            - layer: 层级提示
            - reasoning: 推理框架
            - exploration: 探索增强
            - phase_context: 阶段上下文
            - user_personalization: 用户个性化
            - vision: 视觉感知
        session_id: 会话ID
        query: 用户查询
    """
    try:
        components = []

        if components_data:
            # 按顺序添加各个组件
            component_configs = [
                ("three_views", "三观提示词", "道德观、价值观、世界观指导", 1),
                ("base_prompt", "基础提示词", "roles.yaml模块组合后的基础提示词", 2),
                ("user_personalization", "用户个性化", "用户偏好和个性化设置", 3),
                ("memory", "记忆上下文", "注入的相关记忆", 4),
                ("experience", "经验上下文", "注入的相关经验", 5),
                ("exploration", "探索增强", "任务探索增强提示", 6),
                ("layer", "层级提示", "L1/L2/L3层级特定提示", 7),
                ("phase_context", "阶段上下文", "阶段锚点防止AI遗忘", 8),
                ("reasoning", "推理框架", "推理和决策框架", 9),
                ("vision", "视觉感知", "屏幕视觉描述", 10),
            ]

            for key, name, desc, order in component_configs:
                if key in components_data and components_data[key]:
                    content = str(components_data[key])
                    if content.strip():
                        components.append(PromptComponent(
                            name=name,
                            content=content,
                            description=desc,
                            order=order
                        ))

        debug_info = PromptDebugInfo(
            user_id=user_id,
            full_prompt=full_system_prompt,
            components=components,
            session_id=session_id,
            query=query
        )

        with _storage_lock:
            _prompt_storage[user_id] = debug_info

        logger.debug(f"[PromptDebugger] 已保存用户 {user_id} 的提示词调试信息")

    except Exception as e:
        logger.warning(f"[PromptDebugger] 保存提示词调试信息失败: {e}")


def get_last_prompt(user_id: str) -> dict[str, Any] | None:
    """
    获取最后一次的提示词调试信息

    Args:
        user_id: 用户ID

    Returns:
        提示词调试信息字典，如果不存在返回None
    """
    with _storage_lock:
        debug_info = _prompt_storage.get(user_id)

    if debug_info:
        return debug_info.to_dict()
    return None


def get_last_prompt_preview(user_id: str, max_length: int = 500) -> str | None:
    """
    获取最后一次提示词的预览

    Args:
        user_id: 用户ID
        max_length: 最大长度

    Returns:
        提示词预览字符串
    """
    debug_info = get_last_prompt(user_id)
    if debug_info:
        prompt = debug_info.get("full_prompt", "")
        if len(prompt) > max_length:
            return prompt[:max_length] + f"\n\n... (共 {len(prompt)} 字符)"
        return prompt
    return None


def clear_user_prompt_history(user_id: str) -> bool:
    """
    清除用户的提示词历史

    Args:
        user_id: 用户ID

    Returns:
        是否成功清除
    """
    with _storage_lock:
        if user_id in _prompt_storage:
            del _prompt_storage[user_id]
            return True
    return False


def get_storage_stats() -> dict[str, Any]:
    """
    获取存储统计信息

    Returns:
        统计信息字典
    """
    with _storage_lock:
        return {
            "total_users": len(_prompt_storage),
            "user_ids": list(_prompt_storage.keys()),
            "memory_size": sum(
                len(info.full_prompt) + sum(len(c.content) for c in info.components)
                for info in _prompt_storage.values()
            )
        }
