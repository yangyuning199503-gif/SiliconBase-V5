#!/usr/bin/env python3
"""
经验自动淘汰引擎
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
定期清理低质量经验，保持经验库的活力和有效性

淘汰策略:
1. 低成功率淘汰: success_rate < 30% 且 usage_count >= 5
2. 长期未使用淘汰: last_used > 180天 且 usage_count < 3
3. 重复/冗余淘汰: 内容相似度 > 90% 的经验合并
4. 过时经验降级: 成功率下降的活跃经验降低权重

处理流程:
标记 → 审核 → 降级/归档 → 删除

Author: Agent-6 Experience Optimizer
Version: 1.0.0
"""

import hashlib
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class PurgeAction(Enum):
    """淘汰操作类型"""
    MARK_REVIEW = "mark_review"       # 标记待审核
    DEMOTE_WEIGHT = "demote_weight"   # 降低权重
    ARCHIVE = "archive"               # 归档
    DELETE = "delete"                 # 删除
    MERGE = "merge"                   # 合并


class ExperienceStatus(Enum):
    """经验状态"""
    ACTIVE = "active"           # 活跃
    UNDER_REVIEW = "review"     # 审核中
    DEMOTED = "demoted"         # 已降级
    ARCHIVED = "archived"       # 已归档
    PURGED = "purged"           # 已淘汰


@dataclass
class PurgeCandidate:
    """淘汰候选"""
    experience_id: str

    # 原因
    reason: str
    reason_code: str

    # 统计数据
    success_rate: float
    usage_count: int
    last_used_days: int | None = None

    # 建议操作
    recommended_action: PurgeAction = PurgeAction.MARK_REVIEW

    # 优先级 (1-5, 5最高)
    priority: int = 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "experience_id": self.experience_id,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "success_rate": round(self.success_rate, 3),
            "usage_count": self.usage_count,
            "last_used_days": self.last_used_days,
            "recommended_action": self.recommended_action.value,
            "priority": self.priority
        }


@dataclass
class PurgeRecord:
    """淘汰记录"""
    record_id: str
    experience_id: str
    action: PurgeAction
    reason: str
    executed_at: float

    # 执行前状态
    before_stats: dict[str, Any] = field(default_factory=dict)

    # 执行结果
    success: bool = True
    details: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "experience_id": self.experience_id,
            "action": self.action.value,
            "reason": self.reason,
            "executed_at": self.executed_at,
            "before_stats": self.before_stats,
            "success": self.success,
            "details": self.details
        }


class AutoPurgeEngine:
    """
    经验自动淘汰引擎

    功能:
    1. 扫描识别需要淘汰的经验
    2. 分级处理（标记、降级、归档、删除）
    3. 合并重复经验
    4. 生成淘汰报告

    Usage:
        purge_engine = AutoPurgeEngine()

        # 扫描候选
        candidates = purge_engine.scan_candidates()

        # 执行淘汰
        results = purge_engine.execute_purge(candidates)

        # 获取报告
        report = purge_engine.get_purge_report()
    """

    # 默认阈值配置
    DEFAULT_THRESHOLDS = {
        "low_success_rate": 0.3,        # 成功率低于30%
        "min_usage_for_purge": 5,       # 至少使用5次才考虑淘汰
        "unused_days_threshold": 180,   # 180天未使用
        "min_usage_for_unused": 3,      # 使用少于3次才算"未充分使用"
        "similarity_threshold": 0.9,    # 相似度90%以上考虑合并
        "demote_threshold": 0.5,        # 成功率50%以下降级
    }

    def __init__(
        self,
        storage_path: str | None = None,
        thresholds: dict[str, float] | None = None,
        dry_run: bool = True  # 默认只扫描不执行
    ):
        """
        初始化淘汰引擎

        Args:
            storage_path: 数据存储路径
            thresholds: 阈值配置
            dry_run: 是否仅模拟运行
        """
        self.storage_path = storage_path or "data/experience_purge_records.json"
        self.archive_path = storage_path or "data/experience_archive.json"
        self.thresholds = {**self.DEFAULT_THRESHOLDS, **(thresholds or {})}
        self.dry_run = dry_run

        # 状态管理
        self._experience_status: dict[str, ExperienceStatus] = {}
        self._experience_weights: dict[str, float] = {}  # 经验权重
        self._purge_records: list[PurgeRecord] = []

        # 加载数据
        self._load_data()

        logger.info(f"[AutoPurgeEngine] 初始化完成，dry_run={dry_run}")

    async def scan_candidates(
        self,
        effectiveness_tracker=None,
        vector_memory=None
    ) -> list[PurgeCandidate]:
        """
        扫描需要淘汰的经验候选

        Args:
            effectiveness_tracker: 效果追踪器实例
            vector_memory: 向量内存实例

        Returns:
            候选列表
        """
        candidates = []

        # 导入依赖
        if effectiveness_tracker is None:
            from .experience_effectiveness_tracker import get_effectiveness_tracker
            effectiveness_tracker = get_effectiveness_tracker()

        # 1. 扫描低成功率经验
        low_success = self._scan_low_success_experiences(effectiveness_tracker)
        candidates.extend(low_success)

        # 2. 扫描长期未使用的经验
        unused = self._scan_unused_experiences(effectiveness_tracker)
        candidates.extend(unused)

        # 3. 扫描需要降级的经验
        demote_candidates = self._scan_demote_candidates(effectiveness_tracker)
        candidates.extend(demote_candidates)

        # 4. 扫描重复经验（如果有vector_memory）
        if vector_memory:
            duplicates = await self._scan_duplicate_experiences(vector_memory)
            candidates.extend(duplicates)

        # 去重并按优先级排序
        seen = set()
        unique_candidates = []
        for c in candidates:
            if c.experience_id not in seen:
                seen.add(c.experience_id)
                unique_candidates.append(c)

        unique_candidates.sort(key=lambda x: x.priority, reverse=True)

        logger.info(f"[AutoPurgeEngine] 扫描到 {len(unique_candidates)} 个淘汰候选")

        return unique_candidates

    def _scan_low_success_experiences(
        self,
        tracker
    ) -> list[PurgeCandidate]:
        """扫描低成功率经验"""
        candidates = []

        ineffective = tracker.get_ineffective_experiences(
            threshold=self.thresholds["low_success_rate"],
            min_usage=int(self.thresholds["min_usage_for_purge"])
        )

        for stats in ineffective:
            candidate = PurgeCandidate(
                experience_id=stats["experience_id"],
                reason=f"成功率过低 ({stats['success_rate']:.1%})",
                reason_code="LOW_SUCCESS_RATE",
                success_rate=stats["success_rate"],
                usage_count=stats["usage_count"],
                recommended_action=PurgeAction.ARCHIVE,
                priority=5
            )
            candidates.append(candidate)

        return candidates

    def _scan_unused_experiences(
        self,
        tracker
    ) -> list[PurgeCandidate]:
        """扫描长期未使用的经验"""
        candidates = []

        now = time.time()
        unused_threshold_days = self.thresholds["unused_days_threshold"]

        for stats in tracker.get_all_stats():
            if stats.usage_count < self.thresholds["min_usage_for_unused"] and stats.last_used_at:
                days_unused = (now - stats.last_used_at) / 86400

                if days_unused > unused_threshold_days:
                    candidate = PurgeCandidate(
                        experience_id=stats.experience_id,
                        reason=f"长期未使用 ({int(days_unused)}天)",
                        reason_code="UNUSED_EXPERIENCE",
                        success_rate=stats.success_rate,
                        usage_count=stats.usage_count,
                        last_used_days=int(days_unused),
                        recommended_action=PurgeAction.ARCHIVE,
                        priority=2
                    )
                    candidates.append(candidate)

        return candidates

    def _scan_demote_candidates(
        self,
        tracker
    ) -> list[PurgeCandidate]:
        """扫描需要降级的经验"""
        candidates = []

        for stats in tracker.get_all_stats():
            # 成功率不高但也不是很低
            if (self.thresholds["low_success_rate"] <= stats.success_rate <
                self.thresholds["demote_threshold"]) and stats.usage_count >= self.thresholds["min_usage_for_purge"]:
                candidate = PurgeCandidate(
                    experience_id=stats.experience_id,
                    reason=f"成功率一般，建议降级 ({stats.success_rate:.1%})",
                    reason_code="DEMOTE_CANDIDATE",
                    success_rate=stats.success_rate,
                    usage_count=stats.usage_count,
                    recommended_action=PurgeAction.DEMOTE_WEIGHT,
                    priority=3
                )
                candidates.append(candidate)

        return candidates

    @staticmethod
    async def _scan_duplicate_experiences(
        vector_memory
    ) -> list[PurgeCandidate]:
        """扫描重复/相似经验（向量相似度 > 90%）"""
        candidates = []

        if vector_memory is None:
            return candidates

        # 兼容 VectorStore / MemoryManager / MemoryService
        if hasattr(vector_memory, "get_all"):
            vs = vector_memory
        elif hasattr(vector_memory, "vector_store"):
            vs = vector_memory.vector_store
        else:
            return candidates

        try:
            all_experiences = await vs.get_all("experience")
        except (RuntimeError, ConnectionError, TimeoutError) as e:
            logger.debug(f"[AutoPurgeEngine] 获取经验列表失败: {e}")
            return candidates

        seen_pairs = set()

        for exp in all_experiences:
            exp_id = exp.get("id")
            document = exp.get("document", "")

            if not document or not exp_id:
                continue

            try:
                similar_results = await vs.search("experience", document, limit=5)
            except (RuntimeError, ConnectionError, TimeoutError) as e:
                logger.debug(f"[AutoPurgeEngine] 相似度搜索失败: {e}")
                continue

            for result in similar_results:
                similar_id = getattr(result, "id", None)
                distance = getattr(result, "distance", None)

                if similar_id == exp_id:
                    continue

                similarity = 1.0 - (distance or 0.0)
                if similarity < 0.9:
                    continue

                pair = tuple(sorted([str(exp_id), str(similar_id)]))
                if pair in seen_pairs:
                    continue

                seen_pairs.add(pair)
                candidates.append(PurgeCandidate(
                    experience_id=exp_id,
                    reason=f"与 {similar_id} 高度相似 (相似度: {similarity:.1%})",
                    reason_code="DUPLICATE_EXPERIENCE",
                    success_rate=1.0,
                    usage_count=1,
                    recommended_action=PurgeAction.MERGE,
                    priority=4
                ))

        return candidates

    def execute_purge(
        self,
        candidates: list[PurgeCandidate],
        auto_confirm: bool = False
    ) -> list[PurgeRecord]:
        """
        执行淘汰操作

        Args:
            candidates: 候选列表
            auto_confirm: 是否自动确认（无需人工审核）

        Returns:
            执行记录列表
        """
        if self.dry_run and not auto_confirm:
            logger.info("[AutoPurgeEngine] 处于dry_run模式，仅模拟执行")

        results = []

        for candidate in candidates:
            # 高优先级可以自动执行，低优先级需要审核
            if not auto_confirm and candidate.priority < 4:
                # 标记待审核
                record = self._mark_for_review(candidate)
            else:
                # 执行操作
                record = self._execute_action(candidate)

            results.append(record)

        # 持久化
        self._persist_data()

        logger.info(f"[AutoPurgeEngine] 执行了 {len(results)} 个淘汰操作")

        return results

    def _mark_for_review(self, candidate: PurgeCandidate) -> PurgeRecord:
        """标记待审核"""
        self._experience_status[candidate.experience_id] = ExperienceStatus.UNDER_REVIEW

        record = PurgeRecord(
            record_id=hashlib.md5(f"{candidate.experience_id}:{time.time()}".encode()).hexdigest()[:12],
            experience_id=candidate.experience_id,
            action=PurgeAction.MARK_REVIEW,
            reason=candidate.reason,
            executed_at=time.time(),
            details="已标记待审核，等待人工确认"
        )

        self._purge_records.append(record)
        return record

    def _execute_action(self, candidate: PurgeCandidate) -> PurgeRecord:
        """执行淘汰操作"""
        record_id = hashlib.md5(f"{candidate.experience_id}:{time.time()}".encode()).hexdigest()[:12]

        if self.dry_run:
            record = PurgeRecord(
                record_id=record_id,
                experience_id=candidate.experience_id,
                action=candidate.recommended_action,
                reason=candidate.reason,
                executed_at=time.time(),
                details="[DRY_RUN] 模拟执行，未实际修改",
                success=True
            )
        else:
            # 实际执行
            success = False
            details = ""

            try:
                if candidate.recommended_action == PurgeAction.DEMOTE_WEIGHT:
                    success = self._demote_experience(candidate)
                    details = "已降低经验权重"

                elif candidate.recommended_action == PurgeAction.ARCHIVE:
                    success = self._archive_experience(candidate)
                    details = "已归档经验"

                elif candidate.recommended_action == PurgeAction.DELETE:
                    success = self._delete_experience(candidate)
                    details = "已删除经验"

                elif candidate.recommended_action == PurgeAction.MERGE:
                    success = self._merge_experience(candidate)
                    details = "已合并经验"

            except Exception as e:
                details = f"执行失败: {str(e)}"

            record = PurgeRecord(
                record_id=record_id,
                experience_id=candidate.experience_id,
                action=candidate.recommended_action,
                reason=candidate.reason,
                executed_at=time.time(),
                success=success,
                details=details
            )

        self._purge_records.append(record)
        return record

    def _demote_experience(self, candidate: PurgeCandidate) -> bool:
        """降低经验权重"""
        self._experience_status[candidate.experience_id] = ExperienceStatus.DEMOTED
        self._experience_weights[candidate.experience_id] = 0.3  # 降低权重到30%
        return True

    def _archive_experience(self, candidate: PurgeCandidate) -> bool:
        """归档经验"""
        self._experience_status[candidate.experience_id] = ExperienceStatus.ARCHIVED
        # 实际应该移动到归档存储
        return True

    def _delete_experience(self, candidate: PurgeCandidate) -> bool:
        """删除经验"""
        self._experience_status[candidate.experience_id] = ExperienceStatus.PURGED
        # 实际应该从向量库和记忆库中删除
        return True

    @staticmethod
    def _merge_experience(candidate: PurgeCandidate) -> bool:
        """合并经验"""
        # 复杂操作，需要指定合并目标
        _ = candidate  # type: ignore
        return False

    def get_experience_weight(self, experience_id: str) -> float:
        """获取经验当前权重"""
        status = self._experience_status.get(experience_id, ExperienceStatus.ACTIVE)

        if status == ExperienceStatus.PURGED:
            return 0.0
        elif status == ExperienceStatus.ARCHIVED:
            return 0.1
        elif status == ExperienceStatus.DEMOTED:
            return self._experience_weights.get(experience_id, 0.3)
        elif status == ExperienceStatus.UNDER_REVIEW:
            return 0.5
        else:
            return 1.0

    def get_purge_report(self, days: int = 30) -> dict[str, Any]:
        """获取淘汰报告"""
        recent_records = [
            r for r in self._purge_records
            if r.executed_at > time.time() - days * 86400
        ]

        action_counts = defaultdict(int)
        for r in recent_records:
            action_counts[r.action.value] += 1

        return {
            "generated_at": datetime.now().isoformat(),
            "period_days": days,
            "total_actions": len(recent_records),
            "action_breakdown": dict(action_counts),
            "current_status": {
                "active": sum(1 for s in self._experience_status.values() if s == ExperienceStatus.ACTIVE),
                "under_review": sum(1 for s in self._experience_status.values() if s == ExperienceStatus.UNDER_REVIEW),
                "demoted": sum(1 for s in self._experience_status.values() if s == ExperienceStatus.DEMOTED),
                "archived": sum(1 for s in self._experience_status.values() if s == ExperienceStatus.ARCHIVED),
                "purged": sum(1 for s in self._experience_status.values() if s == ExperienceStatus.PURGED)
            },
            "recent_records": [r.to_dict() for r in recent_records[:20]]
        }

    def _load_data(self):
        """加载数据"""
        try:
            import os
            if os.path.exists(self.storage_path):
                with open(self.storage_path, encoding='utf-8') as f:
                    data = json.load(f)

                # 加载状态
                for exp_id, status_str in data.get('status', {}).items():
                    self._experience_status[exp_id] = ExperienceStatus(status_str)

                # 加载权重
                self._experience_weights = data.get('weights', {})

                # 加载记录
                for record_data in data.get('records', []):
                    record = PurgeRecord(
                        record_id=record_data['record_id'],
                        experience_id=record_data['experience_id'],
                        action=PurgeAction(record_data['action']),
                        reason=record_data['reason'],
                        executed_at=record_data['executed_at'],
                        before_stats=record_data.get('before_stats', {}),
                        success=record_data.get('success', True),
                        details=record_data.get('details')
                    )
                    self._purge_records.append(record)

                logger.info(f"[AutoPurgeEngine] 加载了 {len(self._purge_records)} 条淘汰记录")
        except Exception as e:
            logger.warning(f"[AutoPurgeEngine] 加载数据失败: {e}")

    def _persist_data(self):
        """持久化数据"""
        try:
            import os
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)

            data = {
                'status': {
                    exp_id: status.value
                    for exp_id, status in self._experience_status.items()
                },
                'weights': self._experience_weights,
                'records': [r.to_dict() for r in self._purge_records[-1000:]],  # 只保留最近1000条
                'updated_at': datetime.now().isoformat()
            }

            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[AutoPurgeEngine] 持久化数据失败: {e}")


# ═══════════════════════════════════════════════════════════════════
# 便捷函数和全局实例
# ═══════════════════════════════════════════════════════════════════

_auto_purge_engine: AutoPurgeEngine | None = None


def get_auto_purge_engine(
    dry_run: bool = True,
    refresh: bool = False
) -> AutoPurgeEngine:
    """获取自动淘汰引擎全局实例"""
    global _auto_purge_engine
    if _auto_purge_engine is None or refresh:
        _auto_purge_engine = AutoPurgeEngine(dry_run=dry_run)
    return _auto_purge_engine


async def run_experience_purge(
    dry_run: bool = True,
    auto_confirm: bool = False
) -> dict[str, Any]:
    """
    便捷函数：运行经验淘汰流程

    Returns:
        淘汰报告
    """
    engine = get_auto_purge_engine(dry_run=dry_run)

    # 扫描候选
    candidates = await engine.scan_candidates()

    # 执行淘汰
    if candidates:
        engine.execute_purge(candidates, auto_confirm=auto_confirm)

    # 返回报告
    return engine.get_purge_report()
