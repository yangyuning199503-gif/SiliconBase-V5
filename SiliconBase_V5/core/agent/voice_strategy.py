#!/usr/bin/env python3
"""
语音策略模块 - SiliconBase V5
【重构拆分】从 agent_loop.py 迁移

职责：管理AI语音播报的偏好设置和智能策略
- 用户播报偏好管理
- 智能播报决策（何时播报、播报什么）
- 防重复播报机制
"""

import random
import time

from core.logger import logger


class VoicePreferences:
    """用户语音播报偏好管理"""

    # 默认配置
    _DEFAULT_INTERVAL = 10  # 默认10秒间隔
    _DEFAULT_ENABLED = True  # 默认启用播报
    _DEFAULT_SMART_MODE = True  # 默认启用智能模式

    @staticmethod
    def get_announce_interval(user_id: str = "default") -> int:
        """获取用户播报间隔偏好，默认10秒"""
        try:
            from core.config import config
            user_config = config.get(f"voice.user_preferences.{user_id}", {})
            interval = user_config.get("announce_interval", VoicePreferences._DEFAULT_INTERVAL)
            return max(5, min(60, interval))
        except Exception as e:
            logger.error(f"[VoicePreferences] 获取播报间隔失败: {e}", exc_info=True)
            return VoicePreferences._DEFAULT_INTERVAL

    @staticmethod
    def is_announce_enabled(user_id: str = "default") -> bool:
        """用户是否启用播报"""
        try:
            from core.config import config
            user_config = config.get(f"voice.user_preferences.{user_id}", {})
            return user_config.get("announce_enabled", VoicePreferences._DEFAULT_ENABLED)
        except Exception as e:
            logger.error(f"[VoicePreferences] 获取播报启用状态失败: {e}", exc_info=True)
            return VoicePreferences._DEFAULT_ENABLED

    @staticmethod
    def is_smart_mode_enabled(user_id: str = "default") -> bool:
        """是否启用智能播报模式"""
        try:
            from core.config import config
            user_config = config.get(f"voice.user_preferences.{user_id}", {})
            return user_config.get("smart_mode", VoicePreferences._DEFAULT_SMART_MODE)
        except Exception as e:
            logger.error(f"[VoicePreferences] 获取智能模式失败: {e}", exc_info=True)
            return VoicePreferences._DEFAULT_SMART_MODE

    @staticmethod
    def get_memory_count_threshold(user_id: str = "default") -> int:
        """获取记忆数量变化阈值（超过此值才播报）"""
        try:
            from core.config import config
            user_config = config.get(f"voice.user_preferences.{user_id}", {})
            return user_config.get("memory_count_threshold", 5)
        except Exception as e:
            logger.error(f"[VoicePreferences] 获取记忆阈值失败: {e}", exc_info=True)
            return 5


class VoiceAnnounceStrategy:
    """语音播报智能策略 - 决定何时应该播报"""

    # 播报类型常量
    MEMORY_QUERY = "memory_query"
    TOOL_CALL = "tool_call"
    INTENT_CHANGE = "intent_change"
    LAYER_SWITCH = "layer_switch"
    THINKING = "thinking"

    # 类级别变量：跟踪各类型的上次播报时间（全局去重）
    _last_announcement_time: dict[str, float] = {}
    _MIN_ANNOUNCEMENT_INTERVAL = 5.0  # 5秒内不重复播报

    # 多样化的过程提示
    THINKING_VARIANTS = [
        "正在思考...",
        "让我想想...",
        "正在理解...",
        "稍等片刻...",
        "正在分析...",
        "让我思考一下..."
    ]

    MEMORY_QUERY_VARIANTS = [
        "正在查询记忆...",
        "正在回忆相关内容...",
        "让我找找之前的记录...",
        "正在检索记忆...",
        "正在查找相关信息..."
    ]

    @staticmethod
    def get_thinking_announcement() -> str:
        """获取多样化的思考提示"""
        return random.choice(VoiceAnnounceStrategy.THINKING_VARIANTS)

    @staticmethod
    def get_memory_query_announcement() -> str:
        """获取多样化的记忆查询提示"""
        return random.choice(VoiceAnnounceStrategy.MEMORY_QUERY_VARIANTS)

    @staticmethod
    def is_process_announce_enabled(announce_type: str) -> bool:
        """检查过程播报是否启用"""
        try:
            from core.config import config
            if not config.get("voice.announce.process.enabled", True):
                return False
            return config.get(f"voice.announce.process.{announce_type}", True)
        except Exception as e:
            logger.error(f"[VoiceAnnounce] 检查过程播报启用状态失败: {e}", exc_info=True)
            return True

    @staticmethod
    def get_process_priority() -> int:
        """获取过程播报的优先级"""
        try:
            from core.config import config
            return config.get("voice.announce.priority.process", 2)
        except Exception as e:
            logger.error(f"[VoiceAnnounce] 获取过程播报优先级失败: {e}", exc_info=True)
            return 2

    @staticmethod
    def is_interruptible() -> bool:
        """检查过程播报是否可被中断"""
        try:
            from core.config import config
            return config.get("voice.announce.priority.interruptible", True)
        except Exception as e:
            logger.error(f"[VoiceAnnounce] 检查播报可中断状态失败: {e}", exc_info=True)
            return True

    @staticmethod
    def should_announce_by_type(announcement_type: str) -> bool:
        """检查是否应该播报指定类型（全局去重）"""
        now = time.time()
        last_time = VoiceAnnounceStrategy._last_announcement_time.get(announcement_type, 0)
        if now - last_time < VoiceAnnounceStrategy._MIN_ANNOUNCEMENT_INTERVAL:
            logger.debug(f"[VoiceStrategy-Dedup] 跳过播报 '{announcement_type}'，距离上次仅 {now - last_time:.1f}秒")
            return False
        VoiceAnnounceStrategy._last_announcement_time[announcement_type] = now
        logger.debug(f"[VoiceStrategy-Dedup] 允许播报 '{announcement_type}'，已更新记录")
        return True

    _last_ai_output: str = ""

    @staticmethod
    def should_announce_ai_output(text: str) -> bool:
        """检查是否应该播报AI输出（避免重复播报相同内容）"""
        if not text or not text.strip():
            return False
        last_output = getattr(VoiceAnnounceStrategy, '_last_ai_output', '')
        if text.strip() == last_output:
            return False
        VoiceAnnounceStrategy._last_ai_output = text.strip()
        return True

    @staticmethod
    def should_announce(
        working_memory,
        voice_instance,
        context: dict,
        announce_type: str = MEMORY_QUERY
    ) -> bool:
        """
        判断是否应该播报

        策略:
        1. 首次查询: 播报
        2. 10秒内重复: 不播报（时间间隔控制）
        3. 不同意图: 播报（意图变化触发）
        4. 记忆数量变化大: 播报（数据变化触发）
        5. 层级切换: 播报（状态变化触发）
        """
        if not voice_instance:
            return False

        user_id = context.get("user_id", "default")

        if not VoicePreferences.is_announce_enabled(user_id):
            return False

        # 初始化工作记忆中的播报状态属性
        if not hasattr(working_memory, '_voice_state'):
            working_memory._voice_state = {
                '_last_memory_announce_time': 0,
                '_last_memory_count': 0,
                '_last_intent': '',
                '_last_announce_type': '',
                '_announce_count': 0,
                '_last_layer': '',
            }

        state = working_memory._voice_state
        current_time = time.time()

        interval = VoicePreferences.get_announce_interval(user_id)

        # 基础时间间隔检查
        time_since_last = current_time - state['_last_memory_announce_time']
        if time_since_last < interval:
            return VoiceAnnounceStrategy._check_important_changes(
                state, context, announce_type, user_id
            )

        # 时间间隔已过，检查是否有必要
        return not VoiceAnnounceStrategy._is_redundant_announce(state, context, announce_type)

    @staticmethod
    def _check_important_changes(state: dict, context: dict, announce_type: str, user_id: str) -> bool:
        """检查是否有重要变化需要突破时间间隔限制"""
        # 意图变化检查
        current_intent = context.get('intent', '')
        last_intent = state['_last_intent']
        if current_intent and current_intent != last_intent and last_intent != '':
            return True

        # 记忆数量显著变化检查
        memory_threshold = VoicePreferences.get_memory_count_threshold(user_id)
        current_count = context.get('memory_count', 0)
        last_count = state['_last_memory_count']
        if abs(current_count - last_count) > memory_threshold:
            return True

        # 层级切换检查
        current_layer = context.get('layer', '')
        last_layer = state['_last_layer']
        return bool(current_layer and current_layer != last_layer and last_layer != '')

    @staticmethod
    def _is_redundant_announce(state: dict, context: dict, announce_type: str) -> bool:
        """检查是否是重复冗余的播报"""
        if announce_type == state['_last_announce_type']:
            current_count = context.get('memory_count', 0)
            last_count = state['_last_memory_count']
            if abs(current_count - last_count) <= 2:
                return True
        return False

    @staticmethod
    def update_state(working_memory, context: dict, announce_type: str):
        """更新播报状态"""
        if not hasattr(working_memory, '_voice_state'):
            working_memory._voice_state = {
                '_last_memory_announce_time': 0,
                '_last_memory_count': 0,
                '_last_intent': '',
                '_last_announce_type': '',
                '_announce_count': 0,
                '_last_layer': '',
            }

        state = working_memory._voice_state
        state['_last_memory_announce_time'] = time.time()
        state['_last_memory_count'] = context.get('memory_count', 0)
        state['_last_intent'] = context.get('intent', '')
        state['_last_announce_type'] = announce_type
        state['_last_layer'] = context.get('layer', '')
        state['_announce_count'] += 1


def generate_announce_message(context: dict) -> str:
    """
    根据上下文动态生成播报内容

    Args:
        context: 上下文信息，包含:
            - memory_count: 记忆数量
            - intent: 当前意图
            - layer: 当前层级
            - is_first_query: 是否首次查询

    Returns:
        str: 播报消息
    """
    memory_count = context.get('memory_count', 0)
    is_first_query = context.get('is_first_query', False)

    # 首次查询的特殊处理
    if is_first_query:
        if memory_count == 0:
            return "正在启动查询..."
        first_query_variants = [
            "正在查询记忆，请稍候...",
            "让我找找之前的记录...",
            "正在回忆相关内容..."
        ]
        return random.choice(first_query_variants)

    # 根据记忆数量生成不同消息
    if memory_count == 0:
        zero_memory_variants = [
            "正在查询记忆...",
            "正在检索相关信息...",
            "让我查一下..."
        ]
        return random.choice(zero_memory_variants)
    elif memory_count < 3:
        return f"找到{memory_count}条相关记忆，请稍候..."
    elif memory_count < 10:
        return f"正在从{memory_count}条记忆中检索相关信息..."
    else:
        return f"发现大量记忆({memory_count}条)，正在筛选..."


def announce_with_strategy(
    voice_instance,
    working_memory,
    announce_type: str = VoiceAnnounceStrategy.MEMORY_QUERY,
    **context_kwargs
) -> bool:
    """
    使用智能策略进行语音播报

    Args:
        voice_instance: 语音实例
        working_memory: 工作记忆
        announce_type: 播报类型
        **context_kwargs: 额外的上下文信息

    Returns:
        bool: 是否成功播报
    """
    if not voice_instance:
        return False

    # 检查过程播报配置开关
    if announce_type == VoiceAnnounceStrategy.MEMORY_QUERY and not VoiceAnnounceStrategy.is_process_announce_enabled("memory_query"):
        logger.debug("[VoiceStrategy] 记忆查询播报已禁用，跳过")
        return False

    # 构建上下文
    context = {
        'memory_count': context_kwargs.get('memory_count', 0),
        'intent': context_kwargs.get('intent', ''),
        'layer': context_kwargs.get('layer', ''),
        'user_id': context_kwargs.get('user_id', 'default'),
        'is_first_query': context_kwargs.get('is_first_query', False),
    }

    # 检查是否应该播报
    if not VoiceAnnounceStrategy.should_announce(working_memory, voice_instance, context, announce_type):
        return False

    # 全局去重检查
    if not VoiceAnnounceStrategy.should_announce_by_type(announce_type):
        return False

    try:
        message = generate_announce_message(context)

        # 检查是否可中断
        interruptible = VoiceAnnounceStrategy.is_interruptible()
        voice_instance.speak(message, is_system=True, wait=False, protected=not interruptible)

        # 更新状态
        VoiceAnnounceStrategy.update_state(working_memory, context, announce_type)

        logger.debug(f"[VoiceStrategy] 播报成功: {message} (interruptible={interruptible})")
        return True

    except Exception as e:
        logger.warning(f"[VoiceStrategy] 播报失败: {e}")
        return False


def speak_ai_reply(text: str, voice_instance=None, max_length: int = 100) -> bool:
    """
    播报AI回复（清理并截断）

    Args:
        text: 要播报的文本
        voice_instance: 语音实例
        max_length: 最大播报长度

    Returns:
        bool: 是否成功播报
    """
    if not voice_instance or not text:
        return False

    # 清理文本
    cleaned = text.strip()
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length] + "..."

    try:
        voice_instance.speak(cleaned, is_system=False, wait=False)
        return True
    except Exception as e:
        logger.warning(f"[VoiceStrategy] 播报AI回复失败: {e}")
        return False


# 向后兼容导出
__all__ = [
    'VoicePreferences',
    'VoiceAnnounceStrategy',
    'generate_announce_message',
    'announce_with_strategy',
    'speak_ai_reply',
]
