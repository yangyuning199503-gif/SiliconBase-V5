#!/usr/bin/env python3
"""
强化学习执行反馈系统 - 方向C: 执行反馈强化学习
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

核心改进：
1. 策略学习：从成功/失败中提取有效策略模式
2. 行为模式识别：识别导致成功的行为序列
3. 动态策略调整：根据反馈调整执行策略
4. 长期价值评估：不仅看即时结果，还看长期价值
5. 工具组合优化：学习最优工具调用序列

Author: Agent-Refactoring
Version: 1.0.0
"""

import hashlib
import json
import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from core.logger import logger


class StrategyType(Enum):
    """策略类型"""
    TOOL_SELECTION = "tool_selection"      # 工具选择策略
    PARAMETER_SETTING = "parameter"         # 参数设置策略
    SEQUENCE_ORDER = "sequence"             # 执行顺序策略
    ERROR_RECOVERY = "error_recovery"       # 错误恢复策略
    RETRY_PATTERN = "retry"                 # 重试模式策略


@dataclass
class ActionOutcome:
    """行动结果记录"""
    action: str                            # 行动描述
    params: dict[str, Any]                 # 参数
    success: bool                          # 是否成功
    execution_time: float                  # 执行时间(秒)
    feedback_score: float                  # 反馈分数 (-1到1)
    timestamp: float                       # 时间戳
    context: dict[str, Any] = field(default_factory=dict)  # 上下文


@dataclass
class LearnedStrategy:
    """学习到的策略"""
    strategy_id: str
    strategy_type: StrategyType

    # 策略定义
    pattern: dict[str, Any]                # 模式定义
    applicability_conditions: list[str]     # 适用条件

    # 效果统计
    usage_count: int = 0                   # 使用次数
    success_count: int = 0                 # 成功次数
    total_reward: float = 0.0              # 累计奖励
    avg_execution_time: float = 0.0        # 平均执行时间

    # 时间信息
    created_at: float = field(default_factory=time.time)
    last_used: float = 0.0

    # 元数据
    confidence: float = 0.5                # 置信度 (0-1)
    is_deprecated: bool = False            # 是否已废弃

    def update_effectiveness(self, success: bool, reward: float, exec_time: float):
        """更新策略效果"""
        self.usage_count += 1
        if success:
            self.success_count += 1
        self.total_reward += reward
        self.last_used = time.time()

        # 更新平均执行时间
        if self.avg_execution_time == 0:
            self.avg_execution_time = exec_time
        else:
            self.avg_execution_time = (self.avg_execution_time * (self.usage_count - 1) + exec_time) / self.usage_count

        # 更新置信度
        if self.usage_count >= 5:
            success_rate = self.success_count / self.usage_count
            self.confidence = min(0.95, success_rate * 0.9 + 0.1)

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.usage_count == 0:
            return 0.0
        return self.success_count / self.usage_count

    @property
    def average_reward(self) -> float:
        """平均奖励"""
        if self.usage_count == 0:
            return 0.0
        return self.total_reward / self.usage_count


@dataclass
class ExecutionEpisode:
    """执行回合记录"""
    episode_id: str
    task_description: str
    task_type: str

    # 执行序列
    actions: list[ActionOutcome] = field(default_factory=list)

    # 结果
    final_success: bool = False
    total_reward: float = 0.0
    total_time: float = 0.0

    # 时间戳
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None

    def add_action(self, action: ActionOutcome):
        """添加行动"""
        self.actions.append(action)
        self.total_time += action.execution_time
        self.total_reward += action.feedback_score

    def finalize(self, success: bool):
        """结束回合"""
        self.final_success = success
        self.end_time = time.time()

        # 根据结果调整奖励
        if success:
            self.total_reward += 1.0  # 完成奖励
        else:
            self.total_reward -= 0.5  # 失败惩罚


class ReinforcementLearningEngine:
    """
    强化学习执行反馈引擎

    功能：
    1. 记录执行回合（成功和失败）
    2. 从执行历史中提取有效策略
    3. 评估策略效果并持续优化
    4. 为相似任务推荐最优策略
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, storage_path: str = "data/rl_strategies.json"):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True

        self.storage_path = storage_path

        # 策略库
        self._strategies: dict[str, LearnedStrategy] = {}
        self._strategies_by_type: dict[StrategyType, list[str]] = defaultdict(list)

        # 执行历史
        self._episodes: list[ExecutionEpisode] = []
        self._max_episodes = 1000

        # 当前回合
        self._current_episode: ExecutionEpisode | None = None

        # 统计信息
        self._stats = {
            "total_episodes": 0,
            "successful_episodes": 0,
            "strategies_learned": 0,
            "total_reward": 0.0
        }

        # 加载历史数据
        self._load_data()

        logger.info(f"[RLEngine] 强化学习引擎初始化完成，已加载 {len(self._strategies)} 个策略")

    def start_episode(self, task_description: str, task_type: str = "general") -> str:
        """
        开始一个新的执行回合

        Args:
            task_description: 任务描述
            task_type: 任务类型

        Returns:
            episode_id: 回合ID
        """
        episode_id = f"ep_{int(time.time() * 1000)}_{hashlib.md5(task_description.encode()).hexdigest()[:8]}"

        self._current_episode = ExecutionEpisode(
            episode_id=episode_id,
            task_description=task_description,
            task_type=task_type
        )

        logger.info(f"[RLEngine] 开始执行回合: {episode_id}, 任务: {task_type}")
        return episode_id

    def record_action(self,
                     action: str,
                     params: dict[str, Any],
                     success: bool,
                     execution_time: float,
                     feedback_score: float = 0.0,
                     context: dict | None = None):
        """
        记录一个行动的结果

        Args:
            action: 行动描述（如工具名称）
            params: 参数
            success: 是否成功
            execution_time: 执行时间
            feedback_score: 反馈分数 (-1到1)
            context: 上下文信息
        """
        if self._current_episode is None:
            logger.warning("[RLEngine] 没有活动的执行回合，请先调用start_episode")
            return

        outcome = ActionOutcome(
            action=action,
            params=params,
            success=success,
            execution_time=execution_time,
            feedback_score=feedback_score,
            timestamp=time.time(),
            context=context or {}
        )

        self._current_episode.add_action(outcome)

        # 实时学习：更新相关策略
        self._update_strategies_from_action(outcome)

        logger.debug(f"[RLEngine] 记录行动: {action}, 成功={success}, 奖励={feedback_score}")

    def end_episode(self, final_success: bool, task_result: dict | None = None) -> ExecutionEpisode:
        """
        结束当前执行回合

        Args:
            final_success: 最终是否成功
            task_result: 任务结果详情

        Returns:
            ExecutionEpisode: 完整的回合记录
        """
        if self._current_episode is None:
            logger.warning("[RLEngine] 没有活动的执行回合")
            return None

        self._current_episode.finalize(final_success)
        episode = self._current_episode

        # 保存到历史
        self._episodes.append(episode)
        if len(self._episodes) > self._max_episodes:
            self._episodes.pop(0)  # 移除最旧的

        # 更新统计
        self._stats["total_episodes"] += 1
        if final_success:
            self._stats["successful_episodes"] += 1
        self._stats["total_reward"] += episode.total_reward

        # 从回合中提取策略
        self._extract_strategies_from_episode(episode)

        # 清理
        self._current_episode = None

        # 保存数据
        self._save_data()

        logger.info(
            f"[RLEngine] 结束回合: {episode.episode_id}, "
            f"成功={final_success}, 总奖励={episode.total_reward:.2f}, "
            f"行动数={len(episode.actions)}"
        )

        return episode

    def get_strategy_recommendations(self,
                                    task_description: str,
                                    task_type: str,
                                    current_context: dict | None = None) -> list[dict]:
        """
        获取策略推荐

        Args:
            task_description: 任务描述
            task_type: 任务类型
            current_context: 当前上下文

        Returns:
            推荐策略列表（按置信度排序）
        """
        recommendations = []

        # 1. 查找适用的策略
        for strategy in self._strategies.values():
            if strategy.is_deprecated:
                continue
            if strategy.confidence < 0.5:
                continue

            # 检查适用条件
            if self._check_applicability(strategy, task_description, current_context):
                recommendations.append({
                    "strategy_id": strategy.strategy_id,
                    "strategy_type": strategy.strategy_type.value,
                    "pattern": strategy.pattern,
                    "confidence": strategy.confidence,
                    "success_rate": strategy.success_rate,
                    "avg_reward": strategy.average_reward,
                    "usage_count": strategy.usage_count
                })

        # 2. 按置信度和成功率排序
        recommendations.sort(key=lambda x: x["confidence"] * x["success_rate"], reverse=True)

        return recommendations[:5]  # 返回前5个

    def get_optimal_tool_sequence(self, task_type: str, goal: str) -> list[str]:
        """
        获取最优工具调用序列

        基于历史成功回合，找出最常用的成功工具序列
        """
        # 筛选相关回合
        relevant_episodes = [
            ep for ep in self._episodes
            if ep.task_type == task_type and ep.final_success
        ]

        if not relevant_episodes:
            return []

        # 统计工具序列模式
        sequence_counts = defaultdict(int)

        for ep in relevant_episodes:
            # 获取工具序列（最多前5个）
            tool_sequence = tuple(
                a.action for a in ep.actions[:5]
            )
            if len(tool_sequence) >= 2:  # 至少两个工具才有意义
                sequence_counts[tool_sequence] += 1

        if not sequence_counts:
            return []

        # 返回最常见的序列
        best_sequence = max(sequence_counts.keys(), key=lambda x: sequence_counts[x])
        return list(best_sequence)

    def analyze_failure_patterns(self, tool_name: str | None = None) -> list[dict]:
        """
        分析失败模式

        Args:
            tool_name: 工具名称（可选，分析特定工具的失败）

        Returns:
            失败模式列表
        """
        failure_patterns = defaultdict(lambda: {"count": 0, "actions": []})

        for ep in self._episodes:
            if ep.final_success:
                continue  # 只分析失败回合

            for action in ep.actions:
                if not action.success:
                    if tool_name and action.action != tool_name:
                        continue

                    # 提取失败模式
                    pattern_key = f"{action.action}:{action.params.get('operation', 'unknown')}"
                    failure_patterns[pattern_key]["count"] += 1
                    failure_patterns[pattern_key]["actions"].append({
                        "params": action.params,
                        "context": action.context,
                        "episode_id": ep.episode_id
                    })

        # 转换为列表并排序
        result = []
        for pattern, data in failure_patterns.items():
            if data["count"] >= 2:  # 至少出现2次的才算模式
                result.append({
                    "pattern": pattern,
                    "count": data["count"],
                    "examples": data["actions"][:3]  # 最多3个示例
                })

        result.sort(key=lambda x: x["count"], reverse=True)
        return result

    def get_learning_summary(self) -> dict[str, Any]:
        """获取学习摘要"""
        return {
            "total_episodes": self._stats["total_episodes"],
            "success_rate": (
                self._stats["successful_episodes"] / max(1, self._stats["total_episodes"])
            ),
            "total_strategies": len(self._strategies),
            "strategy_breakdown": {
                st.value: len(ids) for st, ids in self._strategies_by_type.items()
            },
            "top_strategies": [
                {
                    "id": s.strategy_id,
                    "type": s.strategy_type.value,
                    "success_rate": s.success_rate,
                    "confidence": s.confidence,
                    "usage_count": s.usage_count
                }
                for s in sorted(
                    self._strategies.values(),
                    key=lambda x: x.confidence * x.success_rate,
                    reverse=True
                )[:5]
            ],
            "average_reward": (
                self._stats["total_reward"] / max(1, self._stats["total_episodes"])
            )
        }

    def _extract_strategies_from_episode(self, episode: ExecutionEpisode):
        """从执行回合中提取策略"""
        if not episode.actions:
            return

        # 1. 提取工具选择策略
        successful_tools = [
            a.action for a in episode.actions
            if a.success
        ]

        if successful_tools and episode.final_success:
            strategy_id = f"ts_{episode.task_type}_{hashlib.md5(str(successful_tools).encode()).hexdigest()[:8]}"

            if strategy_id not in self._strategies:
                strategy = LearnedStrategy(
                    strategy_id=strategy_id,
                    strategy_type=StrategyType.TOOL_SELECTION,
                    pattern={"tools": successful_tools, "task_type": episode.task_type},
                    applicability_conditions=[f"task_type == '{episode.task_type}'"]
                )
                self._strategies[strategy_id] = strategy
                self._strategies_by_type[StrategyType.TOOL_SELECTION].append(strategy_id)
                self._stats["strategies_learned"] += 1

        # 2. 提取错误恢复策略
        for i, action in enumerate(episode.actions):
            if not action.success and i + 1 < len(episode.actions):
                # 查找恢复行动
                next_action = episode.actions[i + 1]
                if next_action.success:
                    strategy_id = f"er_{action.action}_{hashlib.md5(str(next_action.params).encode()).hexdigest()[:8]}"

                    if strategy_id not in self._strategies:
                        strategy = LearnedStrategy(
                            strategy_id=strategy_id,
                            strategy_type=StrategyType.ERROR_RECOVERY,
                            pattern={
                                "failed_action": action.action,
                                "recovery_action": next_action.action,
                                "recovery_params": next_action.params
                            },
                            applicability_conditions=[f"after_failure == '{action.action}'"]
                        )
                        self._strategies[strategy_id] = strategy
                        self._strategies_by_type[StrategyType.ERROR_RECOVERY].append(strategy_id)
                        self._stats["strategies_learned"] += 1

    def _update_strategies_from_action(self, outcome: ActionOutcome):
        """从单个行动结果更新策略"""
        # 找到相关的策略并更新
        for strategy in self._strategies.values():
            if strategy.strategy_type == StrategyType.TOOL_SELECTION and outcome.action in strategy.pattern.get("tools", []):
                strategy.update_effectiveness(
                    outcome.success,
                    outcome.feedback_score,
                    outcome.execution_time
                )

    def _check_applicability(self,
                            strategy: LearnedStrategy,
                            task_description: str,
                            context: dict | None) -> bool:
        """检查策略是否适用于当前情况"""
        # 简化的适用性检查
        context = context or {}

        for condition in strategy.applicability_conditions:
            if "task_type ==" in condition:
                expected_type = condition.split("==")[1].strip().strip("'")
                if context.get("task_type") != expected_type:
                    return False

        return True

    def _save_data(self):
        """保存数据到文件"""
        try:
            import os
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)

            data = {
                "strategies": {
                    sid: {
                        **asdict(s),
                        "strategy_type": s.strategy_type.value
                    }
                    for sid, s in self._strategies.items()
                },
                "stats": self._stats,
                "saved_at": datetime.now().isoformat()
            }

            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"[RLEngine] 保存数据失败: {e}")

    def _load_data(self):
        """从文件加载数据"""
        try:
            import os
            if not os.path.exists(self.storage_path):
                return

            with open(self.storage_path, encoding='utf-8') as f:
                data = json.load(f)

            # 加载策略
            for sid, sdata in data.get("strategies", {}).items():
                strategy = LearnedStrategy(
                    strategy_id=sdata["strategy_id"],
                    strategy_type=StrategyType(sdata["strategy_type"]),
                    pattern=sdata["pattern"],
                    applicability_conditions=sdata["applicability_conditions"],
                    usage_count=sdata.get("usage_count", 0),
                    success_count=sdata.get("success_count", 0),
                    total_reward=sdata.get("total_reward", 0.0),
                    avg_execution_time=sdata.get("avg_execution_time", 0.0),
                    confidence=sdata.get("confidence", 0.5),
                    is_deprecated=sdata.get("is_deprecated", False)
                )
                self._strategies[sid] = strategy
                self._strategies_by_type[strategy.strategy_type].append(sid)

            # 加载统计
            self._stats = data.get("stats", self._stats)

            logger.info(f"[RLEngine] 已加载 {len(self._strategies)} 个策略")

        except Exception as e:
            logger.warning(f"[RLEngine] 加载数据失败: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# 便捷函数
# ═════════════════════════════════════════════════════════════════════════════

_rl_engine: ReinforcementLearningEngine | None = None


def get_rl_engine() -> ReinforcementLearningEngine:
    """获取强化学习引擎实例"""
    global _rl_engine
    if _rl_engine is None:
        _rl_engine = ReinforcementLearningEngine()
    return _rl_engine


def record_execution_result(task_type: str,
                           tool_sequence: list[str],
                           success: bool,
                           execution_time: float):
    """
    便捷函数：记录执行结果

    Args:
        task_type: 任务类型
        tool_sequence: 工具调用序列
        success: 是否成功
        execution_time: 执行时间
    """
    engine = get_rl_engine()

    # 开始回合
    engine.start_episode(
        task_description=f"Task type: {task_type}",
        task_type=task_type
    )

    # 记录每个工具调用
    for tool in tool_sequence:
        engine.record_action(
            action=tool,
            params={},
            success=success,
            execution_time=execution_time / max(1, len(tool_sequence)),
            feedback_score=1.0 if success else -0.5
        )

    # 结束回合
    engine.end_episode(final_success=success)


def get_optimal_strategy(task_type: str, context: dict | None = None) -> dict | None:
    """
    获取最优策略

    Args:
        task_type: 任务类型
        context: 上下文

    Returns:
        最优策略或None
    """
    engine = get_rl_engine()
    recommendations = engine.get_strategy_recommendations(
        task_description=f"Task type: {task_type}",
        task_type=task_type,
        current_context=context
    )

    return recommendations[0] if recommendations else None
