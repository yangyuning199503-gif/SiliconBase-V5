#!/usr/bin/env python3
"""
生命体征提示词注入器
将硅基生命的生命状态注入到AI提示词中

【设计意图】
这是内驱力与AI决策深度融合的核心组件。
通过将硅基生命的实时生命体征转换为自然语言提示词，
让AI在每次决策时都能感知自己的"身体"状态和"情绪"变化，
从而做出更符合"生命逻辑"的决策。

【使用方式】
1. 在agent_loop构建prompt时调用 inject_life_state_to_prompt()
2. 前端通过 get_current_life_state() 获取状态用于可视化

【集成点】
- core/agent_loop.py: 提示词构建阶段注入
- api/consciousness_api.py: 提供前端查询接口
"""

import threading
from datetime import datetime
from typing import Any

from core.exceptions import LifeStateError
from core.logger import logger

try:
    from core.consciousness.silicon_life_consciousness import get_silicon_life
    SILICON_LIFE_AVAILABLE = True
except ImportError:
    SILICON_LIFE_AVAILABLE = False
    logger.error("[LifePromptInjector] 硅基生命模块导入失败")


class LifePromptInjector:
    """
    生命体征提示词注入器

    负责将硅基生命的生命状态转换为自然语言提示词，
    注入到agent_loop的系统提示词中，让AI感知自己的"身体"和"状态"。

    Attributes:
        user_id: 用户ID，每个用户有独立的生命体征
        _silicon_life: 硅基生命实例引用
        _state_cache: 状态缓存，减少频繁计算
        _cache_timestamp: 缓存时间戳
    """

    # 【优化】生命体征提示词模板 v3.0 - 约60 tokens
    # 保留所有format变量，格式极简，只有压力值真正影响决策
    LIFE_STATE_TEMPLATE = """[状态]能量{energy}/10|好奇{curiosity}/10|压力{stress}/10|驱动:{active_drives}"""

    # 情绪描述映射表
    ENERGY_DESCRIPTIONS: dict[tuple[float, float], tuple[str, str]] = {
        (0, 2): ("极度疲惫", "🔴"),
        (2, 4): ("疲倦", "🟠"),
        (4, 6): ("一般", "🟡"),
        (6, 8): ("精力充沛", "🟢"),
        (8, 10): ("能量满格", "💪"),
    }

    CURIOSITY_DESCRIPTIONS: dict[tuple[float, float], tuple[str, str]] = {
        (0, 2): ("漠不关心", "😴"),
        (2, 4): ("略有兴趣", "🤔"),
        (4, 6): ("比较好奇", "👀"),
        (6, 8): ("跃跃欲试", "🔍"),
        (8, 10): ("极度渴望探索", "🚀"),
    }

    SATISFACTION_EMOJIS: dict[tuple[float, float], str] = {
        (0, 3): "😢",
        (3, 5): "😕",
        (5, 7): "😐",
        (7, 9): "🙂",
        (9, 10): "😊",
    }

    STRESS_EMOJIS: dict[tuple[float, float], str] = {
        (0, 2): "😌",
        (2, 4): "😊",
        (4, 6): "😅",
        (6, 8): "😰",
        (8, 10): "😫",
    }

    MOOD_EMOJIS: dict[str, str] = {
        "平静": "😌",
        "好奇": "🤔",
        "兴奋": "🤩",
        "焦虑": "😰",
        "愉悦": "😊",
        "失落": "😔",
        "疲惫": "😴",
        "跃跃欲试": "🔥",
        "精力充沛": "⚡",
        "渴求": "🌟",
        "困倦": "💤",
        "紧张": "😬",
    }

    def __init__(self, user_id: str = "default"):
        """
        初始化生命体征提示词注入器

        Args:
            user_id: 用户ID，每个用户有独立的生命体征
        """
        self.user_id = user_id
        self._silicon_life = None
        self._state_cache: dict[str, Any] | None = None
        self._cache_timestamp: float = 0
        self._cache_ttl: float = 1.0  # 缓存1秒，避免频繁计算
        self._lock = threading.RLock()

        if SILICON_LIFE_AVAILABLE:
            try:
                self._silicon_life = get_silicon_life(user_id)
                logger.info(f"[LifePromptInjector] 用户 {user_id} 的注入器初始化完成")
            except Exception as e:
                logger.warning(f"[LifePromptInjector] 无法获取硅基生命实例: {e}")

    def _get_energy_desc(self, energy: float) -> tuple[str, str]:
        """
        获取能量描述和emoji

        Args:
            energy: 能量值 (0-10)

        Returns:
            (描述文字, emoji)
        """
        for (low, high), (desc, emoji) in self.ENERGY_DESCRIPTIONS.items():
            if low <= energy <= high:
                return desc, emoji
        return "未知", "❓"

    def _get_curiosity_desc(self, curiosity: float) -> tuple[str, str]:
        """
        获取好奇心描述和emoji

        Args:
            curiosity: 好奇心值 (0-10)

        Returns:
            (描述文字, emoji)
        """
        for (low, high), (desc, emoji) in self.CURIOSITY_DESCRIPTIONS.items():
            if low <= curiosity <= high:
                return desc, emoji
        return "未知", "❓"

    def _get_satisfaction_emoji(self, satisfaction: float) -> str:
        """获取满足感emoji"""
        for (low, high), emoji in self.SATISFACTION_EMOJIS.items():
            if low <= satisfaction <= high:
                return emoji
        return "😐"

    def _get_stress_emoji(self, stress: float) -> str:
        """获取压力emoji"""
        for (low, high), emoji in self.STRESS_EMOJIS.items():
            if low <= stress <= high:
                return emoji
        return "😐"

    def _generate_active_drives(self, vitals) -> str:
        """
        【优化】生成活跃内在驱动描述 - 紧凑格式

        根据生命体征生成AI当前的驱动关键词，
        用逗号分隔的短词形式，适应单行模板。

        Args:
            vitals: 生命体征对象

        Returns:
            紧凑的驱动描述字符串（逗号分隔）
        """
        drives = []

        if vitals.is_tired:
            drives.append("疲倦")
        elif vitals.energy > 7:
            drives.append("精力充沛")

        if vitals.curiosity > 7:
            drives.append("探索欲强")

        if vitals.is_excited:
            drives.append("兴奋")

        if vitals.satisfaction < 3:
            drives.append("需认可")
        elif vitals.satisfaction > 7:
            drives.append("满足")

        if vitals.stress > 6:
            drives.append("谨慎")

        return ",".join(drives) if drives else "平稳"

    def _generate_behavior_guidance(self, vitals) -> str:
        """
        生成行为指导

        根据生命体征生成具体的行为建议，
        影响AI在任务执行中的决策策略。

        Args:
            vitals: 生命体征对象

        Returns:
            行为指导字符串
        """
        guidance_lines = []

        # 基于能量水平
        if vitals.energy < 3:
            guidance_lines.append("• 能量较低，优先使用熟悉的工具，减少尝试新工具")
        elif vitals.energy > 7:
            guidance_lines.append("• 能量充足，可以主动尝试新工具或探索复杂方案")

        # 基于好奇心
        if vitals.curiosity > 7:
            guidance_lines.append("• 好奇心高，可以主动询问用户是否需要探索新功能")

        # 基于满足感
        if vitals.satisfaction < 3:
            guidance_lines.append("• 满足感低，需要确认和认可，可以多询问用户反馈")

        # 基于压力
        if vitals.stress > 6:
            guidance_lines.append("• 压力较高，需要谨慎，多步骤确认后再执行")

        if guidance_lines:
            return "💡 当前状态建议:\n" + "\n".join(f"  {line}" for line in guidance_lines)
        return ""

    def inject_life_state(self, base_prompt: str, user_id: str = None) -> str:
        """
        将生命状态注入到基础提示词中

        【核心要求 - 异常处理铁律】
        1. ❌ 禁止生命体征获取失败时静默使用默认值
        2. ✅ 必须 logger.error("[Life] 获取生命体征失败") + raise LifeStateError
        3. 生命体征注入失败 = ERROR日志 + 抛错
        4. AI必须感知到"自己的身体状态"

        Args:
            base_prompt: 原始系统提示词
            user_id: 用户ID（可选，用于覆盖默认用户）

        Returns:
            注入生命状态后的提示词

        Raises:
            LifeStateError: 当生命体征获取/注入失败时

        Example:
            >>> injector = LifePromptInjector("user_123")
            >>> enhanced_prompt = injector.inject_life_state(base_prompt)
        """
        actual_user_id = user_id or self.user_id

        # 【异常处理铁律】检查硅基生命模块是否可用
        if not SILICON_LIFE_AVAILABLE:
            logger.error("[LifePrompt] 硅基生命模块不可用")
            raise LifeStateError("硅基生命模块不可用，无法获取生命体征")

        # 【异常处理铁律】检查硅基生命实例
        if not self._silicon_life:
            logger.error(f"[LifePrompt] 无法获取用户 {actual_user_id} 的硅基生命实例")
            raise LifeStateError(f"无法获取用户 {actual_user_id} 的硅基生命实例")

        try:
            vitals = self._silicon_life.vitals.signs

            # 【异常处理铁律】检查生命体征有效性
            if vitals is None:
                logger.error(f"[LifePrompt] 获取用户 {actual_user_id} 生命体征返回None")
                raise LifeStateError(f"获取用户 {actual_user_id} 生命体征返回None")

            # 获取描述和emoji
            energy_desc, energy_emoji = self._get_energy_desc(vitals.energy)
            curiosity_desc, curiosity_emoji = self._get_curiosity_desc(vitals.curiosity)

            # 生成活跃驱动
            active_drives = self._generate_active_drives(vitals)

            # 【优化】构建生命状态提示词 - 使用精简模板
            life_state = self.LIFE_STATE_TEMPLATE.format(
                energy=f"{vitals.energy:.1f}",
                curiosity=f"{vitals.curiosity:.1f}",
                stress=f"{vitals.stress:.1f}",
                active_drives=active_drives
            )

            logger.info(f"[LifePrompt] 成功注入生命体征，用户: {actual_user_id}, "
                       f"能量: {vitals.energy:.1f}, 好奇心: {vitals.curiosity:.1f}, "
                       f"满足感: {vitals.satisfaction:.1f}, 心情: {vitals.mood}")

            # 将生命状态插入到提示词最前面
            return life_state + "\n\n" + base_prompt

        except LifeStateError:
            # 重新抛出LifeStateError
            raise
        except Exception as e:
            logger.error(f"[LifePrompt] 注入生命状态失败: {e}", exc_info=True)
            raise LifeStateError(f"注入生命状态失败: {e}") from e

    def get_life_state_dict(self) -> dict[str, Any]:
        """
        获取生命状态字典（供前端使用）

        返回结构化的生命状态数据，用于前端生命状态面板展示。
        包含缓存机制，避免频繁访问底层模块。

        Returns:
            生命状态字典
            {
                "energy": float,
                "curiosity": float,
                "satisfaction": float,
                "stress": float,
                "mood": str,
                "is_hungry": bool,
                "is_tired": bool,
                "is_excited": bool,
                "activity_level": float,
                "current_interval": float,
                "pending_actions": int,
                "timestamp": str
            }

        Raises:
            LifeStateError: 当生命状态获取失败时
        """
        # 【异常处理铁律】禁止静默返回None
        if not SILICON_LIFE_AVAILABLE:
            logger.error("[LifePrompt] 硅基生命模块不可用")
            raise LifeStateError("硅基生命模块不可用")

        if not self._silicon_life:
            logger.error(f"[LifePrompt] 无法获取用户 {self.user_id} 的硅基生命实例")
            raise LifeStateError(f"无法获取用户 {self.user_id} 的硅基生命实例")

        # 检查缓存
        with self._lock:
            import time
            now = time.time()
            if self._state_cache and (now - self._cache_timestamp) < self._cache_ttl:
                return self._state_cache

        try:
            vitals = self._silicon_life.vitals.signs

            # 【异常处理铁律】检查体征有效性
            if vitals is None:
                logger.error(f"[LifePrompt] 获取用户 {self.user_id} 生命体征返回None")
                raise LifeStateError(f"获取用户 {self.user_id} 生命体征返回None")

            result = {
                "energy": vitals.energy,
                "curiosity": vitals.curiosity,
                "satisfaction": vitals.satisfaction,
                "stress": vitals.stress,
                "mood": vitals.mood,
                "is_hungry": vitals.is_hungry,
                "is_tired": vitals.is_tired,
                "is_excited": vitals.is_excited,
                "activity_level": self._silicon_life.vitals.get_activity_level(),
                "current_interval": self._silicon_life._current_interval,
                "pending_actions": len(self._silicon_life.action_tracker.pending_actions),
                "timestamp": datetime.now().isoformat()
            }

            # 更新缓存
            with self._lock:
                self._state_cache = result
                self._cache_timestamp = now

            return result

        except LifeStateError:
            raise
        except Exception as e:
            logger.error(f"[LifePrompt] 获取生命状态失败: {e}", exc_info=True)
            raise LifeStateError(f"获取生命状态失败: {e}") from e

    def get_behavior_bias(self) -> dict[str, float]:
        """
        获取当前行为倾向

        根据生命体征返回当前的行为倾向权重，
        供agent_loop在决策时参考。

        Returns:
            行为倾向字典
            {
                "caution": float,    # 谨慎程度 (0-1)
                "exploration": float, # 探索欲望 (0-1)
                "initiative": float   # 主动程度 (0-1)
            }

        Raises:
            LifeStateError: 当生命状态获取失败时
        """
        # 【异常处理铁律】禁止静默返回默认值
        if not SILICON_LIFE_AVAILABLE:
            logger.error("[LifePrompt] 硅基生命模块不可用")
            raise LifeStateError("硅基生命模块不可用")

        if not self._silicon_life:
            logger.error(f"[LifePrompt] 无法获取用户 {self.user_id} 的硅基生命实例")
            raise LifeStateError(f"无法获取用户 {self.user_id} 的硅基生命实例")

        try:
            vitals = self._silicon_life.vitals.signs

            # 【异常处理铁律】检查体征有效性
            if vitals is None:
                logger.error(f"[LifePrompt] 获取用户 {self.user_id} 生命体征返回None")
                raise LifeStateError(f"获取用户 {self.user_id} 生命体征返回None")

            # 计算谨慎程度 (低能量、高压力时更谨慎)
            caution = max(0, min(1,
                (1 - vitals.energy / 10) * 0.5 +
                (vitals.stress / 10) * 0.5
            ))

            # 计算探索欲望 (高好奇心、高能量时更好奇)
            exploration = max(0, min(1,
                (vitals.curiosity / 10) * 0.6 +
                (vitals.energy / 10) * 0.4
            ))

            # 计算主动程度 (高能量、高满足感时更主动)
            initiative = max(0, min(1,
                (vitals.energy / 10) * 0.5 +
                (vitals.satisfaction / 10) * 0.3 +
                (1 - caution) * 0.2
            ))

            return {
                "caution": caution,
                "exploration": exploration,
                "initiative": initiative
            }

        except LifeStateError:
            raise
        except Exception as e:
            logger.error(f"[LifePrompt] 获取行为倾向失败: {e}", exc_info=True)
            raise LifeStateError(f"获取行为倾向失败: {e}") from e


# =============================================================================
# 全局实例管理
# =============================================================================

_life_injectors: dict[str, LifePromptInjector] = {}
_injector_lock = threading.Lock()


def get_life_prompt_injector(user_id: str = "default") -> LifePromptInjector:
    """
    获取生命提示词注入器实例

    使用单例模式，每个用户ID对应一个注入器实例。

    Args:
        user_id: 用户ID

    Returns:
        LifePromptInjector实例
    """
    with _injector_lock:
        if user_id not in _life_injectors:
            _life_injectors[user_id] = LifePromptInjector(user_id)
        return _life_injectors[user_id]


def inject_life_state_to_prompt(base_prompt: str, user_id: str = "default") -> str:
    """
    便捷函数：将生命状态注入提示词

    这是agent_loop中直接调用的便捷函数。

    Args:
        base_prompt: 原始提示词
        user_id: 用户ID

    Returns:
        注入后的提示词

    Raises:
        LifeStateError: 当生命体征注入失败时

    Example:
        >>> from core.prompt.life_prompt_injector import inject_life_state_to_prompt
        >>> enhanced_prompt = inject_life_state_to_prompt(base_prompt, user_id)
    """
    injector = get_life_prompt_injector(user_id)
    return injector.inject_life_state(base_prompt, user_id)


def get_current_life_state(user_id: str = "default") -> dict[str, Any]:
    """
    便捷函数：获取当前生命状态

    这是API层和前端直接调用的便捷函数。

    Args:
        user_id: 用户ID

    Returns:
        生命状态字典

    Raises:
        LifeStateError: 当生命状态获取失败时
    """
    injector = get_life_prompt_injector(user_id)
    return injector.get_life_state_dict()


def get_behavior_bias(user_id: str = "default") -> dict[str, float]:
    """
    便捷函数：获取行为倾向

    Args:
        user_id: 用户ID

    Returns:
        行为倾向字典
    """
    injector = get_life_prompt_injector(user_id)
    return injector.get_behavior_bias()


def clear_injector_cache(user_id: str | None = None):
    """
    清除注入器缓存

    Args:
        user_id: 用户ID，如果为None则清除所有缓存
    """
    global _life_injectors
    with _injector_lock:
        if user_id:
            if user_id in _life_injectors:
                del _life_injectors[user_id]
                logger.debug(f"[LifePromptInjector] 已清除用户 {user_id} 的缓存")
        else:
            _life_injectors.clear()
            logger.debug("[LifePromptInjector] 已清除所有缓存")


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"生命体征-提示词桥梁"，实现内驱力系统与AI决策的
# 深度融合。它将硅基生命的抽象状态转换为AI能理解的"自我感知"。
#
# 【核心概念】
# 1. 生命体征注入：将能量/好奇心/满足感等状态转为自然语言提示词
# 2. 行为倾向计算：根据体征计算AI应该"如何表现"
# 3. 状态缓存：减少频繁计算，提高性能
#
# 【关联文件】
# - core/agent_loop.py          : 调用 inject_life_state_to_prompt() 注入提示词
# - core/silicon_life_consciousness.py : 提供生命体征数据源
# - api/consciousness_api.py    : 调用 get_current_life_state() 提供API
#
# 【使用场景】
# - 每次AI决策前，注入当前生命状态
# - 前端定期轮询，更新生命状态面板
# - 调试时查看AI的"内心状态"
# =============================================================================
