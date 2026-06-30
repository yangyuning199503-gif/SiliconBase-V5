#!/usr/bin/env python3
"""
智能干预检测器
【Week 4】AI主动检测需要干预的场景，建议用户介入

检测场景：
1. 循环检测 - 执行轮次过多
2. 工具失败 - 同一工具多次失败
3. 目标偏离 - 执行内容与目标偏离
4. 超时预警 - 执行时间超过预估
5. 资源耗尽 - 系统资源不足
"""

import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.logger import logger


class SuggestionType(Enum):
    """建议类型"""
    LOOP_DETECTED = "loop_detected"           # 检测到循环
    TOOL_FAILING = "tool_failing"             # 工具多次失败
    GOAL_DRIFT = "goal_drift"                 # 目标偏离
    TIMEOUT_WARNING = "timeout_warning"       # 超时预警
    RESOURCE_EXHAUSTED = "resource_exhausted" # 资源耗尽


class SuggestedAction(Enum):
    """建议操作"""
    PAUSE = "PAUSE"           # 暂停检查
    REPLAN = "REPLAN"         # 重新规划
    ADJUST = "ADJUST"         # 调整方向
    CANCEL = "CANCEL"         # 取消任务
    CONTINUE = "CONTINUE"     # 继续观察


@dataclass
class InterventionSuggestion:
    """干预建议"""
    id: str                                    # 建议ID
    type: SuggestionType                       # 建议类型
    reason: str                                # 原因说明
    confidence: float                          # 置信度 0-1
    suggested_action: SuggestedAction          # 建议操作
    target_runtime_id: str | None = None    # 目标子代理
    target_task_id: str | None = None       # 目标任务
    metadata: dict[str, Any] = field(default_factory=dict)  # 额外信息
    timestamp: float = field(default_factory=time.time)
    dismissed: bool = False                    # 是否被忽略
    accepted: bool = False                     # 是否被接受


@dataclass
class DetectionConfig:
    """检测配置"""
    # 循环检测
    max_rounds: int = 15                       # 最大执行轮次
    loop_warning_threshold: int = 10           # 循环警告阈值

    # 工具失败检测
    max_tool_failures: int = 3                 # 最大工具失败次数
    tool_failure_window: int = 5               # 失败计数窗口（轮次）

    # 目标偏离检测
    goal_drift_threshold: float = 0.3          # 偏离度阈值

    # 超时检测
    timeout_multiplier: float = 2.0            # 超时倍数（超过预估时间多少倍）

    # 资源检测
    max_memory_percent: float = 85.0           # 最大内存使用率
    max_cpu_percent: float = 90.0              # 最大CPU使用率

    # 冷却时间
    suggestion_cooldown: int = 60              # 同一问题的建议冷却时间（秒）


class SmartInterventionDetector:
    """
    智能干预检测器

    单例模式，持续监控任务执行状态，主动发现需要干预的场景
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: DetectionConfig | None = None):
        if self._initialized:
            return
        self._initialized = True

        self.config = config or DetectionConfig()

        # 线程安全锁
        self._lock = threading.RLock()

        # 运行时状态跟踪 {runtime_id: RuntimeState}
        self._runtime_states: dict[str, dict[str, Any]] = {}

        # 建议历史 {runtime_id: [InterventionSuggestion]}
        self._suggestion_history: dict[str, list[InterventionSuggestion]] = defaultdict(list)

        # 已忽略的建议ID集合（防止重复建议）
        self._dismissed_suggestions: set = set()

        # 监听器列表
        self._listeners: list[Callable[[InterventionSuggestion], None]] = []

        logger.info("[SmartInterventionDetector] 智能干预检测器初始化完成")

        # 【TODO】添加状态持久化
        # 当前实现将状态保存在内存中，服务重启后会丢失。
        # 建议添加可选的文件或数据库持久化:
        #   - 文件: JSON/SQLite 存储运行时状态
        #   - 数据库: PostgreSQL/MongoDB 存储历史记录
        #   - 缓存: Redis 存储活跃运行时

    def register_listener(self, listener: Callable[[InterventionSuggestion], None]):
        """注册建议监听器"""
        self._listeners.append(listener)

    def unregister_listener(self, listener: Callable[[InterventionSuggestion], None]):
        """注销建议监听器"""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify_listeners(self, suggestion: InterventionSuggestion):
        """通知所有监听器"""
        for listener in self._listeners:
            try:
                listener(suggestion)
            except Exception as e:
                logger.error(f"[SmartInterventionDetector] 监听器执行失败: {e}")

    def register_runtime(self, runtime_id: str, task_description: str = "",
                         parent_task_id: str | None = None,
                         estimated_time: float | None = None):
        """
        注册运行时开始监控

        Args:
            runtime_id: 运行时ID
            task_description: 任务描述
            parent_task_id: 父任务ID
            estimated_time: 预估执行时间（秒）
        """
        with self._lock:
            self._runtime_states[runtime_id] = {
                "start_time": time.time(),
                "task_description": task_description,
                "parent_task_id": parent_task_id,
                "estimated_time": estimated_time,
                "round_count": 0,
                "tool_failures": defaultdict(int),  # {tool_name: failure_count}
                "tool_usage_history": [],  # [{tool, success, timestamp}, ...]
                "last_suggestion_time": 0,
                "active_suggestions": []
            }
        logger.debug(f"[SmartInterventionDetector] 注册运行时: {runtime_id}")

    def unregister_runtime(self, runtime_id: str):
        """注销运行时"""
        with self._lock:
            if runtime_id in self._runtime_states:
                del self._runtime_states[runtime_id]
        logger.debug(f"[SmartInterventionDetector] 注销运行时: {runtime_id}")

    def record_round(self, runtime_id: str, round_data: dict | None = None):
        """
        记录执行轮次

        Args:
            runtime_id: 运行时ID
            round_data: 轮次数据（工具调用、结果等）
        """
        if runtime_id not in self._runtime_states:
            return

        state = self._runtime_states[runtime_id]
        state["round_count"] += 1

        # 检查循环
        self._check_loop(runtime_id, state)

        # 检查超时
        self._check_timeout(runtime_id, state)

    def record_tool_execution(self, runtime_id: str, tool_name: str,
                               success: bool, error: str | None = None):
        """
        记录工具执行结果

        Args:
            runtime_id: 运行时ID
            tool_name: 工具名称
            success: 是否成功
            error: 错误信息
        """
        if runtime_id not in self._runtime_states:
            return

        state = self._runtime_states[runtime_id]
        state["tool_usage_history"].append({
            "tool": tool_name,
            "success": success,
            "timestamp": time.time(),
            "error": error
        })

        if not success:
            state["tool_failures"][tool_name] += 1
            # 检查工具失败
            self._check_tool_failures(runtime_id, state, tool_name)

    def _check_loop(self, runtime_id: str, state: dict):
        """检查是否陷入循环"""
        round_count = state["round_count"]

        if round_count >= self.config.max_rounds:
            # 超过最大轮次，强制建议取消
            self._create_suggestion(
                runtime_id=runtime_id,
                suggestion_type=SuggestionType.LOOP_DETECTED,
                reason=f"已执行 {round_count} 轮，超过最大限制 {self.config.max_rounds} 轮，可能陷入无限循环",
                confidence=min(0.95, round_count / self.config.max_rounds),
                suggested_action=SuggestedAction.CANCEL,
                metadata={"round_count": round_count, "threshold": self.config.max_rounds}
            )
        elif round_count >= self.config.loop_warning_threshold:
            # 超过警告阈值，建议暂停检查
            self._create_suggestion(
                runtime_id=runtime_id,
                suggestion_type=SuggestionType.LOOP_DETECTED,
                reason=f"已执行 {round_count} 轮，可能陷入循环，建议暂停检查方向",
                confidence=min(0.85, round_count / self.config.loop_warning_threshold * 0.8),
                suggested_action=SuggestedAction.PAUSE,
                metadata={"round_count": round_count, "threshold": self.config.loop_warning_threshold}
            )

    def _check_tool_failures(self, runtime_id: str, state: dict, tool_name: str):
        """检查工具失败次数"""
        failure_count = state["tool_failures"][tool_name]

        if failure_count >= self.config.max_tool_failures:
            # 同一工具多次失败，建议调整或重新规划
            self._create_suggestion(
                runtime_id=runtime_id,
                suggestion_type=SuggestionType.TOOL_FAILING,
                reason=f"工具 '{tool_name}' 已连续失败 {failure_count} 次，建议调整参数或更换工具",
                confidence=min(0.9, 0.6 + failure_count * 0.1),
                suggested_action=SuggestedAction.ADJUST,
                metadata={"tool_name": tool_name, "failure_count": failure_count}
            )

    def _check_timeout(self, runtime_id: str, state: dict):
        """检查是否超时"""
        if not state.get("estimated_time"):
            return

        elapsed = time.time() - state["start_time"]
        estimated = state["estimated_time"]

        if elapsed > estimated * self.config.timeout_multiplier:
            # 超过预估时间，建议暂停或取消
            self._create_suggestion(
                runtime_id=runtime_id,
                suggestion_type=SuggestionType.TIMEOUT_WARNING,
                reason=f"执行时间 {elapsed:.0f}s 超过预估 {estimated:.0f}s 的 {self.config.timeout_multiplier} 倍",
                confidence=min(0.85, elapsed / (estimated * self.config.timeout_multiplier) * 0.5),
                suggested_action=SuggestedAction.PAUSE,
                metadata={"elapsed": elapsed, "estimated": estimated}
            )

    def check_goal_drift(self, runtime_id: str, original_goal: str,
                         current_action: str) -> float | None:
        """
        检查目标偏离度（简化实现，实际可用语义相似度）

        Returns:
            偏离度 0-1，None表示无法计算
        """
        # 简化：通过关键词匹配判断偏离度
        # 实际应使用 embedding 语义相似度
        original_keywords = set(original_goal.lower().split())
        current_keywords = set(current_action.lower().split())

        if not original_keywords:
            return None

        overlap = len(original_keywords & current_keywords)
        drift = 1 - (overlap / len(original_keywords))

        if drift > self.config.goal_drift_threshold:
            self._create_suggestion(
                runtime_id=runtime_id,
                suggestion_type=SuggestionType.GOAL_DRIFT,
                reason=f"当前执行内容与原始目标偏离度较高 ({drift:.0%})，建议重新规划",
                confidence=min(0.8, drift),
                suggested_action=SuggestedAction.REPLAN,
                metadata={"drift": drift, "threshold": self.config.goal_drift_threshold}
            )

        return drift

    def check_resource_usage(self, runtime_id: str,
                            memory_percent: float,
                            cpu_percent: float):
        """检查资源使用情况"""
        if memory_percent > self.config.max_memory_percent:
            self._create_suggestion(
                runtime_id=runtime_id,
                suggestion_type=SuggestionType.RESOURCE_EXHAUSTED,
                reason=f"内存使用率 {memory_percent:.1f}% 超过阈值 {self.config.max_memory_percent}%",
                confidence=min(0.9, memory_percent / 100),
                suggested_action=SuggestedAction.PAUSE,
                metadata={"memory_percent": memory_percent}
            )

        if cpu_percent > self.config.max_cpu_percent:
            self._create_suggestion(
                runtime_id=runtime_id,
                suggestion_type=SuggestionType.RESOURCE_EXHAUSTED,
                reason=f"CPU使用率 {cpu_percent:.1f}% 超过阈值 {self.config.max_cpu_percent}%",
                confidence=min(0.9, cpu_percent / 100),
                suggested_action=SuggestedAction.PAUSE,
                metadata={"cpu_percent": cpu_percent}
            )

    def _create_suggestion(self, runtime_id: str, suggestion_type: SuggestionType,
                          reason: str, confidence: float,
                          suggested_action: SuggestedAction,
                          metadata: dict[str, Any] = None) -> InterventionSuggestion | None:
        """创建干预建议"""
        # 检查冷却时间
        state = self._runtime_states.get(runtime_id)
        if state:
            last_time = state.get("last_suggestion_time", 0)
            if time.time() - last_time < self.config.suggestion_cooldown:
                return None

        # 生成建议ID
        suggestion_id = f"{runtime_id}_{suggestion_type.value}_{int(time.time())}"

        # 检查是否已忽略
        if suggestion_id in self._dismissed_suggestions:
            return None

        suggestion = InterventionSuggestion(
            id=suggestion_id,
            type=suggestion_type,
            reason=reason,
            confidence=confidence,
            suggested_action=suggested_action,
            target_runtime_id=runtime_id,
            metadata=metadata or {}
        )

        # 保存到历史
        if runtime_id:
            self._suggestion_history[runtime_id].append(suggestion)
            if state:
                state["last_suggestion_time"] = time.time()
                state["active_suggestions"].append(suggestion)

        logger.info(f"[SmartInterventionDetector] 生成建议: {suggestion_type.value} - {reason}")

        # 通知监听器
        self._notify_listeners(suggestion)

        return suggestion

    def dismiss_suggestion(self, suggestion_id: str):
        """忽略建议"""
        self._dismissed_suggestions.add(suggestion_id)

        # 标记历史中的建议为已忽略
        for _runtime_id, suggestions in self._suggestion_history.items():
            for suggestion in suggestions:
                if suggestion.id == suggestion_id:
                    suggestion.dismissed = True

    def accept_suggestion(self, suggestion_id: str):
        """接受建议"""
        for _runtime_id, suggestions in self._suggestion_history.items():
            for suggestion in suggestions:
                if suggestion.id == suggestion_id:
                    suggestion.accepted = True
                    return suggestion
        return None

    def get_active_suggestions(self, runtime_id: str | None = None) -> list[InterventionSuggestion]:
        """获取活跃的建议"""
        if runtime_id:
            state = self._runtime_states.get(runtime_id)
            if state:
                return [s for s in state.get("active_suggestions", [])
                        if not s.dismissed and not s.accepted]
            return []

        # 返回所有活跃建议
        all_suggestions = []
        for state in self._runtime_states.values():
            all_suggestions.extend([
                s for s in state.get("active_suggestions", [])
                if not s.dismissed and not s.accepted
            ])
        return all_suggestions

    def get_suggestion_history(self, runtime_id: str) -> list[InterventionSuggestion]:
        """获取建议历史"""
        return self._suggestion_history.get(runtime_id, [])

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        total_suggestions = sum(len(s) for s in self._suggestion_history.values())
        accepted = sum(
            1 for suggestions in self._suggestion_history.values()
            for s in suggestions if s.accepted
        )
        dismissed = sum(
            1 for suggestions in self._suggestion_history.values()
            for s in suggestions if s.dismissed
        )

        return {
            "monitored_runtimes": len(self._runtime_states),
            "total_suggestions": total_suggestions,
            "accepted_suggestions": accepted,
            "dismissed_suggestions": dismissed,
            "acceptance_rate": accepted / total_suggestions if total_suggestions > 0 else 0
        }


# 全局实例
smart_intervention_detector = SmartInterventionDetector()
