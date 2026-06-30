#!/usr/bin/env python3
"""
内在动机系统 - 核心实现（重写版）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
基于自我决定理论，不再是"测量仪"，而是"发动机"。
好奇心、胜任感、自主性直接影响思维线程的行为决策。

核心设计原则：
- 好奇心：区分来源价值（UIA > OCR > contour），高价值新发现更兴奋
- 自主性：基于动作来源，自己发起的行为得分高
- 胜任感：基于成功率，连续失败会主动触发复盘
- 所有动机状态都能驱动实际行为

【使用示例】
    from core.intrinsic_motivation import IntrinsicMotivation

    motivation = IntrinsicMotivation()

    # 视觉系统检测到新元素时注册
    is_novel, boost = motivation.register_discovery(
        source="uia", element_type="Button", app_name="网易云音乐", name="播放"
    )

    # 思维线程每轮调用，决定这轮做什么
    drive = motivation.evaluate_drive()
    if drive.should_explore:
        # 主动触发探索行为
        ...
    if drive.should_reflect:
        # 触发复盘
        ...
"""

import hashlib
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger('intrinsic_motivation')


class MotivationType(Enum):
    """动机类型枚举"""
    CURIOSITY = "curiosity"       # 好奇心
    MASTERY = "mastery"           # 胜任感
    AUTONOMY = "autonomy"         # 自主性
    PURPOSE = "purpose"           # 目的感


class ActionSource(Enum):
    """动作来源枚举"""
    USER_COMMAND = "user_command"       # 用户指令
    SYSTEM_TIMER = "system_timer"       # 系统定时触发
    SELF_INITIATED = "self_initiated"   # AI 自己发起
    EXTERNAL_EVENT = "external_event"   # 外部事件驱动


@dataclass
class MotivationState:
    """动机状态数据类"""
    curiosity: float = 0.5        # 好奇心水平 (0-1)
    mastery: float = 0.5          # 胜任感水平 (0-1)
    autonomy: float = 0.5         # 自主性水平 (0-1)
    purpose: float = 0.5          # 目的感水平 (0-1)

    def get_dominant(self) -> MotivationType:
        """获取主导动机"""
        values = {
            MotivationType.CURIOSITY: self.curiosity,
            MotivationType.MASTERY: self.mastery,
            MotivationType.AUTONOMY: self.autonomy,
            MotivationType.PURPOSE: self.purpose
        }
        return max(values, key=values.get)

    def get_lowest(self) -> MotivationType:
        """获取最低动机"""
        values = {
            MotivationType.CURIOSITY: self.curiosity,
            MotivationType.MASTERY: self.mastery,
            MotivationType.AUTONOMY: self.autonomy,
            MotivationType.PURPOSE: self.purpose
        }
        return min(values, key=values.get)


@dataclass
class ExplorationTarget:
    """探索目标"""
    description: str               # 目标描述
    priority: float                # 优先级 (0-1)
    source: str                    # 来源（哪个模块发现的）
    element_type: str = ""         # 元素类型（如果是UI元素）
    app_name: str = ""             # 所属应用
    bbox: list[float] = field(default_factory=list)
    discovered_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "priority": self.priority,
            "source": self.source,
            "element_type": self.element_type,
            "app_name": self.app_name,
            "discovered_at": self.discovered_at,
        }


@dataclass
class BehavioralDrive:
    """行为驱动力——告诉思维线程这轮该做什么"""
    should_explore: bool = False           # 是否应该主动探索
    should_reflect: bool = False           # 是否应该复盘失败
    should_rest: bool = False              # 是否应该降低活跃度
    should_seek_help: bool = False         # 是否应该向用户求助
    curiosity_level: float = 0.5
    mastery_level: float = 0.5
    autonomy_level: float = 0.5
    purpose_level: float = 0.5
    energy_level: float = 0.8
    dominant_motivation: str = "curiosity"
    exploration_targets: list[ExplorationTarget] = field(default_factory=list)
    reflection_hint: str = ""              # 复盘建议


# ── 来源价值权重：不同类型的新发现对好奇心的刺激程度不同 ──
_SOURCE_CURIOSITY_WEIGHT = {
    "uia": 1.0,          # UIA 发现的按钮/控件——最有价值
    "ocr": 0.5,          # OCR 文字——中等价值
    "contour": 0.3,      # 轮廓——低价值，可能是噪点
    "onnx": 0.4,         # ONNX 检测——中等偏低
    "unknown": 0.5,      # 未知来源——中等
}

# ── UIA 控件类型的好奇心权重 ──
_UIA_TYPE_WEIGHT = {
    "Button": 1.0,
    "Edit": 0.9,
    "ComboBox": 0.9,
    "MenuItem": 0.8,
    "TabItem": 0.7,
    "Hyperlink": 0.8,
    "CheckBox": 0.7,
    "RadioButton": 0.7,
    "Slider": 0.6,
    "Spinner": 0.6,
    "ToolBar": 0.5,
    "StatusBar": 0.3,
    "ScrollBar": 0.2,
    "Pane": 0.2,
    "Group": 0.2,
    "Unknown": 0.5,
    "Text": 0.1,
    "Document": 0.1,
}

# ── 衰减参数 ──
_CURIOSITY_DECAY_PER_ROUND = 0.01      # 每轮无新发现时衰减
_CURIOSITY_BOOST_NOVEL = 0.15          # 高新奇度发现的增量
_AUTONOMY_DECAY_PER_ROUND = 0.005      # 每轮无自主行为时衰减
_MASTERY_DECAY_PER_ROUND = 0.003       # 每轮衰减

# ── 行为阈值 ──
_CURIOSITY_EXPLORE_THRESHOLD = 0.45    # 超过此值主动探索（初始 0.5 可触发）
_MASTERY_REFLECT_THRESHOLD = 0.55      # 低于此值触发复盘（初始 0.5 可触发）
_AUTONOMY_SEEK_HELP_THRESHOLD = 0.3    # 低于此值考虑求助
_ENERGY_REST_THRESHOLD = 0.25          # 低于此值降低活跃度

# ── 容量限制（防内存泄漏）──
_MAX_EXPLORED_ITEMS = 5000             # 探索历史最大条目
_MAX_PENDING_EXPLORATION = 50          # 待探索队列最大长度
_MAX_RECENT_OUTCOMES = 20              # 最近结果队列最大长度
_MAX_HISTORY = 200                     # 历史记录最大长度


class IntrinsicMotivation:
    """
    内在动机系统（重写版）

    不再是"测量仪"，而是"发动机"。
    动机状态直接影响思维线程的行为决策。

    单例模式实现。
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, world_model=None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
                    cls._instance._world_model = world_model
        return cls._instance

    def __init__(self, world_model=None):
        if self._initialized:
            return
        self._initialized = True

        self._world_model = world_model
        self._state = MotivationState()
        self._lock = threading.RLock()

        # 探索历史：记录见过的东西（哈希 → 元数据）
        # 使用 OrderedDict 实现 LRU，防内存泄漏
        self._explored_items: OrderedDict[str, dict[str, Any]] = OrderedDict()

        # 最近发现的高价值未知元素（待探索队列）
        self._pending_exploration: deque = deque(maxlen=_MAX_PENDING_EXPLORATION)

        # 成功/失败追踪
        self._success_count = 0
        self._total_attempts = 0
        self._recent_outcomes: deque = deque(maxlen=_MAX_RECENT_OUTCOMES)

        # 自主行为计数
        self._self_initiated_count = 0
        self._total_action_count = 0

        # 历史记录（保留最近 200 条用于分析）
        self._history: deque = deque(maxlen=_MAX_HISTORY)

        # 上次探索/复盘时间
        self._last_exploration_time = 0
        self._last_reflection_time = 0

        # 新奇度阈值（可动态调整）
        self.novelty_threshold = 0.5

        # 活跃度（由外部设置，如 GPU 状态、系统负载）
        self._energy_level = 0.8

        # ── KF：动机状态平滑 ──────────────────────────────────────────────────
        from core.estimation.state_estimator import KalmanFilter
        self._motivation_kf = KalmanFilter(state_dim=4, observation_dim=4)
        # 初始化状态 [curiosity, mastery, autonomy, energy]
        import numpy as np
        self._motivation_kf.X = np.array([[0.5], [0.5], [0.5], [0.8]])
        # 过程噪声：动机变化缓慢
        self._motivation_Q = np.eye(4) * 0.005
        # 观测噪声：原始读数有一定抖动
        self._motivation_R = np.eye(4) * 0.02
        # 观测矩阵：直接观测
        self._motivation_H = np.eye(4)
        # 状态转移：轻微惯性
        self._motivation_A = np.array([
            [0.98, 0.01, 0.01, 0.00],
            [0.01, 0.98, 0.01, 0.00],
            [0.01, 0.01, 0.98, 0.00],
            [0.00, 0.00, 0.00, 0.99]
        ])

        logger.info("[IntrinsicMotivation] 内在动机系统初始化完成（重写版），KF 已注册")

    # ═══════════════════════════════════════════════════════════════
    # 核心接口：思维线程每轮调用
    # ═══════════════════════════════════════════════════════════════

    def evaluate_drive(self) -> BehavioralDrive:
        """
        评估当前行为驱动力。

        思维线程每轮调用此方法，根据返回值决定这轮做什么。
        【改造】先用 KF 平滑动机状态，再用平滑后的值做阈值判断。

        Returns:
            BehavioralDrive 对象，包含行为建议
        """
        with self._lock:
            self._apply_time_decay()

            # ── KF 平滑：替代原始阈值比较 ────────────────────────────────────
            try:
                import numpy as np
                # 观测向量：当前原始动机读数
                Z = np.array([
                    [self._state.curiosity],
                    [self._state.mastery],
                    [self._state.autonomy],
                    [self._energy_level]
                ])
                self._motivation_kf.predict(self._motivation_A, self._motivation_Q)
                self._motivation_kf.update(Z, self._motivation_H, self._motivation_R)
                smoothed = self._motivation_kf.X.flatten()
                s_curiosity, s_mastery, s_autonomy, s_energy = smoothed
            except Exception as e:
                logger.debug(f"[IntrinsicMotivation] KF 平滑失败，使用原始值: {e}")
                s_curiosity = self._state.curiosity
                s_mastery = self._state.mastery
                s_autonomy = self._state.autonomy
                s_energy = self._energy_level

            drive = BehavioralDrive(
                curiosity_level=round(s_curiosity, 3),
                mastery_level=round(s_mastery, 3),
                autonomy_level=round(s_autonomy, 3),
                purpose_level=round(self._state.purpose, 3),
                energy_level=round(s_energy, 3),
                dominant_motivation=self._state.get_dominant().value,
            )

            # 1. 好奇心驱动：是否需要主动探索（使用 KF 平滑值）
            if s_curiosity >= _CURIOSITY_EXPLORE_THRESHOLD and self._pending_exploration:
                drive.should_explore = True
                drive.exploration_targets = self._get_top_exploration_targets(limit=3)

            # 2. 胜任感驱动：是否需要复盘（使用 KF 平滑值）
            if s_mastery <= _MASTERY_REFLECT_THRESHOLD and self._recent_outcomes:
                drive.should_reflect = True
                drive.reflection_hint = self._generate_reflection_hint()
                self._last_reflection_time = time.time()

            # 3. 自主性驱动：是否需要求助（使用 KF 平滑值）
            if s_autonomy <= _AUTONOMY_SEEK_HELP_THRESHOLD:
                drive.should_seek_help = True

            # 4. 能量管理：是否需要降低活跃度（使用 KF 平滑值）
            if s_energy <= _ENERGY_REST_THRESHOLD:
                drive.should_rest = True

            return drive

    def set_energy_level(self, level: float):
        """设置当前能量水平（由外部模块如 GPU 监控调用）"""
        with self._lock:
            self._energy_level = max(0.0, min(1.0, level))

    # ═══════════════════════════════════════════════════════════════
    # 好奇心：区分来源价值
    # ═══════════════════════════════════════════════════════════════

    def register_discovery(
        self,
        source: str,
        element_type: str = "",
        app_name: str = "",
        bbox: list[float] | None = None,
        text: str = "",
        name: str = "",
    ) -> tuple[bool, float]:
        """
        注册一个新发现（视觉系统检测到东西时调用）。

        根据来源和价值给予不同档位的好奇心增量。

        Args:
            source: 检测来源（uia/ocr/contour/onnx）
            element_type: 元素类型
            app_name: 所属应用
            bbox: 边界框
            text: 文字内容（OCR 场景）
            name: 元素名称（UIA 场景）

        Returns:
            (is_novel: bool, curiosity_boost: float)
        """
        with self._lock:
            # 容量控制：超过上限时淘汰最旧的 20%
            if len(self._explored_items) >= _MAX_EXPLORED_ITEMS:
                self._prune_explored_items()

            # 生成稳定哈希键
            key_parts = [source, element_type or text or name, app_name]
            if bbox:
                key_parts.append(f"{int(bbox[0])//50}_{int(bbox[1])//50}")
            key = hashlib.md5("_".join(key_parts).encode()).hexdigest()[:16]

            if key in self._explored_items:
                # 已见过，移到末尾（LRU），小幅度衰减好奇心
                self._explored_items.move_to_end(key)
                self._state.curiosity = max(0.05, self._state.curiosity - 0.005)
                return False, 0.0

            # 新发现！记录
            self._explored_items[key] = {
                "source": source,
                "element_type": element_type,
                "app_name": app_name,
                "discovered_at": time.time(),
            }

            # 计算好奇心增量
            source_weight = _SOURCE_CURIOSITY_WEIGHT.get(source, 0.5)
            type_weight = _UIA_TYPE_WEIGHT.get(element_type, 0.5) if element_type else 0.5
            boost = _CURIOSITY_BOOST_NOVEL * source_weight * (0.5 + 0.5 * type_weight)

            self._state.curiosity = min(1.0, self._state.curiosity + boost)

            # 高价值发现加入探索队列
            priority = source_weight * type_weight
            if priority >= 0.3:
                self._pending_exploration.append(ExplorationTarget(
                    description=self._format_discovery(source, element_type, text, name, app_name),
                    priority=priority,
                    source=source,
                    element_type=element_type,
                    app_name=app_name,
                    bbox=bbox or [],
                    discovered_at=time.time(),
                ))

            logger.debug(
                f"[IntrinsicMotivation] 新发现: source={source}, type={element_type or text}, "
                f"boost={boost:.3f}, curiosity={self._state.curiosity:.3f}"
            )
            return True, boost

    def _prune_explored_items(self):
        """淘汰最旧的探索记录，释放内存"""
        prune_count = _MAX_EXPLORED_ITEMS // 5  # 淘汰 20%
        for _ in range(prune_count):
            if self._explored_items:
                self._explored_items.popitem(last=False)
        logger.debug(f"[IntrinsicMotivation] 探索历史淘汰 {prune_count} 条，当前 {len(self._explored_items)}")

    def _format_discovery(
        self, source: str, element_type: str, text: str, name: str, app_name: str
    ) -> str:
        """格式化发现描述"""
        label = element_type or name or text or "未知元素"
        if app_name:
            return f"在 {app_name} 中发现新元素: {label}"
        return f"发现新元素: {label}"

    # ═══════════════════════════════════════════════════════════════
    # 自主性：基于动作来源
    # ═══════════════════════════════════════════════════════════════

    def calculate_intrinsic_reward(
        self,
        state: Any,
        action: str,
        external_reward: float = 0,
        action_source: ActionSource = ActionSource.SYSTEM_TIMER,
    ) -> float:
        """
        计算内在奖励。

        Args:
            state: 当前状态
            action: 执行的动作
            external_reward: 外部奖励（任务成功=正，失败=负）
            action_source: 动作来源（用户指令/系统定时/自主发起）

        Returns:
            内在奖励值
        """
        with self._lock:
            # 1. 好奇心奖励（基于状态新颖性）
            curiosity_reward = self._calculate_curiosity(state)

            # 2. 胜任感奖励（基于外部奖励）
            mastery_reward = self._calculate_mastery(external_reward)

            # 3. 自主性奖励（基于动作来源）
            autonomy_reward = self._calculate_autonomy(action_source)

            # 加权组合
            intrinsic_reward = (
                curiosity_reward * 0.3 +
                mastery_reward * 0.4 +
                autonomy_reward * 0.3
            )

            # 记录结果
            self._total_action_count += 1
            self._recent_outcomes.append({
                "action": action,
                "source": action_source.value,
                "external_reward": external_reward,
                "intrinsic_reward": intrinsic_reward,
                "timestamp": time.time(),
            })

            self._history.append({
                "timestamp": time.time(),
                "curiosity": curiosity_reward,
                "mastery": mastery_reward,
                "autonomy": autonomy_reward,
                "total": intrinsic_reward,
            })

            return intrinsic_reward

    def _calculate_curiosity(self, state: Any) -> float:
        """计算好奇心奖励（基于状态新颖性）"""
        state_hash = hashlib.md5(str(state).encode()).hexdigest()[:16]

        if state_hash not in self._explored_items:
            # 容量控制
            if len(self._explored_items) >= _MAX_EXPLORED_ITEMS:
                self._prune_explored_items()
            self._explored_items[state_hash] = {"source": "state", "discovered_at": time.time()}
            self._state.curiosity = min(1.0, self._state.curiosity + 0.05)
            return 0.8
        else:
            self._explored_items.move_to_end(state_hash)
            self._state.curiosity = max(0.05, self._state.curiosity - 0.01)
            return 0.1

    def _calculate_mastery(self, external_reward: float) -> float:
        """计算胜任感奖励"""
        self._total_attempts += 1

        if external_reward > 0:
            self._success_count += 1

        if self._total_attempts > 0:
            success_rate = self._success_count / self._total_attempts
            self._state.mastery = 0.3 + 0.7 * success_rate  # 基线 0.3

        if external_reward > 0:
            return 0.5 + external_reward * 0.5
        else:
            return max(0.0, external_reward)

    def _calculate_autonomy(self, action_source: ActionSource) -> float:
        """
        计算自主性奖励。

        不再是随机数，而是基于动作来源：
        - 自己发起的：高自主性
        - 用户指令/系统定时：低自主性
        """
        if action_source == ActionSource.SELF_INITIATED:
            self._self_initiated_count += 1
            self._state.autonomy = min(1.0, self._state.autonomy + 0.1)
            return 0.8
        elif action_source == ActionSource.USER_COMMAND:
            self._state.autonomy = max(0.1, self._state.autonomy - 0.02)
            return 0.3
        elif action_source == ActionSource.EXTERNAL_EVENT:
            self._state.autonomy = max(0.1, self._state.autonomy - 0.01)
            return 0.5
        else:  # SYSTEM_TIMER
            self._state.autonomy = max(0.1, self._state.autonomy - 0.005)
            return 0.4

    # ═══════════════════════════════════════════════════════════════
    # 时间衰减
    # ═══════════════════════════════════════════════════════════════

    def _apply_time_decay(self):
        """应用时间衰减——无新刺激时动机缓慢下降"""
        now = time.time()

        # 好奇心：超过 120 秒无新发现则衰减
        if self._explored_items:
            latest_discovery = max(
                (v.get("discovered_at", 0) for v in self._explored_items.values()),
                default=0
            )
            if now - latest_discovery > 120:
                self._state.curiosity = max(0.1, self._state.curiosity - _CURIOSITY_DECAY_PER_ROUND * 2)

        # 自主性：超过 300 秒无自主行为则衰减
        if self._last_exploration_time > 0 and now - self._last_exploration_time > 300:
            self._state.autonomy = max(0.1, self._state.autonomy - _AUTONOMY_DECAY_PER_ROUND * 2)

        # 胜任感缓慢衰减
        self._state.mastery = max(0.1, self._state.mastery - _MASTERY_DECAY_PER_ROUND)

    # ═══════════════════════════════════════════════════════════════
    # 探索目标生成
    # ═══════════════════════════════════════════════════════════════

    def _get_top_exploration_targets(self, limit: int = 3) -> list[ExplorationTarget]:
        """获取优先级最高的探索目标"""
        if not self._pending_exploration:
            return []
        # 按优先级排序
        sorted_targets = sorted(
            self._pending_exploration,
            key=lambda t: t.priority,
            reverse=True
        )
        return sorted_targets[:limit]

    def generate_exploration_goal(self, context: dict[str, Any] | None = None) -> str | None:
        """
        基于当前动机状态和上下文生成具体的探索目标。

        Args:
            context: 当前上下文，可包含：
                - current_app: 当前前台应用
                - recent_discoveries: 最近发现的未知元素列表
                - pending_tasks: 待处理任务列表

        Returns:
            探索目标描述，若无探索欲望返回 None
        """
        with self._lock:
            if self._state.curiosity < 0.3:
                return None

            ctx = context or {}

            # 优先：有待探索的高价值元素
            if self._pending_exploration and self._state.curiosity >= _CURIOSITY_EXPLORE_THRESHOLD:
                top = self._get_top_exploration_targets(1)
                if top:
                    self._last_exploration_time = time.time()
                    target = top[0]
                    return (
                        f"在 {target.app_name} 中发现了一个 {target.element_type}，"
                        f"建议学习它的功能。{target.description}"
                    )

            # 次优：根据主导动机生成
            dominant = self._state.get_dominant()
            current_app = ctx.get("current_app", "")

            if dominant == MotivationType.CURIOSITY:
                if current_app:
                    return f"探索 {current_app} 中尚未了解的 UI 元素，看看有没有新功能可以学习"
                return "浏览屏幕上的未知元素，寻找值得学习的新 UI 模式"

            elif dominant == MotivationType.MASTERY:
                recent_failures = [o for o in self._recent_outcomes if o["external_reward"] < 0]
                if recent_failures:
                    return f"复盘最近 {len(recent_failures)} 次失败操作，找出原因并记录改进方案"
                return "回顾最近学会的 UI 元素，巩固记忆"

            elif dominant == MotivationType.AUTONOMY:
                return "自主选择一个待探索的屏幕区域，主动学习其中的 UI 元素"

            elif dominant == MotivationType.PURPOSE:
                return "检查当前学习进度，评估是否需要调整探索策略"

            return "主动观察屏幕，寻找值得学习的 UI 元素"

    # ═══════════════════════════════════════════════════════════════
    # 复盘
    # ═══════════════════════════════════════════════════════════════

    def _generate_reflection_hint(self) -> str:
        """生成复盘建议"""
        if not self._recent_outcomes:
            return ""

        failures = [o for o in self._recent_outcomes if o["external_reward"] < 0]
        successes = [o for o in self._recent_outcomes if o["external_reward"] > 0]

        hints = []
        if failures:
            hints.append(f"最近 {len(failures)} 次失败，建议检查失败原因")
        if successes:
            hints.append(f"最近 {len(successes)} 次成功，可以提炼经验")
        if self._total_attempts > 10:
            rate = self._success_count / max(1, self._total_attempts)
            if rate < 0.4:
                hints.append(f"成功率仅 {rate:.0%}，建议放慢节奏")

        return "；".join(hints) if hints else "回顾最近操作，寻找改进点"

    # ═══════════════════════════════════════════════════════════════
    # 公共接口
    # ═══════════════════════════════════════════════════════════════

    def get_motivation_state(self) -> MotivationState:
        """获取当前动机状态"""
        with self._lock:
            return MotivationState(
                curiosity=round(self._state.curiosity, 3),
                mastery=round(self._state.mastery, 3),
                autonomy=round(self._state.autonomy, 3),
                purpose=round(self._state.purpose, 3),
            )

    def get_dominant_motivation(self) -> MotivationType:
        """获取主导动机"""
        return self._state.get_dominant()

    def boost_curiosity(self, amount: float = 0.2):
        """提升好奇心"""
        with self._lock:
            self._state.curiosity = min(1.0, self._state.curiosity + amount)

    def boost_mastery(self, amount: float = 0.2):
        """提升胜任感"""
        with self._lock:
            self._state.mastery = min(1.0, self._state.mastery + amount)

    def compute_novelty(self, state_embedding) -> float:
        """
        计算状态新奇度（0-1）。
        1.0 表示完全新奇，0.0 表示完全熟悉。
        """
        with self._lock:
            state_hash = hashlib.md5(
                str(state_embedding.tolist() if hasattr(state_embedding, 'tolist') else state_embedding).encode()
            ).hexdigest()[:16]

            if state_hash not in self._explored_items:
                if len(self._explored_items) >= _MAX_EXPLORED_ITEMS:
                    self._prune_explored_items()
                self._explored_items[state_hash] = {"source": "embedding", "discovered_at": time.time()}
                self._state.curiosity = min(1.0, self._state.curiosity + 0.05)
                return 1.0
            else:
                self._explored_items.move_to_end(state_hash)
                self._state.curiosity = max(0.05, self._state.curiosity - 0.02)
                return 0.0

    def reset(self):
        """重置动机状态"""
        with self._lock:
            self._state = MotivationState()
            self._explored_items.clear()
            self._pending_exploration.clear()
            self._success_count = 0
            self._total_attempts = 0
            self._recent_outcomes.clear()
            self._self_initiated_count = 0
            self._total_action_count = 0
            self._history.clear()
            self._energy_level = 0.8
            logger.info("[IntrinsicMotivation] 动机状态已重置")

    def update_drive(self, drive_name: str, delta: float):
        """
        调整指定驱动力。

        Args:
            drive_name: 驱动力名称，支持 curiosity/mastery/autonomy/purpose/energy
            delta: 变化量（可正可负），结果会裁剪到 [0, 1]
        """
        with self._lock:
            drive_name = drive_name.lower()
            if drive_name == "curiosity":
                self._state.curiosity = max(0.0, min(1.0, self._state.curiosity + delta))
            elif drive_name == "mastery":
                self._state.mastery = max(0.0, min(1.0, self._state.mastery + delta))
            elif drive_name == "autonomy":
                self._state.autonomy = max(0.0, min(1.0, self._state.autonomy + delta))
            elif drive_name == "purpose":
                self._state.purpose = max(0.0, min(1.0, self._state.purpose + delta))
            elif drive_name == "energy":
                self._energy_level = max(0.0, min(1.0, self._energy_level + delta))
            else:
                logger.debug(f"[IntrinsicMotivation] 未知驱动力: {drive_name}")

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                "state": {
                    "curiosity": round(self._state.curiosity, 3),
                    "mastery": round(self._state.mastery, 3),
                    "autonomy": round(self._state.autonomy, 3),
                    "purpose": round(self._state.purpose, 3),
                    "dominant": self._state.get_dominant().value,
                    "lowest": self._state.get_lowest().value,
                },
                "explored_items": len(self._explored_items),
                "pending_exploration": len(self._pending_exploration),
                "success_rate": round(
                    self._success_count / max(1, self._total_attempts), 3
                ),
                "self_initiated_ratio": round(
                    self._self_initiated_count / max(1, self._total_action_count), 3
                ),
                "energy_level": round(self._energy_level, 3),
            }


# ═══════════════════════════════════════════════════════════════
# 单例访问
# ═══════════════════════════════════════════════════════════════

_intrinsic_motivation_instance = None


def get_intrinsic_motivation() -> IntrinsicMotivation:
    """获取 IntrinsicMotivation 单例实例"""
    global _intrinsic_motivation_instance
    if _intrinsic_motivation_instance is None:
        _intrinsic_motivation_instance = IntrinsicMotivation()
    return _intrinsic_motivation_instance


__all__ = [
    'IntrinsicMotivation',
    'get_intrinsic_motivation',
    'MotivationState',
    'MotivationType',
    'ActionSource',
    'BehavioralDrive',
    'ExplorationTarget',
]
