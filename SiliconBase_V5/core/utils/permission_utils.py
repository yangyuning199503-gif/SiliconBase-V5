#!/usr/bin/env python3
"""
权限检查工具模块 - 提供统一的权限验证功能

用于防止空值绕过等权限控制漏洞
"""
from typing import Any

from core.logger import logger


def check_memory_permission(
    memory: dict[str, Any],
    user_id: str,
    action: str = "操作"
) -> tuple[bool, str]:
    """
    统一的记忆权限检查

    检查用户是否有权限对指定记忆进行操作。
    特别针对空值绕过漏洞进行防护。

    Args:
        memory: 记忆数据字典
        user_id: 操作用户ID (如 "AI", "user", "system")
        action: 操作类型描述 (如 "修改", "删除")

    Returns:
        Tuple[bool, str]: (是否允许, 错误信息/通过原因)

    安全检查点:
        1. creator 字段是否存在
        2. creator 字段是否为 None
        3. creator 字段是否为空字符串
        4. creator 字段是否为仅包含空白字符的字符串
    """
    memory_id = memory.get("id", "unknown")
    creator = memory.get("creator")

    # ===== 空值验证 - 防止空值绕过漏洞 =====
    if creator is None:
        logger.warning(f"[Permission] 记忆 {memory_id} 的 creator 字段为 None，拒绝{action}")
        return False, f"记忆缺少创建者信息(creator=None)，禁止{action}"

    if not isinstance(creator, str):
        logger.warning(f"[Permission] 记忆 {memory_id} 的 creator 字段类型错误: {type(creator)}，拒绝{action}")
        return False, f"记忆创建者信息格式错误，禁止{action}"

    if creator.strip() == "":
        logger.warning(f"[Permission] 记忆 {memory_id} 的 creator 字段为空/空白字符串，拒绝{action}")
        return False, f"记忆缺少有效的创建者信息，禁止{action}"

    # ===== 权限判断 =====
    # AI 只能操作自己创建的记忆
    if user_id == "AI" and creator != "AI":
        logger.warning(f"[Permission] AI尝试{action} {creator} 创建的记忆 {memory_id}")
        return False, f"AI只能{action}自己创建的记忆，该记忆由 {creator} 创建"

    logger.debug(f"[Permission] 用户 {user_id} 获得记忆 {memory_id} 的{action}权限")
    return True, "权限检查通过"


def check_ai_memory_permission(
    memory: dict[str, Any],
    action: str = "操作"
) -> tuple[bool, str]:
    """
    简化的AI权限检查

    专门用于检查AI是否有权限操作指定记忆

    Args:
        memory: 记忆数据字典
        action: 操作类型描述

    Returns:
        Tuple[bool, str]: (是否允许, 错误信息/通过原因)
    """
    return check_memory_permission(memory, "AI", action)


def validate_creator_field(memory: dict[str, Any]) -> tuple[bool, str | None]:
    """
    验证记忆数据中的 creator 字段是否有效

    Args:
        memory: 记忆数据字典

    Returns:
        Tuple[bool, Optional[str]]: (是否有效, 错误信息)
    """
    if "creator" not in memory:
        return False, "缺少 creator 字段"

    creator = memory.get("creator")
    memory_id = memory.get("id", "unknown")

    if creator is None:
        return False, f"记忆 {memory_id}: creator 字段为 None"

    if not isinstance(creator, str):
        return False, f"记忆 {memory_id}: creator 字段类型错误 ({type(creator)})"

    if creator.strip() == "":
        return False, f"记忆 {memory_id}: creator 字段为空字符串"

    return True, None


# ===== 便捷函数 =====

def is_creator_valid(memory: dict[str, Any]) -> bool:
    """快速检查 creator 字段是否有效"""
    valid, _ = validate_creator_field(memory)
    return valid


def get_safe_creator(memory: dict[str, Any], default: str = "system") -> str:
    """
    安全获取 creator 字段，无效时返回默认值

    注意：此函数仅用于读取，不应用于权限判断。
    权限判断应使用 check_memory_permission() 进行完整验证。
    """
    creator = memory.get("creator")

    if creator is None:
        return default

    if not isinstance(creator, str):
        return default

    if creator.strip() == "":
        return default

    return creator
