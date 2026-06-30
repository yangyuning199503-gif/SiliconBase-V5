#!/usr/bin/env python3
"""
AI生命感管理器 - SiliconBase V5 用户体验核心
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

功能：
  ✓ 沉默模式 - 只在关键时刻播报
  ✓ 状态可视化 - 思考/执行/等待状态
  ✓ 智能播报过滤
  ✓ 用户可配置的通知级别

核心理念：
  让AI表现得更有"生命感"，不是机械地执行，而是有节奏、有重点地交互

作者: SiliconBase Team
版本: 1.0.0
"""

import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class AIState(Enum):
    """AI状态枚举"""
    IDLE = "idle"           # 空闲
    THINKING = "thinking"   # 思考中
    EXECUTING = "executing" # 执行中
    WAITING = "waiting"     # 等待中（用户输入/外部资源）
    ERROR = "error"         # 出错
    COMPLETED = "completed" # 完成


class NotificationLevel(Enum):
    """通知级别"""
    SILENT = "silent"       # 完全静默
    MINIMAL = "minimal"     # 最小播报
    NORMAL = "normal"       # 正常播报
    VERBOSE = "verbose"     # 详细播报


class EventType(Enum):
    """事件类型"""
    TASK_START = "task_start"
    TASK_COMPLETE = "task_complete"
    TOOL_CALL = "tool_call"
    TOOL_SUCCESS = "tool_success"
    TOOL_ERROR = "tool_error"
    MILESTONE = "milestone"
    PROGRESS = "progress"
    USER_INPUT_NEEDED = "user_input_needed"
    ERROR = "error"
    THINKING_START = "thinking_start"
    THINKING_END = "thinking_end"
    CHECKPOINT_SAVED = "checkpoint_saved"
    RECOVERY = "recovery"


@dataclass
class StatusIndicator:
    """状态指示器"""
    state: AIState
    current_action: str
    progress: float | None = None
    estimated_remaining: int | None = None  # 秒
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'state': self.state.value,
            'current_action': self.current_action,
            'progress': self.progress,
            'estimated_remaining': self.estimated_remaining,
            'details': self.details
        }


@dataclass
class AnnounceEvent:
    """播报事件"""
    event_type: EventType
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class LifePresenceConfig:
    """生命感配置"""

    # 各级别的播报策略
    NOTIFICATION_CONFIG = {
        NotificationLevel.SILENT: {
            'always_speak': [EventType.ERROR, EventType.USER_INPUT_NEEDED],
            'show_indicator': True,
            'description': '完全静默，只在错误和需要用户时播报'
        },
        NotificationLevel.MINIMAL: {
            'always_speak': [EventType.TASK_START, EventType.TASK_COMPLETE,
                           EventType.ERROR, EventType.USER_INPUT_NEEDED],
            'show_indicator': True,
            'description': '最小播报，只在任务起止和错误时播报'
        },
        NotificationLevel.NORMAL: {
            'always_speak': [EventType.TASK_START, EventType.TASK_COMPLETE,
                           EventType.MILESTONE, EventType.ERROR,
                           EventType.USER_INPUT_NEEDED],
            'show_indicator': True,
            'cooldown_seconds': 30,  # 同类事件冷却时间
            'description': '正常播报，包含里程碑'
        },
        NotificationLevel.VERBOSE: {
            'always_speak': 'all',  # 所有事件都播报
            'show_indicator': True,
            'description': '详细播报，所有操作都播报'
        }
    }

    # 重要工具列表（这些工具的执行会播报）
    IMPORTANT_TOOLS = [
        'file_manager', 'web_automation', 'process_start',
        'clipboard', 'memory_add', 'delete_user_data'
    ]

    # 里程碑进度点
    MILESTONE_PROGRESS = [25, 50, 75, 90, 100]


class SmartAnnouncer:
    """
    智能播报器

    智能判断是否播报，避免信息过载
    """

    def __init__(self, level: NotificationLevel = NotificationLevel.NORMAL):
        self.level = level
        self.recent_announcements: deque = deque(maxlen=20)
        self.last_announcement_time: dict[EventType, float] = {}
        self.config = LifePresenceConfig.NOTIFICATION_CONFIG[level]

    def should_announce(self, event: AnnounceEvent) -> bool:
        """判断是否应当播报"""
        config = self.config

        # 1. 检查是否总是播报
        always_speak = config.get('always_speak', [])
        if always_speak == 'all':
            return True
        if event.event_type in always_speak:
            return True

        # 2. 检查冷却时间
        cooldown = config.get('cooldown_seconds', 0)
        if cooldown > 0:
            last_time = self.last_announcement_time.get(event.event_type, 0)
            if time.time() - last_time < cooldown:
                return False

        # 3. 智能判断
        if not self._is_important_enough(event):
            return False

        # 4. 检查重复
        return not self._is_duplicate(event)

    def _get_emotional_state(self) -> dict[str, Any]:
        """【生命化接入】读取 AI 当前情绪状态"""
        try:
            from core.consciousness.Consciousness import get_consciousness
            consciousness = get_consciousness()
            if consciousness:
                return consciousness.get_life_state()
        except Exception:
            pass
        return {"energy": 0.5, "mood": "平静", "stress": 0.0, "curiosity": 0.5}

    def _is_important_enough(self, event: AnnounceEvent) -> bool:
        """判断事件是否足够重要（带情绪感知）"""
        event_type = event.event_type
        data = event.data

        # 【生命化接入】读取情绪状态，动态调整播报门槛
        emotional = self._get_emotional_state()
        energy = emotional.get("energy", 0.5)
        mood = emotional.get("mood", "平静")

        # 情绪调节因子：高能量/兴奋 → 门槛降低（多播报）；低能量/疲惫 → 门槛提高（少播报）
        mood_boost = 0.0
        if mood in ("兴奋", "开心", "积极"):
            mood_boost = 0.2
        elif mood in ("疲惫", "低落", "消极"):
            mood_boost = -0.3

        # 工具调用：只播报重要工具或失败
        if event_type == EventType.TOOL_CALL:
            tool_name = data.get('tool_name', '')
            success = data.get('success', True)

            # 失败总是播报
            if not success:
                return True

            # 情绪低时，连重要工具都可能不播报
            if energy + mood_boost < 0.3:
                return False

            # 重要工具播报；普通工具不播报
            return tool_name in LifePresenceConfig.IMPORTANT_TOOLS

        # 进度更新：只在里程碑播报（情绪影响里程碑敏感度）
        if event_type == EventType.PROGRESS:
            progress = data.get('progress', 0)
            # 情绪高涨时，25% 也报；情绪低落时，只报 75%/100%
            if energy + mood_boost < 0.3:
                return progress in [75, 90, 100]
            return progress in LifePresenceConfig.MILESTONE_PROGRESS

        # 思考状态：只播报开始和结束
        if event_type in [EventType.THINKING_START, EventType.THINKING_END]:
            return self.level == NotificationLevel.VERBOSE

        # 默认：情绪极低时，只有强制事件才播报
        return not (energy + mood_boost < 0.2 and event_type not in (EventType.ERROR, EventType.USER_INPUT_NEEDED, EventType.RECOVERY))

    def _is_duplicate(self, event: AnnounceEvent) -> bool:
        """检查是否重复"""
        for recent in self.recent_announcements:
            if (recent.event_type == event.event_type and
                recent.message == event.message):
                return True
        return False

    def record_announcement(self, event: AnnounceEvent):
        """记录播报"""
        self.recent_announcements.append(event)
        self.last_announcement_time[event.event_type] = time.time()


class LifePresenceManager:
    """
    AI生命感管理器

    让AI表现得更有"生命":
    - 状态可视化（前端可显示）
    - 智能播报（只在关键时刻）
    - 沉默模式可选
    """

    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, default_level: NotificationLevel = NotificationLevel.NORMAL):
        if LifePresenceManager._initialized:
            return

        self.default_level = default_level
        self.announcer = SmartAnnouncer(default_level)

        # 当前状态
        self.current_state = AIState.IDLE
        self.current_action = ""
        self.current_progress = 0.0
        self.estimated_remaining = None

        # 状态监听回调
        self._state_listeners: list[Callable] = []

        # 统计
        self._stats = {
            'state_changes': 0,
            'announcements': 0,
            'suppressed': 0
        }

        LifePresenceManager._initialized = True
        logger.info("[LifePresenceManager] 初始化完成")

    def update_state(self, state: AIState, action: str = "",
                     progress: float = None, details: dict = None):
        """
        更新AI状态

        在Agent Loop中状态变化时调用
        """
        old_state = self.current_state
        self.current_state = state
        self.current_action = action

        if progress is not None:
            self.current_progress = progress

        self._stats['state_changes'] += 1

        # 通知监听者
        for listener in self._state_listeners:
            try:
                listener(old_state, state, action)
            except Exception as e:
                logger.error(f"状态监听回调失败: {e}")

        logger.debug(f"[LifePresence] 状态变化: {old_state.value} -> {state.value}, 动作: {action}")

    def announce(self, event_type: EventType, message: str,
                 data: dict = None, force: bool = False) -> bool:
        """
        播报消息

        Args:
            event_type: 事件类型
            message: 播报内容
            data: 附加数据
            force: 是否强制播报（忽略级别）

        Returns:
            是否实际播报了
        """
        event = AnnounceEvent(event_type, message, data or {})

        if not force and not self.announcer.should_announce(event):
            self._stats['suppressed'] += 1
            return False

        # 实际播报（通过语音接口）
        announced_ok = self._do_announce(message)
        if not announced_ok:
            return False

        self.announcer.record_announcement(event)
        self._stats['announcements'] += 1

        return True

    def _do_announce(self, message: str) -> bool:
        """执行播报，返回是否真正播报成功"""
        try:
            from voice import get_voice_interface
            voice = get_voice_interface()
            if voice and hasattr(voice, "speak"):
                voice.speak(message, priority=2)  # 优先级2（中等）
                return True
        except Exception as e:
            logger.debug(f"[LifePresence] 语音播报失败: {e}")
        # 语音不可用，只记录日志
        logger.info(f"[播报] {message}")
        return False

    def get_status_indicator(self) -> StatusIndicator:
        """获取当前状态指示器（供前端使用）"""
        return StatusIndicator(
            state=self.current_state,
            current_action=self.current_action,
            progress=self.current_progress if self.current_progress > 0 else None,
            estimated_remaining=self.estimated_remaining,
            details={
                'level': self.default_level.value,
                'announcements': self._stats['announcements'],
                'suppressed': self._stats['suppressed']
            }
        )

    def set_notification_level(self, level: NotificationLevel):
        """设置通知级别"""
        self.default_level = level
        self.announcer = SmartAnnouncer(level)
        logger.info(f"[LifePresence] 通知级别设置为: {level.value}")

    def add_state_listener(self, listener: Callable):
        """添加状态监听回调"""
        self._state_listeners.append(listener)

    def remove_state_listener(self, listener: Callable):
        """移除状态监听回调"""
        if listener in self._state_listeners:
            self._state_listeners.remove(listener)

    # ═══════════════════════════════════════════════════════════
    # 便捷方法
    # ═══════════════════════════════════════════════════════════

    def on_task_start(self, task_name: str):
        """任务开始"""
        self.update_state(AIState.THINKING, f"开始任务: {task_name}")
        self.announce(EventType.TASK_START, f"开始执行任务: {task_name}")

    def on_task_complete(self, task_name: str, success: bool = True):
        """任务完成"""
        self.update_state(AIState.COMPLETED, f"任务完成: {task_name}")
        status = "成功" if success else "失败"
        self.announce(EventType.TASK_COMPLETE, f"任务{status}: {task_name}")

    def on_tool_call(self, tool_name: str, params: dict = None):
        """工具调用"""
        self.update_state(AIState.EXECUTING, f"调用工具: {tool_name}")
        self.announce(EventType.TOOL_CALL, f"正在执行: {tool_name}",
                     data={'tool_name': tool_name, 'params': params})

    def on_tool_result(self, tool_name: str, success: bool, result: str = ""):
        """工具执行结果"""
        if success:
            self.announce(EventType.TOOL_SUCCESS, f"{tool_name}执行成功",
                         data={'tool_name': tool_name, 'success': True})
        else:
            self.announce(EventType.TOOL_ERROR, f"{tool_name}执行失败: {result}",
                         data={'tool_name': tool_name, 'success': False, 'error': result})

    def on_milestone(self, description: str, progress: int):
        """里程碑"""
        self.current_progress = progress
        self.announce(EventType.MILESTONE, f"达成里程碑: {description}",
                     data={'progress': progress, 'description': description})

    def on_error(self, error_message: str, critical: bool = False):
        """发生错误"""
        self.update_state(AIState.ERROR, f"错误: {error_message}")

        if critical:
            self.announce(EventType.ERROR, f"发生严重错误: {error_message}",
                         data={'error': error_message, 'critical': True}, force=True)
        else:
            self.announce(EventType.ERROR, f"发生错误: {error_message}",
                         data={'error': error_message})

    def on_user_input_needed(self, prompt: str):
        """需要用户输入"""
        self.update_state(AIState.WAITING, f"等待用户: {prompt}")
        self.announce(EventType.USER_INPUT_NEEDED, f"需要您的输入: {prompt}", force=True)

    def on_thinking(self, topic: str = ""):
        """开始思考"""
        self.update_state(AIState.THINKING, f"思考中: {topic}")
        # 思考开始通常不播报，除非是详细模式
        self.announce(EventType.THINKING_START, "正在思考...")

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return self._stats.copy()


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

_presence_manager: LifePresenceManager | None = None

def get_life_presence_manager() -> LifePresenceManager:
    """获取全局管理器实例"""
    global _presence_manager
    if _presence_manager is None:
        _presence_manager = LifePresenceManager()
    return _presence_manager


def announce(message: str, event_type: EventType = EventType.MILESTONE,
             force: bool = False) -> bool:
    """便捷函数：播报消息"""
    return get_life_presence_manager().announce(event_type, message, force=force)


def update_ai_state(state: AIState, action: str = "", progress: float = None):
    """便捷函数：更新AI状态"""
    get_life_presence_manager().update_state(state, action, progress)


def get_ai_status() -> StatusIndicator:
    """便捷函数：获取AI状态"""
    return get_life_presence_manager().get_status_indicator()
