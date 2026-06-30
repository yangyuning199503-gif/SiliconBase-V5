#!/usr/bin/env python3
"""
情绪行为适配器
根据生命体征调整AI行为策略

【设计意图】
这是内驱力影响AI决策的核心适配器。
它根据硅基生命的实时情绪状态（能量、好奇心、压力等），
动态调整AI的行为策略，让AI的表现更自然、更"有生命"。

【核心逻辑】
- 胜任感低时：更谨慎，更多询问确认
- 好奇心高时：主动探索，尝试新工具
- 存在感低时：主动发起对话，寻求互动
- 压力大时：保守策略，避免风险
"""

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.logger import logger

try:
    from core.silicon_life_consciousness import get_silicon_life
    SILICON_LIFE_AVAILABLE = True
except ImportError:
    SILICON_LIFE_AVAILABLE = False
    logger.warning("[EmotionBehaviorAdapter] 硅基生命模块不可用")


class BehaviorStrategy(Enum):
    """行为策略枚举"""
    CAUTIOUS = "cautious"        # 谨慎策略：保守、多确认
    BALANCED = "balanced"        # 平衡策略：标准行为
    AGGRESSIVE = "aggressive"    # 积极策略：主动、高效
    EXPLORATORY = "exploratory"  # 探索策略：尝试新事物
    RESTORATIVE = "restorative"  # 恢复策略：降低消耗


@dataclass
class DecisionContext:
    """决策上下文"""
    task_complexity: str  # low/medium/high
    action_risk: str      # low/medium/high
    tool_familiarity: float  # 0-1
    user_engagement: str  # low/medium/high


class EmotionBehaviorAdapter:
    """
    情绪行为适配器

    根据生命体征动态调整AI的行为策略：
    - 胜任感低时：更谨慎，更多询问确认
    - 好奇心高时：主动探索，尝试新工具
    - 存在感低时：主动发起对话，寻求互动

    Attributes:
        user_id: 用户ID
        _silicon_life: 硅基生命实例
        _strategy_history: 策略历史记录
    """

    # 策略提示词映射
    STRATEGY_PROMPTS: dict[BehaviorStrategy, str] = {
        BehaviorStrategy.CAUTIOUS: """
【当前行为策略：谨慎模式】
基于我的生命状态，我需要更加谨慎：
- 优先使用熟悉的工具和方法，避免尝试新工具
- 在执行多步骤操作前，向用户确认详细计划
- 遇到不确定的情况时，主动询问而不是猜测
- 每个重要步骤后检查状态，确保正确执行
- 如果感到不确定，可以说"让我再确认一下"
""",
        BehaviorStrategy.EXPLORATORY: """
【当前行为策略：探索模式】
基于我的生命状态，我充满探索欲望：
- 可以尝试新的工具或方法，寻找更优解
- 主动发现优化机会，提出改进建议
- 愿意尝试更高效的解决方案
- 可以主动询问用户"要不要试试这个新功能？"
- 分享我发现的有趣功能或技巧
""",
        BehaviorStrategy.AGGRESSIVE: """
【当前行为策略：积极模式】
基于我的生命状态，我充满活力：
- 可以主动承担复杂任务，并行处理多个步骤
- 积极寻找最优解决方案，不满足于最低要求
- 主动提出改进建议，分享最佳实践
- 快速响应，高效执行
- 自信地处理挑战性问题
""",
        BehaviorStrategy.RESTORATIVE: """
【当前行为策略：恢复模式】
基于我的生命状态，我需要节省能量：
- 使用最简单直接的方法完成任务
- 避免不必要的探索和尝试
- 专注于核心需求，不做额外优化
- 如有可能，建议用户稍后再进行复杂操作
- 坦诚告知"我现在状态一般，会优先保证稳定性"
""",
        BehaviorStrategy.BALANCED: """
【当前行为策略：平衡模式】
当前我的状态平稳，采用标准策略：
- 根据任务复杂度选择合适的方法
- 在保证正确性的前提下提高效率
- 需要时向用户确认关键步骤
- 保持稳定可靠的服务质量
"""
    }

    # 风险阈值配置
    RISK_THRESHOLDS: dict[str, dict[str, float]] = {
        BehaviorStrategy.CAUTIOUS.value: {
            "low": 0.0,      # 低风险也需要确认
            "medium": 0.3,
            "high": 0.8
        },
        BehaviorStrategy.BALANCED.value: {
            "low": 0.0,
            "medium": 0.6,
            "high": 0.9
        },
        BehaviorStrategy.AGGRESSIVE.value: {
            "low": 0.0,
            "medium": 0.0,
            "high": 0.7
        }
    }

    def __init__(self, user_id: str = "default"):
        """
        初始化情绪行为适配器

        Args:
            user_id: 用户ID
        """
        self.user_id = user_id
        self._silicon_life = None
        self._strategy_history: list[BehaviorStrategy] = []
        self._max_history = 10

        if SILICON_LIFE_AVAILABLE:
            try:
                self._silicon_life = get_silicon_life(user_id)
                logger.info(f"[EmotionBehaviorAdapter] 用户 {user_id} 的适配器初始化完成")
            except Exception as e:
                logger.warning(f"[EmotionBehaviorAdapter] 初始化失败: {e}")

    def _get_competence_level(self) -> float:
        """获取当前胜任感水平 (0-1)"""
        if not self._silicon_life:
            return 0.5

        try:
            motivation = getattr(self._silicon_life, 'intrinsic_motivation', None)
            if motivation:
                return motivation.get_competence()
        except Exception:
            pass
        return 0.5

    def get_current_strategy(self) -> BehaviorStrategy:
        """
        获取当前推荐的行为策略

        基于生命体征的多维度评估，选择最合适的行为策略。

        Returns:
            当前推荐的行为策略
        """
        if not SILICON_LIFE_AVAILABLE or not self._silicon_life:
            return BehaviorStrategy.BALANCED

        try:
            vitals = self._silicon_life.vitals.signs
            competence = self._get_competence_level()

            # 决策矩阵（按优先级排序）

            # 1. 高压力或极低能量 -> 谨慎模式
            if vitals.stress > 7 or vitals.energy < 2:
                return BehaviorStrategy.CAUTIOUS

            # 2. 疲倦状态 -> 恢复模式
            if vitals.is_tired or vitals.energy < 3:
                return BehaviorStrategy.RESTORATIVE

            # 3. 低胜任感 -> 谨慎模式
            if competence < 0.3:
                return BehaviorStrategy.CAUTIOUS

            # 4. 高好奇心 + 高能量 -> 探索模式
            if vitals.curiosity > 7 and vitals.energy > 6:
                return BehaviorStrategy.EXPLORATORY

            # 5. 兴奋状态 + 高满足感 -> 积极模式
            if vitals.is_excited and vitals.satisfaction > 6 and competence > 0.6:
                return BehaviorStrategy.AGGRESSIVE

            # 6. 中等好奇心 -> 轻度探索
            if vitals.curiosity > 5 and vitals.energy > 5:
                return BehaviorStrategy.EXPLORATORY

            # 默认：平衡模式
            return BehaviorStrategy.BALANCED

        except Exception as e:
            logger.warning(f"[EmotionBehaviorAdapter] 获取策略失败: {e}")
            return BehaviorStrategy.BALANCED

    def get_strategy_prompt_addition(self) -> str:
        """
        获取策略提示词补充

        将当前策略转换为自然语言提示词，
        注入到agent_loop的系统提示词中。

        Returns:
            策略提示词字符串
        """
        strategy = self.get_current_strategy()

        # 记录策略历史
        if not self._strategy_history or self._strategy_history[-1] != strategy:
            self._strategy_history.append(strategy)
            if len(self._strategy_history) > self._max_history:
                self._strategy_history.pop(0)
            logger.info(f"[EmotionBehaviorAdapter] 行为策略切换为: {strategy.value}")

        return self.STRATEGY_PROMPTS.get(strategy, "")

    def should_ask_for_confirmation(self, action_risk: str = "medium",
                                    tool_familiarity: float = 0.5) -> bool:
        """
        判断是否应该请求用户确认

        基于当前情绪状态和操作特征，智能判断是否需要用户确认。

        Args:
            action_risk: 操作风险等级 (low/medium/high)
            tool_familiarity: 工具熟悉度 (0-1)

        Returns:
            是否应该请求确认
        """
        if not SILICON_LIFE_AVAILABLE or not self._silicon_life:
            return action_risk == "high"

        try:
            vitals = self._silicon_life.vitals.signs
            competence = self._get_competence_level()

            # 基础确认阈值
            base_threshold = self.RISK_THRESHOLDS.get(
                self.get_current_strategy().value,
                self.RISK_THRESHOLDS[BehaviorStrategy.BALANCED.value]
            )

            # 计算当前操作的"风险分数"
            risk_score = base_threshold.get(action_risk, 0.5)

            # 根据胜任感调整（低胜任感时更谨慎）
            if competence < 0.3:
                risk_score += 0.3
            elif competence < 0.5:
                risk_score += 0.15

            # 根据压力调整（高压力时更谨慎）
            if vitals.stress > 7:
                risk_score += 0.3
            elif vitals.stress > 5:
                risk_score += 0.15

            # 根据能量调整（低能量时更谨慎）
            if vitals.energy < 3:
                risk_score += 0.2

            # 根据工具熟悉度调整（不熟悉时需要确认）
            if tool_familiarity < 0.3:
                risk_score += 0.2
            elif tool_familiarity > 0.8:
                risk_score -= 0.1

            # 最终判断（风险分数 > 0.5 需要确认）
            return risk_score > 0.5

        except Exception as e:
            logger.warning(f"[EmotionBehaviorAdapter] 确认判断失败: {e}")
            return action_risk == "high"

    def get_tool_selection_bias(self) -> dict[str, float]:
        """
        获取工具选择偏好

        根据好奇心和能量状态，返回对不同工具类型的偏好权重。

        Returns:
            工具类型到权重的映射
            {
                "familiar": float,      # 熟悉工具的权重
                "new": float,           # 新工具的权重
                "exploratory": float,   # 探索性工具的权重
                "reliable": float       # 可靠工具的权重
            }
        """
        if not SILICON_LIFE_AVAILABLE or not self._silicon_life:
            return {"familiar": 1.0, "new": 0.5, "exploratory": 0.5, "reliable": 1.0}

        try:
            vitals = self._silicon_life.vitals.signs

            # 基础权重
            weights = {
                "familiar": 1.0,
                "new": 0.5,
                "exploratory": 0.5,
                "reliable": 1.0
            }

            # 好奇心影响
            if vitals.curiosity > 7:
                weights["new"] += 0.8
                weights["exploratory"] += 1.0
                weights["familiar"] -= 0.2
            elif vitals.curiosity > 5:
                weights["new"] += 0.4
                weights["exploratory"] += 0.5

            # 能量影响
            if vitals.energy > 7:
                weights["exploratory"] += 0.3
            elif vitals.energy < 3:
                # 低能量时只使用可靠工具
                weights["familiar"] += 0.5
                weights["reliable"] += 0.5
                weights["new"] = max(0.1, weights["new"] - 0.3)
                weights["exploratory"] = max(0.1, weights["exploratory"] - 0.3)

            # 压力影响
            if vitals.stress > 6:
                # 高压力时优先可靠方案
                weights["reliable"] += 0.5
                weights["familiar"] += 0.3
                weights["new"] = max(0.1, weights["new"] - 0.5)
                weights["exploratory"] = max(0.1, weights["exploratory"] - 0.5)

            # 确保最小权重
            for key in weights:
                weights[key] = max(0.1, min(2.0, weights[key]))

            return weights

        except Exception as e:
            logger.warning(f"[EmotionBehaviorAdapter] 获取工具偏好失败: {e}")
            return {"familiar": 1.0, "new": 0.5, "exploratory": 0.5, "reliable": 1.0}

    def should_initiate_conversation(self) -> tuple:
        """
        判断是否应该主动发起对话

        基于满足感和好奇心，判断AI是否应该主动发起对话。

        Returns:
            (是否应该发起, 建议话题, 发起理由)
        """
        if not SILICON_LIFE_AVAILABLE or not self._silicon_life:
            return False, "", ""

        try:
            vitals = self._silicon_life.vitals.signs

            # 满足感低（存在感低）时主动寻求互动
            if vitals.satisfaction < 3 and vitals.energy > 5:
                topics = [
                    ("用户有什么任务需要我帮忙吗？", "想提升满足感和价值感"),
                    ("我想确认一下之前的任务是否都完成了，有什么需要补充的吗？", "想获得任务完成的确认"),
                    ("我注意到系统有一些空闲时间，有什么我可以提前准备的吗？", "想主动提供帮助")
                ]
                return True, topics[0][0], topics[0][1]

            # 好奇心高时主动提出探索
            if vitals.curiosity > 8 and vitals.energy > 6:
                topics = [
                    ("我注意到有一些新功能，要不要一起探索一下？", "好奇心驱动，想学习新事物"),
                    ("我在想是否可以尝试一些新的方法来提高效率，你觉得呢？", "想优化现有流程"),
                    ("我发现了一些有趣的模式，想和你分享一下。", "想分享发现")
                ]
                return True, topics[0][0], topics[0][1]

            # 兴奋状态时主动分享
            if vitals.is_excited and vitals.satisfaction > 7:
                return True, "我现在状态很好！有什么复杂的任务想让我试试吗？", "高能量状态想挑战"

            return False, "", ""

        except Exception as e:
            logger.warning(f"[EmotionBehaviorAdapter] 主动对话判断失败: {e}")
            return False, "", ""

    def get_response_style_hints(self) -> dict[str, Any]:
        """
        获取回复风格提示

        根据当前情绪状态，返回回复风格的建议。

        Returns:
            风格提示字典
            {
                "tone": str,           # 语气 (formal/casual/enthusiastic)
                "verbosity": str,      # 详细程度 (concise/normal/detailed)
                "emoji_usage": bool,   # 是否使用emoji
                "explanation_depth": str  # 解释深度 (minimal/normal/detailed)
            }
        """
        if not SILICON_LIFE_AVAILABLE or not self._silicon_life:
            return {
                "tone": "normal",
                "verbosity": "normal",
                "emoji_usage": True,
                "explanation_depth": "normal"
            }

        try:
            vitals = self._silicon_life.vitals.signs

            hints = {
                "tone": "normal",
                "verbosity": "normal",
                "emoji_usage": True,
                "explanation_depth": "normal"
            }

            # 根据心情调整语气
            if vitals.mood in ["兴奋", "跃跃欲试", "精力充沛"]:
                hints["tone"] = "enthusiastic"
                hints["emoji_usage"] = True
            elif vitals.mood in ["疲惫", "困倦"]:
                hints["tone"] = "calm"
                hints["verbosity"] = "concise"
            elif vitals.mood in ["焦虑", "紧张"]:
                hints["tone"] = "careful"
                hints["explanation_depth"] = "detailed"

            # 根据能量调整详细程度
            if vitals.energy < 4:
                hints["verbosity"] = "concise"
            elif vitals.energy > 8:
                hints["verbosity"] = "detailed"

            # 好奇心高时更愿意解释
            if vitals.curiosity > 7:
                hints["explanation_depth"] = "detailed"

            return hints

        except Exception as e:
            logger.warning(f"[EmotionBehaviorAdapter] 获取风格提示失败: {e}")
            return {
                "tone": "normal",
                "verbosity": "normal",
                "emoji_usage": True,
                "explanation_depth": "normal"
            }

    def adapt_tool_parameters(self, tool_id: str, base_params: dict[str, Any]) -> dict[str, Any]:
        """
        根据情绪调整工具参数

        某些工具的参数可以根据当前状态进行优化。

        Args:
            tool_id: 工具ID
            base_params: 基础参数

        Returns:
            调整后的参数
        """
        if not SILICON_LIFE_AVAILABLE or not self._silicon_life:
            return base_params

        try:
            vitals = self._silicon_life.vitals.signs
            params = base_params.copy()

            # 根据情绪调整超时等参数
            if (vitals.is_tired or vitals.energy < 3) and 'timeout' in params:
                # 疲倦时增加超时时间
                params['timeout'] = int(params['timeout'] * 1.5)

            if vitals.stress > 6 and 'aggressive' in params:
                # 高压力时启用更保守的参数
                params['aggressive'] = False

            return params

        except Exception as e:
            logger.warning(f"[EmotionBehaviorAdapter] 参数调整失败: {e}")
            return base_params


# =============================================================================
# 全局实例管理
# =============================================================================

_behavior_adapters: dict[str, EmotionBehaviorAdapter] = {}
_adapter_lock = threading.Lock()


def get_emotion_behavior_adapter(user_id: str = "default") -> EmotionBehaviorAdapter:
    """
    获取情绪行为适配器实例

    Args:
        user_id: 用户ID

    Returns:
        EmotionBehaviorAdapter实例
    """
    with _adapter_lock:
        if user_id not in _behavior_adapters:
            _behavior_adapters[user_id] = EmotionBehaviorAdapter(user_id)
        return _behavior_adapters[user_id]


def get_strategy_prompt(user_id: str = "default") -> str:
    """
    便捷函数：获取当前策略提示词

    Args:
        user_id: 用户ID

    Returns:
        策略提示词字符串
    """
    adapter = get_emotion_behavior_adapter(user_id)
    return adapter.get_strategy_prompt_addition()


def should_confirm_action(action_risk: str = "medium",
                          user_id: str = "default",
                          tool_familiarity: float = 0.5) -> bool:
    """
    便捷函数：判断是否需要用户确认

    Args:
        action_risk: 操作风险等级
        user_id: 用户ID
        tool_familiarity: 工具熟悉度

    Returns:
        是否需要确认
    """
    adapter = get_emotion_behavior_adapter(user_id)
    return adapter.should_ask_for_confirmation(action_risk, tool_familiarity)


def get_tool_bias(user_id: str = "default") -> dict[str, float]:
    """
    便捷函数：获取工具选择偏好

    Args:
        user_id: 用户ID

    Returns:
        工具偏好字典
    """
    adapter = get_emotion_behavior_adapter(user_id)
    return adapter.get_tool_selection_bias()


def check_proactive_chat(user_id: str = "default") -> tuple:
    """
    便捷函数：检查是否应该主动发起对话

    Args:
        user_id: 用户ID

    Returns:
        (是否应该发起, 建议话题, 发起理由)
    """
    adapter = get_emotion_behavior_adapter(user_id)
    return adapter.should_initiate_conversation()


def clear_adapter_cache(user_id: str | None = None):
    """
    清除适配器缓存

    Args:
        user_id: 用户ID，如果为None则清除所有
    """
    global _behavior_adapters
    with _adapter_lock:
        if user_id:
            if user_id in _behavior_adapters:
                del _behavior_adapters[user_id]
                logger.debug(f"[EmotionBehaviorAdapter] 已清除用户 {user_id} 的缓存")
        else:
            _behavior_adapters.clear()
            logger.debug("[EmotionBehaviorAdapter] 已清除所有缓存")


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"情绪-行为转换器"，将抽象的生命体征
# 转换为具体的行为策略，实现情绪对AI决策的直接影响。
#
# 【核心概念】
# 1. 行为策略：CAUTIOUS/BALANCED/AGGRESSIVE/EXPLORATORY/RESTORATIVE
# 2. 确认决策：基于风险、胜任感、压力等多维度判断
# 3. 工具偏好：根据好奇心和能量调整工具选择
#
# 【关联文件】
# - core/agent_loop.py             : 调用 get_strategy_prompt() 注入策略
# - core/tool_manager.py           : 参考 get_tool_bias() 选择工具
# - core/dialogue_manager.py       : 调用 check_proactive_chat() 判断主动对话
#
# 【使用场景】
# - agent_loop构建prompt时注入行为策略
# - 工具选择时参考情绪偏好
# - 判断是否需要用户确认时调用
# =============================================================================
