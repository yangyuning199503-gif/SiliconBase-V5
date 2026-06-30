#!/usr/bin/env python3
"""
权限标签系统
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

治理目标：消灭硬编码白名单。工具通过权限标签声明自身权限级别，
白名单是标签的筛选结果而非硬编码列表。

使用方式：
    from core.safety.permission_tags import PermissionTag, TOOL_PERMISSION_REGISTRY

    # 注册工具权限标签
    register_tool_permission("my_tool", [PermissionTag.DAILY_SAFE, PermissionTag.FILE_RW])

    # 获取日常模式可用工具
    daily_tools = get_tools_by_tag(PermissionTag.DAILY_SAFE)
"""

from enum import Enum

from core.logger import logger


class PermissionTag(str, Enum):
    """工具权限标签 - 工具在声明时标注自身权限"""
    DAILY_SAFE = "daily_safe"      # 日常模式可用（安全、无破坏性）
    NETWORK = "network"            # 涉及网络访问
    FILE_RW = "file_rw"            # 文件读写
    FILE_RO = "file_ro"            # 文件只读
    SYSTEM_EXEC = "system_exec"    # 系统命令执行
    TRADING = "trading"            # 交易相关（涉及资金）
    UI_CONTROL = "ui_control"      # UI 控制（鼠标、键盘、点击）
    VISION = "vision"              # 视觉（截图、图像分析）
    MEMORY = "memory"              # 记忆系统（读写用户数据）
    ADMIN = "admin"                # 管理员操作（危险）


# 工具权限注册表：{tool_name: set(PermissionTag)}
_TOOL_PERMISSION_REGISTRY: dict[str, set[PermissionTag]] = {}


def register_tool_permission(tool_name: str, tags: list[PermissionTag]) -> None:
    """
    注册工具的权限标签

    Args:
        tool_name: 工具名称
        tags: 权限标签列表
    """
    _TOOL_PERMISSION_REGISTRY[tool_name] = set(tags)
    logger.debug(f"[PermissionTag] 工具 '{tool_name}' 注册权限: {[t.value for t in tags]}")


def get_tools_by_tag(tag: PermissionTag) -> list[str]:
    """
    获取具有指定权限标签的所有工具

    Args:
        tag: 权限标签

    Returns:
        List[str]: 工具名称列表
    """
    return [
        name for name, tags in _TOOL_PERMISSION_REGISTRY.items()
        if tag in tags
    ]


def get_tool_permissions(tool_name: str) -> set[PermissionTag] | None:
    """
    获取指定工具的权限标签

    Args:
        tool_name: 工具名称

    Returns:
        Set[PermissionTag] 或 None（未注册）
    """
    return _TOOL_PERMISSION_REGISTRY.get(tool_name)


def has_permission(tool_name: str, tag: PermissionTag) -> bool:
    """
    检查工具是否具有指定权限标签

    Args:
        tool_name: 工具名称
        tag: 权限标签

    Returns:
        bool
    """
    tags = _TOOL_PERMISSION_REGISTRY.get(tool_name)
    return tags is not None and tag in tags


def is_tool_allowed_in_daily_mode(tool_name: str) -> bool:
    """
    检查工具是否允许在日常模式下使用

    规则：
    - 已注册且带有 DAILY_SAFE 标签 → 允许
    - 未注册 → 默认拒绝（保守策略）
    """
    return has_permission(tool_name, PermissionTag.DAILY_SAFE)


# ═══════════════════════════════════════════════════════════════
# 初始化：为现有工具注册权限标签
# ═══════════════════════════════════════════════════════════════

def _init_default_permissions():
    """初始化默认工具权限标签"""
    defaults = {
        # 感知类（日常模式安全）
        "get_perception": [PermissionTag.DAILY_SAFE, PermissionTag.VISION],
        "pixel_capture": [PermissionTag.DAILY_SAFE, PermissionTag.VISION],
        "visual_understand": [PermissionTag.DAILY_SAFE, PermissionTag.VISION],
        "vision_agent": [PermissionTag.DAILY_SAFE, PermissionTag.VISION],

        # 记忆类（日常模式安全）
        "memory_search": [PermissionTag.DAILY_SAFE, PermissionTag.MEMORY],
        "memory_add": [PermissionTag.DAILY_SAFE, PermissionTag.MEMORY],
        "memory_list": [PermissionTag.DAILY_SAFE, PermissionTag.MEMORY],
        "memory_update": [PermissionTag.DAILY_SAFE, PermissionTag.MEMORY],

        # 通信类（日常模式安全）
        "call_user": [PermissionTag.DAILY_SAFE],

        # 搜索类（日常模式安全）
        "web_search": [PermissionTag.DAILY_SAFE, PermissionTag.NETWORK],
        "web_fetch": [PermissionTag.DAILY_SAFE, PermissionTag.NETWORK],

        # 文件类（只读安全，读写需谨慎）
        "file_manager": [PermissionTag.DAILY_SAFE, PermissionTag.FILE_RW],
        "read_file": [PermissionTag.DAILY_SAFE, PermissionTag.FILE_RO],
        "get_tool_manual": [PermissionTag.DAILY_SAFE],
        "system_info": [PermissionTag.DAILY_SAFE],

        # UI 控制类（日常模式安全但需用户在场）
        "launch_app": [PermissionTag.DAILY_SAFE, PermissionTag.UI_CONTROL],
        "mouse_click": [PermissionTag.DAILY_SAFE, PermissionTag.UI_CONTROL],
        "keyboard_input": [PermissionTag.DAILY_SAFE, PermissionTag.UI_CONTROL],
        "click_text": [PermissionTag.DAILY_SAFE, PermissionTag.UI_CONTROL],
        "pixel_click": [PermissionTag.DAILY_SAFE, PermissionTag.UI_CONTROL],
        "browser_open": [PermissionTag.DAILY_SAFE, PermissionTag.UI_CONTROL, PermissionTag.NETWORK],
        "window_action": [PermissionTag.DAILY_SAFE, PermissionTag.UI_CONTROL],
        "process_start": [PermissionTag.DAILY_SAFE, PermissionTag.SYSTEM_EXEC],

        # 交易类（日常模式只允许查询，不允许下单）
        "btc_market_overview": [PermissionTag.DAILY_SAFE, PermissionTag.TRADING],
        "btc_status_query": [PermissionTag.DAILY_SAFE, PermissionTag.TRADING],
        "btc_get_klines": [PermissionTag.DAILY_SAFE, PermissionTag.TRADING],
        "btc_risk_assessment": [PermissionTag.DAILY_SAFE, PermissionTag.TRADING],

        # 以下工具不在日常模式白名单（需要显式授权）
        "shell_execute": [PermissionTag.SYSTEM_EXEC, PermissionTag.ADMIN],
        "btc_place_order": [PermissionTag.TRADING],
        "btc_close_position": [PermissionTag.TRADING],
    }

    for tool_name, tags in defaults.items():
        register_tool_permission(tool_name, tags)

    logger.info(f"[PermissionTag] 已初始化 {len(defaults)} 个工具的默认权限标签")


# 模块导入时自动初始化
_init_default_permissions()
