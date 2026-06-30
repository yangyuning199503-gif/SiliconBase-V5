#!/usr/bin/env python3
"""
Memory Source 枚举定义 - Agent-4：主动被动区分
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
定义记忆来源的枚举类型，用于区分不同来源的记忆：
- AI: AI自主写入
- SYSTEM: 底座强制推送
- USER: 用户手动添加
- REFLECTION: 反思产生
- EVOLUTION: 进化产生

【使用场景】
1. 追踪记忆来源，便于数据分析和问题定位
2. 支持按来源筛选记忆
3. 数据统计报表，分析各来源记忆占比
4. 权限控制：某些来源的记忆不可修改

【关联文件】
- core/memory.py: 数据库schema和存储实现
- tools/memory_add.py: AI调用时使用MemorySource.AI
- core/execution_memory.py: 底座推送时使用MemorySource.SYSTEM
- core/reflector.py: 反思产生时使用MemorySource.REFLECTION
- core/evolution.py: 进化产生时使用MemorySource.EVOLUTION
"""
from enum import Enum
from typing import Optional, Union


class MemorySource(str, Enum):
    """
    记忆来源枚举

    用于标识记忆是由哪个模块/角色创建的，支持字符串和枚举值比较。
    继承str以便直接与数据库中的字符串值比较。
    """
    AI = "ai"                    # AI自主写入 - AI通过工具调用主动添加的记忆
    SYSTEM = "system"            # 底座强制推送 - 底座系统强制写入的记忆
    USER = "user"                # 用户手动添加 - 用户通过界面或API手动添加
    REFLECTION = "reflection"    # 反思产生 - Reflector反思系统产生的记忆
    EVOLUTION = "evolution"      # 进化产生 - Evolution进化系统产生的记忆

    def __str__(self) -> str:
        """返回枚举值的字符串表示"""
        return self.value

    @classmethod
    def from_string(cls, value: str) -> Optional["MemorySource"]:
        """
        从字符串创建枚举值

        Args:
            value: 字符串值，如 "ai", "system" 等

        Returns:
            MemorySource枚举值，如果无效则返回None
        """
        try:
            return cls(value.lower())
        except ValueError:
            return None

    @classmethod
    def get_all_sources(cls) -> list[str]:
        """获取所有来源的字符串值列表"""
        return [source.value for source in cls]

    @classmethod
    def get_source_display_name(cls, source: Union[str, "MemorySource"]) -> str:
        """
        获取来源的显示名称（中文）

        Args:
            source: 来源枚举或字符串

        Returns:
            中文显示名称
        """
        display_names = {
            cls.AI.value: "AI自主",
            cls.SYSTEM.value: "系统推送",
            cls.USER.value: "用户添加",
            cls.REFLECTION.value: "反思产生",
            cls.EVOLUTION.value: "进化产生"
        }
        source_value = source.value if isinstance(source, cls) else str(source).lower()
        return display_names.get(source_value, "未知来源")

    @classmethod
    def get_source_description(cls, source: Union[str, "MemorySource"]) -> str:
        """
        获取来源的详细描述

        Args:
            source: 来源枚举或字符串

        Returns:
            详细描述
        """
        descriptions = {
            cls.AI.value: "AI通过memory_add等工具自主决策添加的记忆",
            cls.SYSTEM.value: "底座系统自动推送的记忆，如执行记录、系统事件",
            cls.USER.value: "用户通过界面或API手动添加的记忆",
            cls.REFLECTION.value: "Reflector反思系统在执行过程中产生的洞察",
            cls.EVOLUTION.value: "Evolution进化系统从任务执行中提取的经验"
        }
        source_value = source.value if isinstance(source, cls) else str(source).lower()
        return descriptions.get(source_value, "未知来源")


# 默认来源值（向后兼容）
DEFAULT_MEMORY_SOURCE = MemorySource.SYSTEM


def validate_source(source: str | MemorySource | None) -> MemorySource:
    """
    验证并转换来源值

    Args:
        source: 来源值，可以是字符串、枚举或None

    Returns:
        有效的MemorySource枚举值，无效时返回默认值SYSTEM
    """
    if source is None:
        return DEFAULT_MEMORY_SOURCE

    if isinstance(source, MemorySource):
        return source

    if isinstance(source, str):
        parsed = MemorySource.from_string(source)
        if parsed:
            return parsed

    return DEFAULT_MEMORY_SOURCE


def is_valid_source(source: str | MemorySource) -> bool:
    """
    检查来源值是否有效

    Args:
        source: 要检查的来源值

    Returns:
        是否有效
    """
    if isinstance(source, MemorySource):
        return True

    if isinstance(source, str):
        return MemorySource.from_string(source) is not None

    return False
