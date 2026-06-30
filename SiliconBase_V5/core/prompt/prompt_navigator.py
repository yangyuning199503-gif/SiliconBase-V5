#!/usr/bin/env python3
"""
提示词导航器 - 兼容层
从 prompt_builder 和 prompt_templates 导出核心功能

【文件角色】
本文件是 SiliconBase V5 系统的"提示词导航器"兼容模块，
为保持向后兼容，从 prompt_builder 和 prompt_templates 重新导出功能。

【关联文件】
- core/prompt_builder.py              : 提示词构建器实现
- core/prompt_templates.py            : 提示词模板定义
- core/command_parser.py              : 使用导航器的命令解析器

【核心功能效果】
1. 提供 PromptNavigator 类，支持 L1/L2/L3 三层导航
2. 提供 NavigationCommands 枚举，定义导航命令
3. 提供 get_navigator() 函数，获取导航器实例
4. 提供 is_navigation_command() 函数，识别导航命令
5. 提供 handle_navigation() 函数，处理导航逻辑
"""

from dataclasses import dataclass
from enum import Enum

from core.intent.command_parser import LAYER_COMMANDS
from core.logger import logger
from core.prompt.prompt_builder import PromptLayer


def _get_builder():
    """延迟导入LayeredPromptBuilder，避免循环导入"""
    from core.prompt.prompt_builder import LayeredPromptBuilder
    return LayeredPromptBuilder()


class NavigationCommands(Enum):
    """导航命令枚举"""
    # L1 命令
    HOME = "home"
    OVERVIEW = "overview"

    # L2 命令
    MANUAL = "manual"
    TOOLS = "tools"
    MENU = "menu"

    # L3 命令
    BACK = "back"
    RETURN = "return"

    # 帮助
    HELP = "help"


@dataclass
class NavigationResult:
    """导航结果"""
    success: bool
    layer: PromptLayer | None
    prompt: str | None
    message: str


class PromptNavigator:
    """
    提示词导航器

    职责：管理 L1/L2/L3 三层提示词之间的导航

    【使用示例】
        navigator = get_navigator()

        # 检查是否是导航命令
        if navigator.is_navigation_command("手册"):
            result = navigator.navigate("手册", working_memory)
            print(result.prompt)  # 输出 L2 层提示词
    """

    _instance = None
    _lock = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._builder = _get_builder()
        self._current_layer = PromptLayer.L1_OVERVIEW
        self._current_tool: str | None = None

        logger.info("[PromptNavigator] 提示词导航器初始化完成")

    def is_navigation_command(self, text: str) -> bool:
        """
        检查文本是否是导航命令

        Args:
            text: 输入文本

        Returns:
            是否是导航命令
        """
        if not text:
            return False
        text = text.strip().lower()
        # 检查所有命令列表中的值，而不是keys
        return any(text in [cmd.lower() for cmd in commands] for commands in LAYER_COMMANDS.values())

    def navigate(self, command: str, working_memory=None) -> NavigationResult:
        """
        执行导航

        Args:
            command: 导航命令
            working_memory: 工作内存（可选）

        Returns:
            NavigationResult 导航结果
        """
        try:
            layer, prompt = self._builder.handle_layer_command(command)
            self._current_layer = layer

            return NavigationResult(
                success=True,
                layer=layer,
                prompt=prompt,
                message=f"导航到 {layer.value}"
            )
        except Exception as e:
            logger.error(f"[PromptNavigator] 导航失败: {e}")
            return NavigationResult(
                success=False,
                layer=None,
                prompt=None,
                message=f"导航失败: {e}"
            )

    def get_current_layer(self) -> PromptLayer:
        """获取当前层级"""
        return self._current_layer

    def get_layer_prompt(self, layer: PromptLayer, **kwargs) -> str:
        """
        获取指定层级的提示词

        Args:
            layer: 目标层级
            **kwargs: 额外参数

        Returns:
            提示词字符串
        """
        # 这里简化实现，实际应该根据不同的layer调用不同的builder方法
        if layer == PromptLayer.L1_OVERVIEW:
            return "【L1 - 系统概览】"
        elif layer == PromptLayer.L2_MANUAL:
            return "【L2 - 工具手册】"
        elif layer == PromptLayer.L3_TOOL_DETAIL:
            tool_id = kwargs.get('tool_id', 'unknown')
            return f"【L3 - {tool_id} 工具详情】"
        return "【未知层级】"


# 模块级单例
_navigator_instance: PromptNavigator | None = None


def get_navigator() -> PromptNavigator:
    """
    获取提示词导航器实例（单例）

    Returns:
        PromptNavigator 实例
    """
    global _navigator_instance
    if _navigator_instance is None:
        _navigator_instance = PromptNavigator()
    return _navigator_instance


def is_navigation_command(text: str) -> bool:
    """
    检查文本是否是导航命令

    Args:
        text: 输入文本

    Returns:
        是否是导航命令
    """
    navigator = get_navigator()
    return navigator.is_navigation_command(text)


def handle_navigation(command: str, working_memory=None) -> NavigationResult:
    """
    处理导航命令

    Args:
        command: 导航命令
        working_memory: 工作内存（可选）

    Returns:
        NavigationResult 导航结果
    """
    navigator = get_navigator()
    return navigator.navigate(command, working_memory)


# 为了向后兼容，导出别名
NavigationResult = NavigationResult


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"提示词导航器"兼容模块，
# 从 prompt_builder 和 prompt_templates 重新导出核心功能，
# 确保向后兼容性。
#
# 【架构设计】
# - 单例模式: PromptNavigator 使用单例模式，全局唯一实例
# - 适配器模式: 将 prompt_builder 功能适配为导航器接口
# - 兼容导出: 保持与原 prompt_navigator 模块相同的导出接口
#
# 【关联文件】
# - core/prompt_builder.py              : 提示词构建器实现
# - core/prompt_templates.py            : 提示词模板定义
# - core/command_parser.py              : 使用导航器的命令解析器
#
# 【导出列表】
# - PromptNavigator     : 提示词导航器类
# - NavigationCommands  : 导航命令枚举
# - NavigationResult    : 导航结果数据类
# - get_navigator()     : 获取导航器实例
# - is_navigation_command() : 识别导航命令
# - handle_navigation() : 处理导航命令
# =============================================================================
