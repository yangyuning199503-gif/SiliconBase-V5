#!/usr/bin/env python3
"""
经验注入 A/B 测试框架
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
对同一类任务进行随机分组对比，量化经验注入的真实效果

核心概念:
- A组 (Treatment): 使用经验注入
- B组 (Control): 不使用经验注入
- 对比指标: 成功率、完成时间、用户满意度、API调用次数

Author: Agent-6 Experience Optimizer
Version: 1.0.0
"""

import hashlib
import json
import logging
import random
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ABTestGroup(Enum):
    """A/B测试分组"""
    TREATMENT = "A"  # 实验组：使用经验注入
    CONTROL = "B"    # 对照组：不使用经验注入


class TaskOutcome(Enum):
    """任务执行结果"""
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    ABORTED = "aborted"


@dataclass
class TaskExecutionRecord:
    """任务执行记录"""
    # 标识
    task_id: str
    task_type: str
    task_hash: str

    # 分组信息
    group: ABTestGroup

    # 任务内容
    task_description: str
    context: dict[str, Any] = field(default_factory=dict)

    # 执行结果
    outcome: TaskOutcome | None = None
    success: bool | None = None

    # 性能指标
    execution_time_ms: int | None = None
    api_calls_count: int | None = None
    token_usage: int | None = None
    retry_count: int | None = None

    # 经验注入相关
    experiences_injected: list[str] = field(default_factory=list)
    experience_count: int = 0

    # 用户反馈
    user_satisfaction: int | None = None  # 1-10
    user_feedback: str | None = None

    # 时间戳
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None

    # 元数据
    user_id: str = "default"
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data['group'] = self.group.value
        data['outcome'] = self.outcome.value if self.outcome else None
        return data


@dataclass
class ABTestMetrics:
    """A/B测试指标统计"""
    # 样本量
    total_tasks: int = 0
    treatment_count: int = 0
    control_count: int = 0

    # 成功率
    treatment_success_rate: float = 0.0
    control_success_rate: float = 0.0
    success_rate_lift: float = 0.0  # 提升幅度

    # 完成时间 (毫秒)
    treatment_avg_time_ms: float = 0.0
    control_avg_time_ms: float = 0.0
    time_improvement_pct: float = 0.0  # 改善百分比

    # 用户满意度
    treatment_avg_satisfaction: float = 0.0
    control_avg_satisfaction: float = 0.0
    satisfaction_lift: float = 0.0

    # API效率
    treatment_avg_api_calls: float = 0.0
    control_avg_api_calls: float = 0.0
    api_efficiency_improvement: float = 0.0

    # 统计显著性 (简化版p值估计)
    statistical_significance: float | None = None
    confidence_level: str = "N/A"  # "high" | "medium" | "low" | "N/A"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ABTestFramework:
    """
    A/B测试框架

    功能:
    1. 任务随机分组 (A组: 使用经验注入, B组: 不使用)
    2. 追踪任务执行结果
    3. 统计分析对比
    4. 效果量化报告

    Usage:
        ab_framework = ABTestFramework()

        # 任务开始时分配分组
        group = ab_framework.assign_group("任务描述", "task_type")

        # 根据分组决定是否使用经验注入
        use_experience = (group == ABTestGroup.TREATMENT)

        # 任务完成后记录结果
        ab_framework.record_outcome(task_id, success=True, execution_time_ms=5000)

        # 获取对比报告
        report = ab_framework.get_comparison_report("task_type")
    """

    # 默认分组比例 (A组 50%, B组 50%)
    DEFAULT_TREATMENT_RATIO = 0.5

    def __init__(
        self,
        storage_path: str | None = None,
        treatment_ratio: float = DEFAULT_TREATMENT_RATIO,
        min_sample_size: int = 10
    ):
        """
        初始化A/B测试框架

        Args:
            storage_path: 数据存储路径
            treatment_ratio: A组(实验组)比例，默认0.5
            min_sample_size: 最小样本量要求
        """
        self.storage_path = storage_path or "data/experience_ab_test.json"
        self.treatment_ratio = treatment_ratio
        self.min_sample_size = min_sample_size

        # 内存存储
        self._records: dict[str, TaskExecutionRecord] = {}  # task_id -> record
        self._task_type_records: dict[str, list[str]] = defaultdict(list)  # task_type -> task_ids

        # 加载历史数据
        self._load_data()

        logger.info(f"[ABTestFramework] 初始化完成，治疗组比例: {treatment_ratio:.0%}")

    def assign_group(
        self,
        task_description: str,
        task_type: str,
        user_id: str = "default",
        context: dict[str, Any] | None = None
    ) -> tuple[ABTestGroup, str]:
        """
        为任务分配A/B测试分组

        Args:
            task_description: 任务描述
            task_type: 任务类型
            user_id: 用户ID
            context: 上下文信息

        Returns:
            (group, task_id): 分组和任务ID
        """
        # 生成任务ID
        task_hash = hashlib.md5(
            f"{task_type}:{task_description}:{time.time()}:{random.random()}".encode()
        ).hexdigest()[:16]

        # 随机分组（使用哈希确保同一任务描述稳定分组）
        hash_val = int(hashlib.md5(f"{user_id}:{task_type}".encode()).hexdigest(), 16)
        is_treatment = (hash_val % 100) < (self.treatment_ratio * 100)
        group = ABTestGroup.TREATMENT if is_treatment else ABTestGroup.CONTROL

        # 创建记录
        record = TaskExecutionRecord(
            task_id=task_hash,
            task_type=task_type,
            task_hash=task_hash,
            group=group,
            task_description=task_description,
            context=context or {},
            user_id=user_id
        )

        # 存储
        self._records[task_hash] = record
        self._task_type_records[task_type].append(task_hash)

        logger.debug(f"[ABTestFramework] 任务 {task_hash[:8]} 分配到 {group.value} 组")

        return group, task_hash

    def record_experience_usage(
        self,
        task_id: str,
        experience_ids: list[str]
    ):
        """
        记录任务使用的经验

        Args:
            task_id: 任务ID
            experience_ids: 使用的经验ID列表
        """
        if task_id not in self._records:
            logger.warning(f"[ABTestFramework] 未知任务ID: {task_id}")
            return

        record = self._records[task_id]
        record.experiences_injected = experience_ids
        record.experience_count = len(experience_ids)

    def record_start(self, task_id: str):
        """记录任务开始"""
        if task_id in self._records:
            self._records[task_id].started_at = time.time()

    def record_outcome(
        self,
        task_id: str,
        success: bool,
        outcome: TaskOutcome = TaskOutcome.SUCCESS,
        execution_time_ms: int | None = None,
        api_calls_count: int | None = None,
        token_usage: int | None = None,
        retry_count: int | None = None,
        user_satisfaction: int | None = None,
        user_feedback: str | None = None
    ):
        """
        记录任务执行结果

        Args:
            task_id: 任务ID
            success: 是否成功
            outcome: 执行结果类型
            execution_time_ms: 执行耗时(毫秒)
            api_calls_count: API调用次数
            token_usage: Token使用量
            retry_count: 重试次数
            user_satisfaction: 用户满意度(1-10)
            user_feedback: 用户反馈文本
        """
        if task_id not in self._records:
            logger.warning(f"[ABTestFramework] 未知任务ID: {task_id}")
            return

        record = self._records[task_id]
        record.success = success
        record.outcome = outcome
        record.completed_at = time.time()

        # 计算执行时间
        if execution_time_ms:
            record.execution_time_ms = execution_time_ms
        elif record.started_at:
            record.execution_time_ms = int((record.completed_at - record.started_at) * 1000)

        record.api_calls_count = api_calls_count
        record.token_usage = token_usage
        record.retry_count = retry_count
        record.user_satisfaction = user_satisfaction
        record.user_feedback = user_feedback

        # 持久化
        self._persist_data()

        logger.info(f"[ABTestFramework] 任务 {task_id[:8]} 完成: success={success}, group={record.group.value}")

    def get_metrics(self, task_type: str | None = None) -> ABTestMetrics:
        """
        获取A/B测试指标统计

        Args:
            task_type: 任务类型过滤，None表示所有类型

        Returns:
            ABTestMetrics 指标统计对象
        """
        # 获取相关记录
        if task_type:
            task_ids = self._task_type_records.get(task_type, [])
            records = [self._records[tid] for tid in task_ids if tid in self._records]
        else:
            records = list(self._records.values())

        # 过滤已完成的任务
        completed = [r for r in records if r.success is not None]

        if not completed:
            return ABTestMetrics()

        # 分组统计
        treatment_records = [r for r in completed if r.group == ABTestGroup.TREATMENT]
        control_records = [r for r in completed if r.group == ABTestGroup.CONTROL]

        metrics = ABTestMetrics(
            total_tasks=len(completed),
            treatment_count=len(treatment_records),
            control_count=len(control_records)
        )

        # 成功率统计
        if treatment_records:
            treatment_success = sum(1 for r in treatment_records if r.success)
            metrics.treatment_success_rate = treatment_success / len(treatment_records)

        if control_records:
            control_success = sum(1 for r in control_records if r.success)
            metrics.control_success_rate = control_success / len(control_records)

        # 提升幅度
        if metrics.control_success_rate > 0:
            metrics.success_rate_lift = (
                (metrics.treatment_success_rate - metrics.control_success_rate)
                / metrics.control_success_rate
            )

        # 执行时间统计
        treatment_times = [r.execution_time_ms for r in treatment_records if r.execution_time_ms]
        control_times = [r.execution_time_ms for r in control_records if r.execution_time_ms]

        if treatment_times:
            metrics.treatment_avg_time_ms = sum(treatment_times) / len(treatment_times)
        if control_times:
            metrics.control_avg_time_ms = sum(control_times) / len(control_times)

        if metrics.control_avg_time_ms > 0:
            metrics.time_improvement_pct = (
                (metrics.control_avg_time_ms - metrics.treatment_avg_time_ms)
                / metrics.control_avg_time_ms * 100
            )

        # 用户满意度统计
        treatment_satisfaction = [r.user_satisfaction for r in treatment_records if r.user_satisfaction]
        control_satisfaction = [r.user_satisfaction for r in control_records if r.user_satisfaction]

        if treatment_satisfaction:
            metrics.treatment_avg_satisfaction = sum(treatment_satisfaction) / len(treatment_satisfaction)
        if control_satisfaction:
            metrics.control_avg_satisfaction = sum(control_satisfaction) / len(control_satisfaction)

        if metrics.control_avg_satisfaction > 0:
            metrics.satisfaction_lift = (
                (metrics.treatment_avg_satisfaction - metrics.control_avg_satisfaction)
                / metrics.control_avg_satisfaction
            )

        # API调用统计
        treatment_apis = [r.api_calls_count for r in treatment_records if r.api_calls_count]
        control_apis = [r.api_calls_count for r in control_records if r.api_calls_count]

        if treatment_apis:
            metrics.treatment_avg_api_calls = sum(treatment_apis) / len(treatment_apis)
        if control_apis:
            metrics.control_avg_api_calls = sum(control_apis) / len(control_apis)

        if metrics.control_avg_api_calls > 0:
            metrics.api_efficiency_improvement = (
                (metrics.control_avg_api_calls - metrics.treatment_avg_api_calls)
                / metrics.control_avg_api_calls * 100
            )

        # 统计显著性评估（简化）
        metrics.confidence_level = self._calculate_confidence_level(
            len(treatment_records), len(control_records),
            metrics.treatment_success_rate, metrics.control_success_rate
        )

        return metrics

    def get_comparison_report(self, task_type: str | None = None) -> dict[str, Any]:
        """
        获取A/B测试对比报告

        Args:
            task_type: 任务类型过滤

        Returns:
            详细的对比报告字典
        """
        metrics = self.get_metrics(task_type)

        report = {
            "generated_at": datetime.now().isoformat(),
            "task_type": task_type or "all",
            "sample_size": {
                "total": metrics.total_tasks,
                "treatment_group": metrics.treatment_count,
                "control_group": metrics.control_count,
                "is_sufficient": metrics.total_tasks >= self.min_sample_size
            },
            "success_rate": {
                "treatment": f"{metrics.treatment_success_rate:.1%}",
                "control": f"{metrics.control_success_rate:.1%}",
                "lift": f"{metrics.success_rate_lift:+.1%}",
                "is_better": metrics.treatment_success_rate > metrics.control_success_rate
            },
            "execution_time": {
                "treatment_avg_ms": round(metrics.treatment_avg_time_ms, 0),
                "control_avg_ms": round(metrics.control_avg_time_ms, 0),
                "improvement": f"{metrics.time_improvement_pct:+.1f}%",
                "is_faster": metrics.treatment_avg_time_ms < metrics.control_avg_time_ms
            },
            "user_satisfaction": {
                "treatment_avg": round(metrics.treatment_avg_satisfaction, 1),
                "control_avg": round(metrics.control_avg_satisfaction, 1),
                "lift": f"{metrics.satisfaction_lift:+.1%}"
            },
            "api_efficiency": {
                "treatment_avg_calls": round(metrics.treatment_avg_api_calls, 1),
                "control_avg_calls": round(metrics.control_avg_api_calls, 1),
                "improvement": f"{metrics.api_efficiency_improvement:+.1f}%"
            },
            "statistical_confidence": metrics.confidence_level,
            "conclusion": self._generate_conclusion(metrics)
        }

        return report

    def get_task_type_list(self) -> list[str]:
        """获取所有任务类型列表"""
        return list(self._task_type_records.keys())

    def get_recent_records(
        self,
        limit: int = 50,
        task_type: str | None = None
    ) -> list[dict[str, Any]]:
        """获取最近的执行记录"""
        if task_type:
            task_ids = self._task_type_records.get(task_type, [])
            records = [self._records[tid] for tid in task_ids if tid in self._records]
        else:
            records = list(self._records.values())

        # 按时间排序
        records.sort(key=lambda r: r.created_at, reverse=True)

        return [r.to_dict() for r in records[:limit]]

    @staticmethod
    def _calculate_confidence_level(
        n_treatment: int,
        n_control: int,
        p_treatment: float,
        p_control: float
    ) -> str:
        """
        计算统计置信度（简化版）

        返回: "high" | "medium" | "low" | "N/A"
        """
        if n_treatment < 10 or n_control < 10:
            return "N/A"

        # 简化：使用样本量和差异大小来估算
        diff = abs(p_treatment - p_control)
        min_n = min(n_treatment, n_control)

        if min_n >= 100 and diff > 0.1:
            return "high"
        elif min_n >= 30 and diff > 0.05:
            return "medium"
        elif min_n >= 10:
            return "low"

        return "N/A"

    def _generate_conclusion(self, metrics: ABTestMetrics) -> str:
        """生成结论文本"""
        if metrics.total_tasks < self.min_sample_size:
            return f"样本量不足（当前{metrics.total_tasks}，需要{self.min_sample_size}），暂无法得出结论"

        conclusions = []

        # 成功率结论
        if metrics.success_rate_lift > 0.05:
            conclusions.append(f"经验注入显著提升成功率 {metrics.success_rate_lift:.1%}")
        elif metrics.success_rate_lift < -0.05:
            conclusions.append(f"经验注入导致成功率下降 {abs(metrics.success_rate_lift):.1%}")
        else:
            conclusions.append("经验注入对成功率影响不显著")

        # 效率结论
        if metrics.time_improvement_pct > 10:
            conclusions.append(f"执行时间缩短 {metrics.time_improvement_pct:.1f}%")
        elif metrics.time_improvement_pct < -10:
            conclusions.append(f"执行时间增加 {abs(metrics.time_improvement_pct):.1f}%")

        return "；".join(conclusions) if conclusions else "暂无明确结论"

    def _load_data(self):
        """从文件加载数据"""
        try:
            import os
            if os.path.exists(self.storage_path):
                with open(self.storage_path, encoding='utf-8') as f:
                    data = json.load(f)

                for record_data in data.get('records', []):
                    record = TaskExecutionRecord(
                        task_id=record_data['task_id'],
                        task_type=record_data['task_type'],
                        task_hash=record_data['task_hash'],
                        group=ABTestGroup(record_data['group']),
                        task_description=record_data['task_description'],
                        context=record_data.get('context', {}),
                        outcome=TaskOutcome(record_data['outcome']) if record_data.get('outcome') else None,
                        success=record_data.get('success'),
                        execution_time_ms=record_data.get('execution_time_ms'),
                        api_calls_count=record_data.get('api_calls_count'),
                        token_usage=record_data.get('token_usage'),
                        retry_count=record_data.get('retry_count'),
                        experiences_injected=record_data.get('experiences_injected', []),
                        experience_count=record_data.get('experience_count', 0),
                        user_satisfaction=record_data.get('user_satisfaction'),
                        user_feedback=record_data.get('user_feedback'),
                        created_at=record_data.get('created_at', time.time()),
                        started_at=record_data.get('started_at'),
                        completed_at=record_data.get('completed_at'),
                        user_id=record_data.get('user_id', 'default'),
                        session_id=record_data.get('session_id')
                    )
                    self._records[record.task_id] = record
                    self._task_type_records[record.task_type].append(record.task_id)

                logger.info(f"[ABTestFramework] 加载了 {len(self._records)} 条A/B测试记录")
        except Exception as e:
            logger.warning(f"[ABTestFramework] 加载数据失败: {e}")

    def _persist_data(self):
        """持久化数据到文件"""
        try:
            import os
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)

            data = {
                'records': [r.to_dict() for r in self._records.values()],
                'updated_at': datetime.now().isoformat()
            }

            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[ABTestFramework] 持久化数据失败: {e}")


# ═══════════════════════════════════════════════════════════════════
# 便捷函数和全局实例
# ═══════════════════════════════════════════════════════════════════

_ab_test_framework: ABTestFramework | None = None


def get_ab_test_framework(refresh: bool = False) -> ABTestFramework:
    """获取A/B测试框架全局实例"""
    global _ab_test_framework
    if _ab_test_framework is None or refresh:
        _ab_test_framework = ABTestFramework()
    return _ab_test_framework


def should_use_experience(task_description: str, task_type: str, user_id: str = "default") -> tuple[bool, str]:
    """
    便捷函数：判断是否应该使用经验注入

    Returns:
        (use_experience, task_id): 是否使用经验注入，以及任务ID
    """
    framework = get_ab_test_framework()
    group, task_id = framework.assign_group(task_description, task_type, user_id)
    return group == ABTestGroup.TREATMENT, task_id
