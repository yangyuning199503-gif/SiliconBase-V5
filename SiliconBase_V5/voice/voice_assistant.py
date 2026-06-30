#!/usr/bin/env python3
"""
语音助手 - 为 L1/L2/L3 提示词导航系统提供语音反馈

主要功能：
1. 层级切换语音反馈（L1↔L2↔L3）
2. 导航命令语音播报
3. 查询状态语音提示
"""

from core.logger import logger
from voice.voice_prompts import ANNOUNCEMENTS as VP_ANNOUNCEMENTS


class VoiceAssistant:
    """
    语音助手类

    为分层提示词导航系统提供标准化的语音反馈机制。
    支持 L1/L2/L3 层级切换时的语音播报。
    """

    # 语音播报模板（已迁移至 voice_prompts.py，保留兼容引用）
    ANNOUNCEMENTS = VP_ANNOUNCEMENTS

    def __init__(self, voice_interface=None):
        """
        初始化语音助手

        Args:
            voice_interface: VoiceInterface 实例，用于实际播报
        """
        self.voice = voice_interface
        self._enabled = True

    def set_voice_interface(self, voice_interface):
        """设置语音接口实例"""
        self.voice = voice_interface

    def enable(self):
        """启用语音反馈"""
        self._enabled = True
        logger.info("[VoiceAssistant] 语音反馈已启用")

    def disable(self):
        """禁用语音反馈"""
        self._enabled = False
        logger.info("[VoiceAssistant] 语音反馈已禁用")

    def is_enabled(self) -> bool:
        """检查语音反馈是否启用"""
        return self._enabled and self.voice is not None

    def speak(self, text: str, is_system: bool = True, wait: bool = False):
        """
        语音播报（内部方法）

        Args:
            text: 要播报的文本
            is_system: 是否是系统音
            wait: 是否等待播报完成
        """
        if not self.is_enabled():
            logger.debug(f"[VoiceAssistant] 语音反馈已禁用，跳过播报: {text}")
            return

        try:
            self.voice.speak(text, is_system=is_system, wait=wait)
            logger.debug(f"[VoiceAssistant] 语音播报: {text}")
        except Exception as e:
            logger.error(f"[VoiceAssistant] 语音播报失败: {e}")

    # ==================== 层级切换语音反馈 ====================

    def announce_l1_overview(self, from_layer: str = None):
        """
        播报进入 L1 概览层

        Args:
            from_layer: 从哪个层级切换而来 ('l1', 'l2', 'l3')
        """
        if from_layer == 'l2':
            text = self.ANNOUNCEMENTS['to_l1_from_l2']
        elif from_layer == 'l3':
            text = self.ANNOUNCEMENTS['to_l1_from_l3']
        else:
            text = self.ANNOUNCEMENTS['to_l1_overview']

        self.speak(text, is_system=True)

    def announce_l2_manual(self, from_layer: str = None):
        """
        播报进入 L2 手册层

        Args:
            from_layer: 从哪个层级切换而来 ('l1', 'l2', 'l3')
        """
        if from_layer == 'l1':
            text = self.ANNOUNCEMENTS['to_l2_from_l1']
        elif from_layer == 'l3':
            text = self.ANNOUNCEMENTS['to_l2_from_l3']
        else:
            text = self.ANNOUNCEMENTS['to_l2_manual']

        self.speak(text, is_system=True)

    def announce_l3_tool_detail(self, tool_name: str, from_layer: str = None):
        """
        播报进入 L3 工具详情层

        Args:
            tool_name: 工具名称
            from_layer: 从哪个层级切换而来 ('l1', 'l2', 'l3')
        """
        if from_layer == 'l1':
            template = self.ANNOUNCEMENTS['to_l3_from_l1']
        elif from_layer == 'l2':
            template = self.ANNOUNCEMENTS['to_l3_from_l2']
        else:
            template = self.ANNOUNCEMENTS['to_l3_tool_detail']

        text = template.format(tool_name=tool_name)
        self.speak(text, is_system=True)

    def announce_layer_switch(self, to_layer: str, from_layer: str = None, tool_name: str = None):
        """
        通用层级切换播报

        Args:
            to_layer: 目标层级 ('l1', 'l2', 'l3')
            from_layer: 源层级 ('l1', 'l2', 'l3')
            tool_name: 工具名称（切换到L3时需要）
        """
        if to_layer == 'l1':
            self.announce_l1_overview(from_layer)
        elif to_layer == 'l2':
            self.announce_l2_manual(from_layer)
        elif to_layer == 'l3' and tool_name:
            self.announce_l3_tool_detail(tool_name, from_layer)
        else:
            self.speak(self.ANNOUNCEMENTS['switching'], is_system=True)

    # ==================== 导航命令语音反馈 ====================

    def announce_navigation(self, command: str):
        """
        播报导航命令反馈

        Args:
            command: 导航命令（如"手册"、"首页"、工具名等）
        """
        command_map = {
            '手册': '正在查询中，请稍后...',
            'manual': '正在查询中，请稍后...',
            '首页': '正在查询中，请稍后...',
            'home': '正在查询中，请稍后...',
            '返回': '正在查询中，请稍后...',
            'back': '正在查询中，请稍后...',
            '目录': '正在查询中，请稍后...',
            'menu': '正在查询中，请稍后...',
        }

        text = command_map.get(command, self.ANNOUNCEMENTS['processing'])
        self.speak(text, is_system=True)

    def announce_querying(self):
        """播报查询中提示"""
        self.speak(self.ANNOUNCEMENTS['querying'], is_system=True)

    def announce_processing(self):
        """播报处理中提示"""
        self.speak(self.ANNOUNCEMENTS['processing'], is_system=True)

    # ==================== 错误/提示语音反馈 ====================

    def announce_tool_not_found(self, tool_name: str = None):
        """播报工具未找到"""
        text = f'未找到工具"{tool_name}"，请检查工具名称' if tool_name else self.ANNOUNCEMENTS['tool_not_found']
        self.speak(text, is_system=True)

    def announce_category_not_found(self):
        """播报分类未找到"""
        self.speak(self.ANNOUNCEMENTS['category_not_found'], is_system=True)

    def announce_invalid_command(self):
        """播报无效命令"""
        self.speak(self.ANNOUNCEMENTS['invalid_command'], is_system=True)


# ==================== 便捷函数 ====================

_voice_assistant_instance = None


def get_voice_assistant(voice_interface=None) -> VoiceAssistant:
    """
    获取语音助手单例

    Args:
        voice_interface: VoiceInterface 实例

    Returns:
        VoiceAssistant 实例
    """
    global _voice_assistant_instance
    if _voice_assistant_instance is None:
        _voice_assistant_instance = VoiceAssistant(voice_interface)
    elif voice_interface is not None:
        _voice_assistant_instance.set_voice_interface(voice_interface)

    return _voice_assistant_instance


def set_voice_assistant_voice(voice_interface):
    """设置语音助手使用的语音接口"""
    assistant = get_voice_assistant()
    assistant.set_voice_interface(voice_interface)


# ==================== 快捷播报函数 ====================

def announce_l1_overview(from_layer: str = None, voice_interface=None):
    """快捷播报：进入 L1 概览层"""
    assistant = get_voice_assistant(voice_interface)
    assistant.announce_l1_overview(from_layer)


def announce_l2_manual(from_layer: str = None, voice_interface=None):
    """快捷播报：进入 L2 手册层"""
    assistant = get_voice_assistant(voice_interface)
    assistant.announce_l2_manual(from_layer)


def announce_l3_tool_detail(tool_name: str, from_layer: str = None, voice_interface=None):
    """快捷播报：进入 L3 工具详情层"""
    assistant = get_voice_assistant(voice_interface)
    assistant.announce_l3_tool_detail(tool_name, from_layer)


def announce_layer_switch(to_layer: str, from_layer: str = None, tool_name: str = None, voice_interface=None):
    """快捷播报：层级切换"""
    assistant = get_voice_assistant(voice_interface)
    assistant.announce_layer_switch(to_layer, from_layer, tool_name)


def announce_querying(voice_interface=None):
    """快捷播报：查询中"""
    assistant = get_voice_assistant(voice_interface)
    assistant.announce_querying()


def announce_navigation(command: str, voice_interface=None):
    """快捷播报：导航命令"""
    assistant = get_voice_assistant(voice_interface)
    assistant.announce_navigation(command)
