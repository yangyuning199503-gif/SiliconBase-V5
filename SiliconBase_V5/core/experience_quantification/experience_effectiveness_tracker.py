#!/usr/bin/env python3
"""
经验效果追踪器
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
追踪每条经验的使用情况和效果，建立经验-结果的闭环追踪

核心功能:
1. 记录经验使用（每次任务使用了哪些经验）
2. 追踪任务结果（成功/失败、耗时、满意度）
3. 统计经验效果（成功率、平均贡献度）
4. 经验归因分析（哪些经验真正带来了成功）

Author: Agent-6 Experience Optimizer
Version: 1.0.0
"""

import hashlib
import json
import logging
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExperienceUsageEvent:
    """经验使用事件"""
    event_id: str
    experience_id: str
    task_id: str
    task_type: str
    used_at: float

    # 经验在任务中的角色
    role: str = "reference"  # "reference" | "primary" | "fallback"
    position: int = 0  # 在经验列表中的位置

    # 上下文
    user_id: str = "default"
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExperienceEffectivenessStats:
    """单条经验的效果统计"""
    experience_id: str

    # 使用统计
    usage_count: int = 0
    last_used_at: float | None = None
    first_used_at: float | None = None

    # 结果统计
    success_count: int = 0
    failure_count: int = 0
    timeout_count: int = 0

    # 性能统计
    total_execution_time_ms: int = 0
    avg_execution_time_ms: float = 0.0

    # 满意度统计
    total_satisfaction: int = 0
    avg_satisfaction: float = 0.0
    satisfaction_count: int = 0

    # 贡献度评估
    contribution_score: float = 0.0  # 综合贡献分 0-1

    # 时间衰减因子
    recency_score: float = 1.0

    @property
    def success_rate(self) -> float:
        """成功率"""
        total = self.success_count + self.failure_count + self.timeout_count
        if total == 0:
            return 0.0
        return self.success_count / total

    @property
    def failure_rate(self) -> float:
        """失败率"""
        total = self.success_count + self.failure_count + self.timeout_count
        if total == 0:
            return 0.0
        return (self.failure_count + self.timeout_count) / total

    @property
    def is_effective(self) -> bool:
        """是否有效（成功率>70%且使用次数>=3）"""
        return self.success_rate > 0.7 and self.usage_count >= 3

    @property
    def is_ineffective(self) -> bool:
        """是否无效（成功率<30%且使用次数>=5）"""
        return self.success_rate < 0.3 and self.usage_count >= 5

    @property
    def needs_review(self) -> bool:
        """是否需要审核（成功率低但有一定使用次数）"""
        return 0.3 <= self.success_rate < 0.5 and self.usage_count >= 5

    def update_with_outcome(
        self,
        success: bool,
        execution_time_ms: int | None = None,
        satisfaction: int | None = None
    ):
        """更新统计"""
        self.usage_count += 1
        self.last_used_at = time.time()
        if self.first_used_at is None:
            self.first_used_at = self.last_used_at

        if success:
            self.success_count += 1
        else:
            self.failure_count += 1

        if execution_time_ms:
            self.total_execution_time_ms += execution_time_ms
            self.avg_execution_time_ms = self.total_execution_time_ms / self.usage_count

        if satisfaction:
            self.total_satisfaction += satisfaction
            self.satisfaction_count += 1
            self.avg_satisfaction = self.total_satisfaction / self.satisfaction_count

        # 更新贡献度分数
        self._update_contribution_score()

    def _update_contribution_score(self):
        """更新贡献度分数"""
        # 综合评分 = 成功率 * 0.5 + 满意度 * 0.3 + 时效性 * 0.2
        satisfaction_normalized = self.avg_satisfaction / 10.0 if self.avg_satisfaction > 0 else 0.5

        self.contribution_score = (
            self.success_rate * 0.5 +
            satisfaction_normalized * 0.3 +
            self.recency_score * 0.2
        )

    def update_recency_score(self):
        """更新时效性分数"""
        if self.last_used_at is None:
            self.recency_score = 0.5
            return

        age_days = (time.time() - self.last_used_at) / 86400

        if age_days <= 7:
            self.recency_score = 1.0
        elif age_days <= 30:
            self.recency_score = 0.9
        elif age_days <= 90:
            self.recency_score = 0.75
        elif age_days <= 180:
            self.recency_score = 0.6
        else:
            self.recency_score = 0.3

    def to_dict(self) -> dict[str, Any]:
        return {
            "experience_id": self.experience_id,
            "usage_count": self.usage_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "timeout_count": self.timeout_count,
            "success_rate": round(self.success_rate, 3),
            "failure_rate": round(self.failure_rate, 3),
            "avg_execution_time_ms": round(self.avg_execution_time_ms, 0),
            "avg_satisfaction": round(self.avg_satisfaction, 1),
            "contribution_score": round(self.contribution_score, 3),
            "is_effective": self.is_effective,
            "is_ineffective": self.is_ineffective,
            "needs_review": self.needs_review,
            "first_used_at": self.first_used_at,
            "last_used_at": self.last_used_at
        }


@dataclass
class TaskOutcomeRecord:
    """任务结果记录"""
    task_id: str
    task_type: str
    success: bool

    # 使用的经验
    experience_ids: list[str] = field(default_factory=list)

    # 结果详情
    execution_time_ms: int | None = None
    satisfaction: int | None = None
    error_message: str | None = None

    # 时间戳
    completed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExperienceEffectivenessTracker:
    """
    经验效果追踪器

    功能:
    1. 记录每条经验的使用和结果
    2. 统计经验的成功率、贡献度
    3. 识别有效/无效经验
    4. 支持经验归因分析

    Usage:
        tracker = ExperienceEffectivenessTracker()

        # 记录经验使用
        tracker.track_usage(exp_id="exp_123", task_id="task_456")

        # 任务完成后更新效果
        tracker.track_outcome(task_id="task_456", success=True)

        # 获取经验统计
        stats = tracker.get_experience_stats("exp_123")

        # 获取排行榜
        top_experiences = tracker.get_effectiveness_leaderboard()
    """

    def __init__(self, storage_path: str | None = None):
        """
        初始化效果追踪器

        Args:
            storage_path: 数据存储路径
        """
        self.storage_path = storage_path or "data/experience_effectiveness.json"

        # 内存存储
        self._stats: dict[str, ExperienceEffectivenessStats] = {}  # exp_id -> stats
        self._usage_events: list[ExperienceUsageEvent] = []
        self._outcome_records: dict[str, TaskOutcomeRecord] = {}  # task_id -> outcome
        self._task_exp_map: dict[str, list[str]] = defaultdict(list)  # task_id -> exp_ids

        # 加载历史数据
        self._load_data()

        logger.info(f"[ExperienceEffectivenessTracker] 初始化完成，已加载 {len(self._stats)} 条经验统计")

    def track_usage(
        self,
        experience_id: str,
        task_id: str,
        task_type: str = "general",
        role: str = "reference",
        position: int = 0,
        user_id: str = "default",
        session_id: str | None = None
    ) -> str:
        """
        记录经验被使用

        Args:
            experience_id: 经验ID
            task_id: 任务ID
            task_type: 任务类型
            role: 经验角色
            position: 位置序号
            user_id: 用户ID
            session_id: 会话ID

        Returns:
            event_id: 事件ID
        """
        event_id = hashlib.md5(
            f"{experience_id}:{task_id}:{time.time()}".encode()
        ).hexdigest()[:12]

        event = ExperienceUsageEvent(
            event_id=event_id,
            experience_id=experience_id,
            task_id=task_id,
            task_type=task_type,
            used_at=time.time(),
            role=role,
            position=position,
            user_id=user_id,
            session_id=session_id
        )

        self._usage_events.append(event)
        self._task_exp_map[task_id].append(experience_id)

        # 初始化经验统计
        if experience_id not in self._stats:
            self._stats[experience_id] = ExperienceEffectivenessStats(experience_id=experience_id)

        logger.debug(f"[EffectivenessTracker] 经验 {experience_id[:8]} 被用于任务 {task_id[:8]}")

        return event_id

    def track_batch_usage(
        self,
        experience_ids: list[str],
        task_id: str,
        task_type: str = "general",
        user_id: str = "default"
    ):
        """
        批量记录经验使用

        Args:
            experience_ids: 经验ID列表
            task_id: 任务ID
            task_type: 任务类型
            user_id: 用户ID
        """
        for i, exp_id in enumerate(experience_ids):
            self.track_usage(
                experience_id=exp_id,
                task_id=task_id,
                task_type=task_type,
                position=i,
                user_id=user_id
            )

    def track_outcome(
        self,
        task_id: str,
        success: bool,
        execution_time_ms: int | None = None,
        satisfaction: int | None = None,
        error_message: str | None = None
    ):
        """
        记录任务结果，更新相关经验统计

        Args:
            task_id: 任务ID
            success: 是否成功
            execution_time_ms: 执行耗时
            satisfaction: 用户满意度
            error_message: 错误信息
        """
        # 记录结果
        outcome = TaskOutcomeRecord(
            task_id=task_id,
            task_type="general",  # 可以从usage事件中获取
            success=success,
            experience_ids=self._task_exp_map.get(task_id, []),
            execution_time_ms=execution_time_ms,
            satisfaction=satisfaction,
            error_message=error_message,
            completed_at=time.time()
        )

        self._outcome_records[task_id] = outcome

        # 更新相关经验的统计
        for exp_id in self._task_exp_map.get(task_id, []):
            if exp_id in self._stats:
                self._stats[exp_id].update_with_outcome(
                    success=success,
                    execution_time_ms=execution_time_ms,
                    satisfaction=satisfaction
                )

        # 持久化
        self._persist_data()

        logger.info(
            f"[EffectivenessTracker] 任务 {task_id[:8]} 完成: success={success}, "
            f"影响了 {len(self._task_exp_map.get(task_id, []))} 条经验"
        )

    def get_experience_stats(self, experience_id: str) -> ExperienceEffectivenessStats | None:
        """获取单条经验的统计"""
        return self._stats.get(experience_id)

    def get_all_stats(self) -> list[ExperienceEffectivenessStats]:
        """获取所有经验的统计列表"""
        return list(self._stats.values())

    def get_effectiveness_leaderboard(
        self,
        limit: int = 20,
        min_usage: int = 3,
        task_type: str | None = None
    ) -> list[dict[str, Any]]:
        """
        获取经验效果排行榜

        Args:
            limit: 返回数量
            min_usage: 最小使用次数（确保统计意义）
            task_type: 任务类型过滤

        Returns:
            排行榜列表
        """
        # 过滤符合条件的经验
        candidates = []
        for exp_id, stats in self._stats.items():
            if stats.usage_count >= min_usage:
                # 如果指定了任务类型，进一步过滤
                if task_type:
                    # 检查该经验是否用于指定类型任务
                    related_events = [
                        e for e in self._usage_events
                        if e.experience_id == exp_id and e.task_type == task_type
                    ]
                    if not related_events:
                        continue

                candidates.append(stats)

        # 按贡献度排序
        candidates.sort(key=lambda s: s.contribution_score, reverse=True)

        return [stats.to_dict() for stats in candidates[:limit]]

    def get_ineffective_experiences(
        self,
        threshold: float = 0.3,
        min_usage: int = 5
    ) -> list[dict[str, Any]]:
        """
        获取无效经验列表（用于自动淘汰）

        Args:
            threshold: 成功率阈值
            min_usage: 最小使用次数

        Returns:
            无效经验列表
        """
        ineffective = []
        for _exp_id, stats in self._stats.items():
            if stats.usage_count >= min_usage and stats.success_rate < threshold:
                ineffective.append(stats.to_dict())

        # 按失败率排序
        ineffective.sort(key=lambda x: x['failure_rate'], reverse=True)
        return ineffective

    def get_needs_review_experiences(self) -> list[dict[str, Any]]:
        """获取需要审核的经验列表"""
        needs_review = []
        for _exp_id, stats in self._stats.items():
            if stats.needs_review:
                needs_review.append(stats.to_dict())

        return needs_review

    def get_global_stats(self) -> dict[str, Any]:
        """获取全局统计信息"""
        if not self._stats:
            return {
                "total_experiences": 0,
                "total_usage": 0,
                "overall_success_rate": 0.0
            }

        total_usage = sum(s.usage_count for s in self._stats.values())
        total_success = sum(s.success_count for s in self._stats.values())

        effective_count = sum(1 for s in self._stats.values() if s.is_effective)
        ineffective_count = sum(1 for s in self._stats.values() if s.is_ineffective)

        return {
            "total_experiences": len(self._stats),
            "total_usage": total_usage,
            "overall_success_rate": round(total_success / total_usage, 3) if total_usage > 0 else 0,
            "effective_count": effective_count,
            "ineffective_count": ineffective_count,
            "needs_review_count": len(self.get_needs_review_experiences()),
            "avg_contribution_score": round(
                sum(s.contribution_score for s in self._stats.values()) / len(self._stats), 3
            )
        }

    def get_task_attribution_analysis(self, task_id: str) -> dict[str, Any] | None:
        """
        获取任务的经验归因分析

        分析哪些经验对任务成功/失败有贡献
        """
        if task_id not in self._outcome_records:
            return None

        outcome = self._outcome_records[task_id]
        exp_ids = self._task_exp_map.get(task_id, [])

        attribution = []
        for exp_id in exp_ids:
            stats = self._stats.get(exp_id)
            if stats:
                attribution.append({
                    "experience_id": exp_id,
                    "success_rate": stats.success_rate,
                    "contribution_score": stats.contribution_score,
                    "usage_count": stats.usage_count
                })

        return {
            "task_id": task_id,
            "success": outcome.success,
            "experiences_used": len(exp_ids),
            "attribution": attribution
        }

    def get_experience_usage_history(
        self,
        experience_id: str,
        limit: int = 20
    ) -> list[dict[str, Any]]:
        """获取经验使用历史"""
        events = [
            e.to_dict() for e in self._usage_events
            if e.experience_id == experience_id
        ]
        events.sort(key=lambda x: x['used_at'], reverse=True)

        # 补充结果信息
        result = []
        for event in events[:limit]:
            task_id = event['task_id']
            outcome = self._outcome_records.get(task_id)
            if outcome:
                event['task_success'] = outcome.success
                event['execution_time_ms'] = outcome.execution_time_ms
            result.append(event)

        return result

    def _load_data(self):
        """从文件加载数据"""
        try:
            import os
            if os.path.exists(self.storage_path):
                with open(self.storage_path, encoding='utf-8') as f:
                    data = json.load(f)

                # 加载经验统计
                for exp_id, stats_data in data.get('stats', {}).items():
                    stats = ExperienceEffectivenessStats(
                        experience_id=exp_id,
                        usage_count=stats_data.get('usage_count', 0),
                        success_count=stats_data.get('success_count', 0),
                        failure_count=stats_data.get('failure_count', 0),
                        timeout_count=stats_data.get('timeout_count', 0),
                        total_execution_time_ms=stats_data.get('total_execution_time_ms', 0),
                        total_satisfaction=stats_data.get('total_satisfaction', 0),
                        satisfaction_count=stats_data.get('satisfaction_count', 0),
                        contribution_score=stats_data.get('contribution_score', 0.0)
                    )
                    stats.first_used_at = stats_data.get('first_used_at')
                    stats.last_used_at = stats_data.get('last_used_at')
                    self._stats[exp_id] = stats

                logger.info(f"[EffectivenessTracker] 加载了 {len(self._stats)} 条经验统计")
        except Exception as e:
            logger.warning(f"[EffectivenessTracker] 加载数据失败: {e}")

    def _persist_data(self):
        """持久化数据到文件"""
        try:
            import os
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)

            data = {
                'stats': {
                    exp_id: stats.to_dict()
                    for exp_id, stats in self._stats.items()
                },
                'updated_at': datetime.now().isoformat()
            }

            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[EffectivenessTracker] 持久化数据失败: {e}")


# ═══════════════════════════════════════════════════════════════════
# 便捷函数和全局实例
# ═══════════════════════════════════════════════════════════════════

_effectiveness_tracker: ExperienceEffectivenessTracker | None = None


def get_effectiveness_tracker(refresh: bool = False) -> ExperienceEffectivenessTracker:
    """获取效果追踪器全局实例"""
    global _effectiveness_tracker
    if _effectiveness_tracker is None or refresh:
        _effectiveness_tracker = ExperienceEffectivenessTracker()
    return _effectiveness_tracker
