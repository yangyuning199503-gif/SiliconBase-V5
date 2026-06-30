#!/usr/bin/env python3
"""
目标系统 - 核心实现
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
提供目标管理和追踪功能：
- 目标创建和管理
- 目标分解
- 进度追踪

【使用示例】
    from core.goal_system import get_goal_system, Goal

    goal_system = get_goal_system()
    goal = Goal(name="学习Python", description="掌握Python编程")
    goal_system.add_goal(goal)
"""

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, cast

try:
    from core.logger import logger as _logger
except ImportError:
    _logger = logging.getLogger('goal_system')

logger: logging.Logger = cast(logging.Logger, _logger)


class GoalStatus(Enum):
    """目标状态枚举"""
    ACTIVE = "active"       # 进行中
    COMPLETED = "completed" # 已完成
    PAUSED = "paused"       # 暂停
    CANCELLED = "cancelled" # 已取消


def _empty_goal_list() -> list['Goal']:
    return []


def _empty_metadata() -> dict[str, Any]:
    return {}


@dataclass
class Goal:
    """目标数据类"""
    name: str
    description: str = ""
    goal_id: str = field(default_factory=lambda: f"goal_{uuid.uuid4().hex[:8]}")
    status: GoalStatus = GoalStatus.ACTIVE
    progress: float = 0.0  # 0-100
    subgoals: list['Goal'] = field(default_factory=_empty_goal_list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=_empty_metadata)
    priority: int = 1  # 优先级 1-5，默认1（最高）
    # 新增：用于 subgoal 权重和完成验证（默认值保证向后兼容）
    weight: float = 1.0
    verification: dict[str, Any] = field(default_factory=_empty_metadata)
    completed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "goal_id": self.goal_id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "progress": self.progress,
            "priority": self.priority,
            "subgoals": [sg.to_dict() for sg in self.subgoals],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "weight": self.weight,
            "verification": self.verification,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'Goal':
        """从字典创建 - 自动迁移旧数据格式"""
        data = data.copy()

        # 【数据迁移】旧版本使用 'id'，新版本使用 'goal_id'
        if 'id' in data:
            data['goal_id'] = data.pop('id')

        # 确保 goal_id 存在
        if 'goal_id' not in data:
            data['goal_id'] = f"goal_{uuid.uuid4().hex[:8]}"

        raw_status = data.get('status', 'active')
        data['status'] = GoalStatus(raw_status if raw_status else 'active')
        subgoals_data: list[dict[str, Any]] = data.pop('subgoals', [])

        # 只传递 Goal.__init__ 接受的参数
        valid_fields = ['name', 'description', 'goal_id', 'status', 'progress',
                        'priority', 'created_at', 'updated_at', 'metadata',
                        'weight', 'verification', 'completed_at']
        filtered_data: dict[str, Any] = {k: v for k, v in data.items() if k in valid_fields}

        goal = cls(**filtered_data)
        goal.subgoals = [Goal.from_dict(sg) for sg in subgoals_data]
        return goal

    def update_progress(self, progress: float):
        """更新进度"""
        self.progress = max(0.0, min(100.0, progress))
        self.updated_at = time.time()

        # 自动更新状态
        if self.progress >= 100.0:
            self.status = GoalStatus.COMPLETED


class GoalSystem:
    """
    目标系统

    管理目标的创建、追踪和完成。

    单例模式实现。
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化目标系统"""
        if self._initialized:
            return
        self._initialized = True

        # 目标存储: goal_id -> Goal
        self._goals: dict[str, Goal] = {}

        # 存储文件
        self._storage_file = Path("data/goals.json")
        self._storage_file.parent.mkdir(parents=True, exist_ok=True)

        # 锁
        self._lock = threading.RLock()

        # 加载已有目标
        self._load_goals()

        logger.info("[GoalSystem] 目标系统初始化完成")

    def add_goal(self, goal: Goal) -> str:
        """
        添加目标

        Args:
            goal: 目标对象

        Returns:
            目标ID
        """
        with self._lock:
            self._goals[goal.goal_id] = goal
            self._save_goals()
            logger.info(f"[GoalSystem] 添加目标: {goal.name} ({goal.goal_id})")
            return goal.goal_id

    def get_goal(self, goal_id: str) -> Goal | None:
        """
        获取目标

        Args:
            goal_id: 目标ID

        Returns:
            目标对象或None
        """
        return self._goals.get(goal_id)

    def update_goal(self, goal_id: str, **updates: Any) -> bool:
        """
        更新目标

        Args:
            goal_id: 目标ID
            **updates: 更新字段

        Returns:
            是否成功
        """
        with self._lock:
            goal = self._goals.get(goal_id)
            if not goal:
                return False

            for key, value in updates.items():
                if hasattr(goal, key):
                    setattr(goal, key, value)

            goal.updated_at = time.time()
            self._save_goals()
            return True

    def delete_goal(self, goal_id: str) -> bool:
        """
        删除目标

        Args:
            goal_id: 目标ID

        Returns:
            是否成功
        """
        with self._lock:
            if goal_id not in self._goals:
                return False

            goal = self._goals.pop(goal_id)
            self._save_goals()
            logger.info(f"[GoalSystem] 删除目标: {goal.name}")
            return True

    def list_goals(self, status: GoalStatus | None = None) -> list[Goal]:
        """
        列出目标

        Args:
            status: 状态过滤

        Returns:
            目标列表
        """
        with self._lock:
            goals = list(self._goals.values())
            if status:
                goals = [g for g in goals if g.status == status]
            return goals

    def get_active_goals(self) -> list[Goal]:
        """获取进行中的目标"""
        return self.list_goals(GoalStatus.ACTIVE)

    def complete_goal(self, goal_id: str) -> bool:
        """
        完成目标

        Args:
            goal_id: 目标ID

        Returns:
            是否成功
        """
        return self.update_goal(goal_id, status=GoalStatus.COMPLETED, progress=100.0)

    def get_top_priority_goal(self) -> Goal | None:
        """获取最高优先级的活跃目标

        Returns:
            Goal: 优先级最高(priority值最小)的活跃目标
            None: 没有活跃目标时返回None
        """
        with self._lock:
            try:
                active_goals = [g for g in self._goals.values()
                                if g.status == GoalStatus.ACTIVE]
                if not active_goals:
                    logger.info("[GoalSystem] 没有活跃目标")
                    return None
                # priority 越小优先级越高
                top_goal = min(active_goals, key=lambda g: g.priority)
                logger.info(f"[GoalSystem] 获取最高优先级目标: {top_goal.name}, priority={top_goal.priority}")
                return top_goal
            except Exception as e:
                logger.error(f"[GoalSystem] get_top_priority_goal 失败: {e}")
                raise

    def update_progress(self, goal_id: str, progress: float) -> bool:
        """更新目标进度

        Args:
            goal_id: 目标ID
            progress: 进度值(0-1)

        Returns:
            bool: True成功, False失败
        """
        try:
            if not 0 <= progress <= 1:
                logger.error(f"[GoalSystem] update_progress 进度值无效: {progress}")
                return False

            with self._lock:
                goal = self._goals.get(goal_id)
                if not goal:
                    logger.error(f"[GoalSystem] update_progress 目标不存在: {goal_id}")
                    return False
                # 调用 Goal 类的 update_progress 方法（自动处理 0-100 转换和状态更新）
                goal.update_progress(progress * 100)
                self._save_goals()
                logger.info(f"[GoalSystem] 更新目标进度: {goal.name} = {progress*100:.1f}%")
                return True
        except Exception as e:
            logger.error(f"[GoalSystem] update_progress 失败: goal_id={goal_id}, error={e}")
            raise

    def complete_subgoal(self, goal_id: str, subgoal_id: str) -> bool:
        """
        完成目标下的一个 subgoal，并按权重重新聚合父目标进度。

        Args:
            goal_id: 父目标ID
            subgoal_id: subgoal ID

        Returns:
            bool: 是否成功
        """
        with self._lock:
            goal = self._goals.get(goal_id)
            if not goal:
                return False

            sg = next((s for s in goal.subgoals if s.goal_id == subgoal_id), None)
            if not sg:
                return False

            sg.status = GoalStatus.COMPLETED
            sg.progress = 1.0
            sg.completed_at = time.time()

            total_weight = sum(s.weight for s in goal.subgoals)
            completed_weight = sum(
                s.weight for s in goal.subgoals
                if s.status == GoalStatus.COMPLETED
            )
            progress = (completed_weight / total_weight) if total_weight > 0 else 1.0

            goal.update_progress(progress * 100)
            if progress >= 1.0:
                goal.status = GoalStatus.COMPLETED
                logger.info(f"[GoalSystem] 目标完成: {goal.name}")

            self._save_goals()
            return True

    def evaluate_tool_subgoal_completion(
        self,
        active_goal: Goal,
        tool_id: str,
        result: dict[str, Any],
        user_instruction: str,
    ) -> Goal | None:
        """
        根据工具执行结果判断是否有 subgoal 完成。

        匹配策略（按优先级）：
        1. verification 中声明 tool_must_use / output_must_contain。
        2. 启发式：subgoal 描述关键词出现在 tool_id / result / user_instruction 中。
        """
        if not active_goal or not active_goal.subgoals:
            return None

        success = result.get("success", False)
        if not success:
            return None

        result_text = str(result.get("data", "")) + " " + str(result.get("user_message", ""))
        combined = f"{tool_id} {result_text} {user_instruction}".lower()

        for sg in active_goal.subgoals:
            if sg.status == GoalStatus.COMPLETED:
                continue

            verification = sg.verification or {}
            must_tool = verification.get("tool_must_use")
            must_contain = verification.get("output_must_contain")

            if must_tool:
                if must_tool == tool_id:
                    return sg
            elif must_contain:
                if str(must_contain).lower() in combined:
                    return sg
            else:
                # 启发式：subgoal 描述中非停用词关键词命中
                desc = sg.description.lower()
                keywords = [w for w in desc.split() if len(w) > 2]
                if keywords and any(kw in combined for kw in keywords):
                    return sg

        return None

    def generate_daily_goals(self) -> list[Goal]:
        """生成每日目标 (占位实现)"""
        logger.info("[GoalSystem] generate_daily_goals 未实现，返回空列表")
        return []

    def _save_goals(self):
        """保存目标到文件"""
        try:
            data = {gid: goal.to_dict() for gid, goal in self._goals.items()}
            with open(self._storage_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[GoalSystem] 保存目标失败: {e}")

    def _load_goals(self):
        """从文件加载目标"""
        try:
            if not self._storage_file.exists():
                return

            with open(self._storage_file, encoding='utf-8') as f:
                data = json.load(f)

            for goal_id, goal_data in data.items():
                self._goals[goal_id] = Goal.from_dict(goal_data)

            logger.info(f"[GoalSystem] 加载了 {len(self._goals)} 个目标")
        except Exception as e:
            logger.error(f"[GoalSystem] 加载目标失败: {e}")

    def get_stats(self) -> dict[str, int]:
        """获取统计信息"""
        return {
            "total": len(self._goals),
            "active": len(self.list_goals(GoalStatus.ACTIVE)),
            "completed": len(self.list_goals(GoalStatus.COMPLETED))
        }


# 全局文件路径（向后兼容）
GOALS_FILE = "data/goals.json"


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

def get_goal_system() -> GoalSystem:
    """获取目标系统实例"""
    return GoalSystem()


__all__ = [
    'GoalSystem',
    'get_goal_system',
    'Goal',
    'GoalStatus',
    'GOALS_FILE',
]
