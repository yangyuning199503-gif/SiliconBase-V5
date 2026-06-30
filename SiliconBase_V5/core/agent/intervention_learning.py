#!/usr/bin/env python3
"""
用户干预模式学习
【Week 4 Day 7】学习用户的干预习惯，优化建议策略

学习目标：
1. 用户常在什么情况下干预？
2. 用户偏好哪种干预方式？
3. 干预后通常如何调整？
4. 预测当前任务是否需要干预提示
"""

import json
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.logger import logger


@dataclass
class UserInterventionPattern:
    """用户干预模式"""
    user_id: str
    total_interventions: int = 0                    # 总干预次数
    accepted_suggestions: int = 0                   # 接受的建议数
    dismissed_suggestions: int = 0                  # 忽略的建议数

    # 按场景统计
    scenario_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # 按操作类型统计
    action_preferences: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # 干预时机（轮次分布）
    intervention_rounds: list[int] = field(default_factory=list)

    # 学习到的阈值偏好
    preferred_loop_threshold: int | None = None   # 偏好的循环检测阈值
    preferred_timeout_multiplier: float | None = None  # 偏好的超时倍数

    last_updated: float = field(default_factory=time.time)

    @property
    def acceptance_rate(self) -> float:
        """建议接受率"""
        total = self.accepted_suggestions + self.dismissed_suggestions
        return self.accepted_suggestions / total if total > 0 else 0.5

    @property
    def avg_intervention_round(self) -> float | None:
        """平均干预轮次"""
        if not self.intervention_rounds:
            return None
        return sum(self.intervention_rounds) / len(self.intervention_rounds)


@dataclass
class InterventionRecord:
    """干预记录"""
    id: str
    user_id: str
    runtime_id: str | None
    task_id: str | None
    task_description: str

    # 触发条件
    trigger_type: str           # loop_detected, tool_failing, etc.
    trigger_confidence: float   # 触发时的置信度
    trigger_round: int          # 触发时的执行轮次

    # 用户响应
    was_suggested: bool         # 是否由AI建议
    was_accepted: bool          # 是否接受建议
    user_action: str            # PAUSE, REPLAN, ADJUST, CANCEL, CONTINUE

    # 干预后结果
    outcome: str | None = None   # success, partial, failure
    time_to_resolution: float | None = None  # 干预到解决的时间

    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


class InterventionLearner:
    """
    用户干预模式学习器

    持续学习用户的干预偏好，优化建议策略
    """

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or Path("data/intervention_learning")
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 用户模式缓存 {user_id: UserInterventionPattern}
        self._patterns: dict[str, UserInterventionPattern] = {}

        # 干预记录缓存
        self._records: list[InterventionRecord] = []

        # 加载已有数据
        self._load_data()

        logger.info("[InterventionLearner] 干预学习器初始化完成")

    def _get_user_file(self, user_id: str) -> Path:
        """获取用户数据文件路径"""
        return self.data_dir / f"{user_id}_pattern.json"

    def _load_data(self):
        """加载已有学习数据"""
        try:
            for file in self.data_dir.glob("*_pattern.json"):
                user_id = file.stem.replace("_pattern", "")
                with open(file, encoding='utf-8') as f:
                    data = json.load(f)
                    self._patterns[user_id] = UserInterventionPattern(**data)
            logger.info(f"[InterventionLearner] 加载了 {len(self._patterns)} 个用户模式")
        except Exception as e:
            logger.error(f"[InterventionLearner] 加载数据失败: {e}")

    def _save_user_pattern(self, user_id: str):
        """保存用户模式"""
        try:
            pattern = self._patterns.get(user_id)
            if pattern:
                file_path = self._get_user_file(user_id)
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(asdict(pattern), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[InterventionLearner] 保存用户模式失败: {e}")

    def get_or_create_pattern(self, user_id: str) -> UserInterventionPattern:
        """获取或创建用户模式"""
        if user_id not in self._patterns:
            self._patterns[user_id] = UserInterventionPattern(user_id=user_id)
        return self._patterns[user_id]

    def record_intervention(self, record: InterventionRecord):
        """
        记录一次干预

        Args:
            record: 干预记录
        """
        self._records.append(record)

        # 更新用户模式
        pattern = self.get_or_create_pattern(record.user_id)
        pattern.total_interventions += 1

        if record.was_suggested:
            if record.was_accepted:
                pattern.accepted_suggestions += 1
            else:
                pattern.dismissed_suggestions += 1

        # 统计场景
        pattern.scenario_counts[record.trigger_type] += 1

        # 统计操作偏好
        pattern.action_preferences[record.user_action] += 1

        # 记录干预轮次
        pattern.intervention_rounds.append(record.trigger_round)
        # 只保留最近100条
        pattern.intervention_rounds = pattern.intervention_rounds[-100:]

        # 学习阈值偏好
        self._learn_threshold_preferences(pattern, record)

        pattern.last_updated = time.time()

        # 保存
        self._save_user_pattern(record.user_id)

        logger.debug(f"[InterventionLearner] 记录干预: {record.user_id} - {record.trigger_type}")

    def _learn_threshold_preferences(self, pattern: UserInterventionPattern,
                                     record: InterventionRecord):
        """学习阈值偏好"""
        # 基于用户接受/忽略建议的情况，调整阈值偏好
        if not record.was_suggested and record.trigger_type == 'loop_detected':
            # 用户主动干预，说明默认阈值可能不够敏感
            # 用户主动在较早轮次干预，倾向于更早检测
            if pattern.preferred_loop_threshold is None:
                pattern.preferred_loop_threshold = record.trigger_round
            else:
                # 滑动平均
                pattern.preferred_loop_threshold = int(
                    0.7 * pattern.preferred_loop_threshold +
                    0.3 * record.trigger_round
                )

    def predict_need_intervention(self, user_id: str, context: dict[str, Any]) -> tuple[float, str | None]:
        """
        预测当前任务是否需要干预提示

        Args:
            user_id: 用户ID
            context: 任务上下文
                - round_count: 当前轮次
                - tool_failures: 工具失败次数
                - task_type: 任务类型
                - elapsed_time: 已用时间
                - estimated_time: 预估时间

        Returns:
            (概率, 建议类型)
        """
        pattern = self.get_or_create_pattern(user_id)

        round_count = context.get('round_count', 0)
        tool_failures = context.get('tool_failures', {})

        # 基于用户历史模式计算概率

        # 1. 基于平均干预轮次
        avg_round = pattern.avg_intervention_round
        if avg_round and round_count > avg_round * 0.8:
            # 接近用户通常干预的轮次
            return min(0.9, round_count / avg_round), 'loop_detected'

        # 2. 基于场景统计
        if pattern.scenario_counts:
            most_common_scenario = max(pattern.scenario_counts,
                                      key=pattern.scenario_counts.get)
            scenario_prob = pattern.scenario_counts[most_common_scenario] / pattern.total_interventions

            # 如果用户经常因为循环而干预，且当前轮次较高
            if most_common_scenario == 'loop_detected' and round_count > 8:
                return min(0.8, scenario_prob), 'loop_detected'

        # 3. 基于工具失败
        max_failures = max(tool_failures.values()) if tool_failures else 0
        if max_failures >= 2:
            return 0.7, 'tool_failing'

        # 4. 默认低概率
        return 0.1, None

    def get_suggested_action(self, user_id: str, scenario_type: str) -> str:
        """
        根据用户偏好获取建议操作

        Args:
            user_id: 用户ID
            scenario_type: 场景类型

        Returns:
            建议的操作
        """
        pattern = self.get_or_create_pattern(user_id)

        if pattern.action_preferences:
            # 返回用户最常用的操作
            return max(pattern.action_preferences,
                      key=pattern.action_preferences.get)

        # 默认建议
        default_actions = {
            'loop_detected': 'PAUSE',
            'tool_failing': 'ADJUST',
            'goal_drift': 'REPLAN',
            'timeout_warning': 'PAUSE',
            'resource_exhausted': 'PAUSE'
        }
        return default_actions.get(scenario_type, 'PAUSE')

    def get_personalized_config(self, user_id: str) -> dict[str, Any]:
        """
        获取个性化配置

        Args:
            user_id: 用户ID

        Returns:
            个性化检测配置
        """
        pattern = self.get_or_create_pattern(user_id)

        config = {
            'loop_warning_threshold': pattern.preferred_loop_threshold or 10,
            'confidence_threshold': 1 - pattern.acceptance_rate,  # 接受率低则提高置信度阈值
        }

        # 如果用户经常忽略建议，提高阈值
        if pattern.dismissed_suggestions > pattern.accepted_suggestions * 2:
            config['loop_warning_threshold'] = int(config['loop_warning_threshold'] * 0.8)
            config['higher_confidence_required'] = True

        return config

    def get_user_stats(self, user_id: str) -> dict[str, Any]:
        """获取用户统计"""
        pattern = self.get_or_create_pattern(user_id)

        return {
            'total_interventions': pattern.total_interventions,
            'acceptance_rate': pattern.acceptance_rate,
            'most_common_scenario': max(pattern.scenario_counts,
                                       key=pattern.scenario_counts.get) if pattern.scenario_counts else None,
            'preferred_action': max(pattern.action_preferences,
                                   key=pattern.action_preferences.get) if pattern.action_preferences else None,
            'avg_intervention_round': pattern.avg_intervention_round,
            'preferred_loop_threshold': pattern.preferred_loop_threshold
        }

    def get_global_stats(self) -> dict[str, Any]:
        """获取全局统计"""
        if not self._patterns:
            return {'user_count': 0}

        total_interventions = sum(p.total_interventions for p in self._patterns.values())
        avg_acceptance = sum(p.acceptance_rate for p in self._patterns.values()) / len(self._patterns)

        # 合并所有场景统计
        all_scenarios = defaultdict(int)
        for pattern in self._patterns.values():
            for scenario, count in pattern.scenario_counts.items():
                all_scenarios[scenario] += count

        return {
            'user_count': len(self._patterns),
            'total_interventions': total_interventions,
            'avg_acceptance_rate': avg_acceptance,
            'most_common_scenario': max(all_scenarios, key=all_scenarios.get) if all_scenarios else None
        }


# 全局实例
intervention_learner = InterventionLearner()
