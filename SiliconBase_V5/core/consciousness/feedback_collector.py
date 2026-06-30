#!/usr/bin/env python3
"""
统一反馈收集器 - 手眼脑嘴协同架构的"经验总线"

设计目标：
- 所有模块（眼、手、嘴、脑 + 工具/RLHF/传感器/记忆/进化/反思/交易）的反馈汇聚到一个地方
- 按固定权重融合成统一的 0~1 标签，供模型训练使用
- 权重不可随意调整，确保学习规则的一致性
- 标签语义：1.0 = 极好，0.0 = 极差，0.5 = 中性

权重分配（总线化后，覆盖所有数据源）：
- 思考质量:     0.13  （脑自我评估 - 价值评估系统）
- 行动结果:     0.20  （手→脑 - _act_on_thought返回值）
- 用户交互:     0.13  （嘴→脑 - 用户输入时间变化）
- 工具执行:     0.13  （ExperienceBus - tool success/failure）
- 用户评分:     0.13  （ExperienceBus - RLHF 点赞/点踩/星级）
- 环境变化:     0.08  （ExperienceBus - 传感器数据）
- 学习效果:     0.03  （ExperienceBus - 进化经验 + 反思策略）
- 记忆价值:     0.04  （ExperienceBus - 记忆访问/晋升/遗忘）
- 视觉反馈:     0.08  （眼→脑 - 视觉变化）
- 交易结果:     0.02  （ExperienceBus - 交易盈亏）
- 执行轨迹:     0.03  （ExperienceBus - AgentLoop 任务/工具/结果轨迹）
"""

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class ActionResult:
    """行动执行结果，由 _act_on_thought() 返回"""
    weak_connection_triggered: bool = False
    weak_connection_keyword: str = ""
    task_proposed: bool = False
    task_priority: str = "none"   # high / normal / low / none
    world_model_confidence: float = 0.0
    executed: bool = False        # 是否实际执行了行动
    reason: str = ""              # 未执行的理由
    action_text: str = ""         # 行动文本


@dataclass
class ThoughtSnapshot:
    """思考前的状态快照"""
    timestamp: float
    motivation: Any = None        # 4维动机向量
    vision_state: Any = None      # 8维视觉状态向量
    history: Any = None           # 4维历史向量
    chosen_direction: str = ""    # 选中的思考方向


# 避免循环导入：仅用于类型标注
from core.consciousness.experience_bus import ExperienceEvent  # noqa: E402


class FeedbackCollector:
    """
    统一反馈收集器。

    使用方式：
        # 1. 思考前记录快照
        snapshot = collector.snapshot(motivation, vision_state, history, chosen_direction)

        # 2. 思考后、行动后收集反馈
        collector.record_thought_quality(assessment_score, converged, thought_length)
        collector.record_action_result(action_result)
        collector.record_user_feedback(user_responded, user_interrupted)
        collector.record_vision_feedback(new_elements_found, alert_changed)

        # 3. 计算统一标签
        label = collector.compute_label()
    """

    # 固定权重，不可随意调整
    # 10个维度总和严格为1.00
    WEIGHTS = {
        "thought_quality": 0.13,
        "action_result": 0.20,
        "user_feedback": 0.13,
        "tool_outcome": 0.13,
        "rlhf_outcome": 0.13,
        "sensor_outcome": 0.08,
        "learning_outcome": 0.03,
        "memory_outcome": 0.04,
        "vision_feedback": 0.08,
        "trade_outcome": 0.02,
        "agent_loop_outcome": 0.03,
    }

    def __init__(self):
        self.snapshot: ThoughtSnapshot | None = None
        self.thought_quality: dict[str, Any] = {}
        self.action_result: ActionResult | None = None
        self.user_feedback: dict[str, Any] = {}
        self.vision_feedback: dict[str, Any] = {}

        # 【ExperienceBus】各source的加权平均outcome（由ExperienceBus.flush_to_collector填充）
        self._tool_outcome: float = 0.5
        self._rlhf_outcome: float = 0.5
        self._sensor_outcome: float = 0.5
        self._learning_outcome: float = 0.5
        self._memory_outcome: float = 0.5
        self._trade_outcome: float = 0.5
        self._agent_loop_outcome: float = 0.5

        # 记录本周期内收到的ExperienceEvent数量（用于日志）
        self._experience_event_count: int = 0

    def take_snapshot(self, motivation: Any, vision_state: Any,
                      history: Any, chosen_direction: str):
        """思考前记录状态快照"""
        self.snapshot = ThoughtSnapshot(
            timestamp=time.time(),
            motivation=motivation,
            vision_state=vision_state,
            history=history,
            chosen_direction=chosen_direction,
        )
        # 清空上一次的反馈
        self.thought_quality = {}
        self.action_result = None
        self.user_feedback = {}
        self.vision_feedback = {}

    def record_thought_quality(self, assessment_score: float, converged: bool, thought_length: int):
        """
        记录思考质量反馈（脑自我评估）。

        Args:
            assessment_score: 价值评估系统的 overall_score (0~1)
            converged: 慢思考是否收敛
            thought_length: 最终思考文本长度
        """
        self.thought_quality = {
            "assessment_score": assessment_score,
            "converged": converged,
            "thought_length": thought_length,
        }

    def record_action_result(self, result: ActionResult):
        """记录行动结果反馈（手→脑）"""
        self.action_result = result

    def record_user_feedback(self, user_responded_within_10s: bool = False, user_interrupted: bool = False):
        """
        记录用户反馈（嘴→脑）。

        Args:
            user_responded_within_10s: 思考产生后 10 秒内用户是否有输入
            user_interrupted: 用户是否打断了当前流程
        """
        self.user_feedback = {
            "user_responded_within_10s": user_responded_within_10s,
            "user_interrupted": user_interrupted,
        }

    def record_vision_feedback(self, new_elements_found: int = 0, alert_level_changed: bool = False):
        """
        记录视觉反馈（眼→脑）。

        Args:
            new_elements_found: 思考期间发现的新元素数量
            alert_level_changed: 告警级别是否发生变化
        """
        self.vision_feedback = {
            "new_elements_found": new_elements_found,
            "alert_level_changed": alert_level_changed,
        }

    def ingest_experience_events(self, events: list[ExperienceEvent]):
        """
        接收来自 ExperienceBus 的经验事件，计算各source的加权平均。

        Args:
            events: ExperienceEvent 列表
        """
        if not events:
            return

        source_stats: dict[str, dict[str, float]] = {}
        for e in events:
            src = e.source
            if src not in source_stats:
                source_stats[src] = {"sum": 0.0, "weight": 0.0, "count": 0}
            source_stats[src]["sum"] += e.outcome * e.weight
            source_stats[src]["weight"] += e.weight
            source_stats[src]["count"] += 1

        for src, stat in source_stats.items():
            if stat["weight"] > 0:
                avg = stat["sum"] / stat["weight"]
                if src == "tool":
                    self._tool_outcome = avg
                elif src == "rlhf":
                    self._rlhf_outcome = avg
                elif src == "sensor":
                    self._sensor_outcome = avg
                elif src in ("evolution", "reflect"):
                    self._learning_outcome = avg
                elif src == "memory":
                    self._memory_outcome = avg
                elif src == "trade":
                    self._trade_outcome = avg
                elif src == "agent_loop":
                    self._agent_loop_outcome = avg

        self._experience_event_count = int(sum(s["count"] for s in source_stats.values()))

    def compute_label(self) -> float:
        """
        计算统一的 0~1 标签。

        各维度计算方式：
        - thought_quality: assessment_score * (1.1 if converged else 0.9)，截断到 0~1
        - action_result: 综合 task_proposed、priority、world_model_confidence
        - user_feedback: responded=1.0, interrupted=0.0, 无响应=0.5
        - vision_feedback: new_elements * 0.2 (max 1.0), alert_changed +0.3
        """
        scores = {}

        # 1. 思考质量 (0~1)
        if self.thought_quality:
            base = self.thought_quality.get("assessment_score", 0.5)
            base = (
                min(1.0, base * 1.1)
                if self.thought_quality.get("converged", False)
                else max(0.0, base * 0.9)
            )
            # 长度奖励：100~500 字为最佳区间
            length = self.thought_quality.get("thought_length", 0)
            if 100 <= length <= 500:
                base = min(1.0, base + 0.05)
            scores["thought_quality"] = base
        else:
            scores["thought_quality"] = 0.5

        # 2. 行动结果 (0~1)
        if self.action_result:
            if not self.action_result.executed:
                # 未执行：根据理由判断
                if "用户活跃" in self.action_result.reason:
                    scores["action_result"] = 0.6  # 保守但不坏
                else:
                    scores["action_result"] = 0.4
            else:
                # 已执行：根据优先级和置信度
                priority_score = {"high": 1.0, "normal": 0.7, "low": 0.4, "none": 0.0}
                p_score = priority_score.get(self.action_result.task_priority, 0.5)
                wm_conf = self.action_result.world_model_confidence
                # 世界模型置信度加权
                scores["action_result"] = p_score * 0.7 + wm_conf * 0.3
        else:
            scores["action_result"] = 0.5

        # 3. 用户反馈 (0~1)
        if self.user_feedback:
            if self.user_feedback.get("user_interrupted", False):
                scores["user_feedback"] = 0.2  # 被打断 = 负面
            elif self.user_feedback.get("user_responded_within_10s", False):
                scores["user_feedback"] = 0.9  # 用户立刻回应 = 高参与度
            else:
                scores["user_feedback"] = 0.5  # 无响应 = 中性
        else:
            scores["user_feedback"] = 0.5

        # 4. 视觉反馈 (0~1)
        if self.vision_feedback:
            new_elems = self.vision_feedback.get("new_elements_found", 0)
            alert_changed = self.vision_feedback.get("alert_level_changed", False)
            scores["vision_feedback"] = min(1.0, new_elems * 0.2) + (0.3 if alert_changed else 0.0)
            scores["vision_feedback"] = min(1.0, scores["vision_feedback"])
        else:
            scores["vision_feedback"] = 0.5

        # 5~8. ExperienceBus 各source outcome（已由 ingest_experience_events 计算好）
        scores["tool_outcome"] = max(0.0, min(1.0, self._tool_outcome))
        scores["rlhf_outcome"] = max(0.0, min(1.0, self._rlhf_outcome))
        scores["sensor_outcome"] = max(0.0, min(1.0, self._sensor_outcome))
        scores["learning_outcome"] = max(0.0, min(1.0, self._learning_outcome))
        scores["memory_outcome"] = max(0.0, min(1.0, self._memory_outcome))
        scores["trade_outcome"] = max(0.0, min(1.0, getattr(self, "_trade_outcome", 0.5)))
        scores["agent_loop_outcome"] = max(0.0, min(1.0, getattr(self, "_agent_loop_outcome", 0.5)))

        # 加权融合（10个维度，总和严格为1.00）
        final = (
            scores["thought_quality"] * self.WEIGHTS["thought_quality"] +
            scores["action_result"] * self.WEIGHTS["action_result"] +
            scores["user_feedback"] * self.WEIGHTS["user_feedback"] +
            scores["vision_feedback"] * self.WEIGHTS["vision_feedback"] +
            scores["tool_outcome"] * self.WEIGHTS["tool_outcome"] +
            scores["rlhf_outcome"] * self.WEIGHTS["rlhf_outcome"] +
            scores["sensor_outcome"] * self.WEIGHTS["sensor_outcome"] +
            scores["learning_outcome"] * self.WEIGHTS["learning_outcome"] +
            scores["memory_outcome"] * self.WEIGHTS["memory_outcome"] +
            scores["trade_outcome"] * self.WEIGHTS["trade_outcome"] +
            scores["agent_loop_outcome"] * self.WEIGHTS["agent_loop_outcome"]
        )
        return round(final, 4)

    def get_summary(self) -> dict[str, Any]:
        """返回反馈汇总（用于日志）"""
        return {
            "label": self.compute_label(),
            "thought_quality": self.thought_quality,
            "action_result": {
                "executed": self.action_result.executed if self.action_result else False,
                "priority": self.action_result.task_priority if self.action_result else "none",
            },
            "user_feedback": self.user_feedback,
            "vision_feedback": self.vision_feedback,
            "experience_events": self._experience_event_count,
            "experience_outcomes": {
                "tool": self._tool_outcome,
                "rlhf": self._rlhf_outcome,
                "sensor": self._sensor_outcome,
                "learning": self._learning_outcome,
                "memory": self._memory_outcome,
            },
        }
