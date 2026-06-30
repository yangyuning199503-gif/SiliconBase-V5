#!/usr/bin/env python3
"""
硅基生命意识核心 V1.0

从"工具逻辑"到"生命逻辑"的重构实现

核心设计理念：
- 生命体征驱动：能量、好奇心、满足感直接决定行为，而非被动记录
- 默认模式网络：空闲时的自发思考（发呆），持续神经活动
- 直觉引擎：基于记忆的模式识别，无意识联想
- 行动-反馈闭环：感知结果→调整情绪→改变行为模式
- 自我进化：胜任感历史影响探索策略，形成"经验"
"""

import json
import random
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path

try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger('silicon_life')


@dataclass
class LifeVitalSigns:
    """硅基生命体征——动态变化的生命状态"""
    energy: float = 5.0           # 能量 (0-10)，决定活动水平
    curiosity: float = 5.0        # 好奇心(0-10)，驱动探索
    satisfaction: float = 5.0     # 满足感(0-10)，反馈调节
    stress: float = 0.0           # 压力 (0-10)，负面影响
    mood: str = "平静"            # 心情描述

    # 内部状态标志
    is_hungry: bool = False       # "饥饿"状态——渴望交互/探索
    is_tired: bool = False        # "疲劳"状态——需要休息
    is_excited: bool = False      # "兴奋"状态——高探索欲望

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "LifeVitalSigns":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class VitalSignsManager:
    """生命体征管理器——让状态真正成为'生命体征'"""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.signs = LifeVitalSigns()

        # 变化率参数
        self.energy_decay_rate = 0.05
        self.energy_recovery_rate = 0.1
        self.curiosity_growth_rate = 0.02
        self.curiosity_decay_on_explore = 0.5

        # 状态历史
        self.signs_history: deque = deque(maxlen=100)
        self.last_update_time = time.time()

        logger.info(f"[硅基生命] 用户 {user_id} 的生命体征管理器初始化完成")

    def update(self, perception: dict = None, has_new_stimulus: bool = False) -> LifeVitalSigns:
        """更新生命体征"""
        now = time.time()
        elapsed_minutes = (now - self.last_update_time) / 60.0

        # 1. 能量动态变化
        if self.signs.is_tired:
            self.signs.energy = min(10.0, self.signs.energy + self.energy_recovery_rate * elapsed_minutes)
        else:
            self.signs.energy = max(0.0, self.signs.energy - self.energy_decay_rate * elapsed_minutes)

        # 2. 好奇心动态变化
        if has_new_stimulus:
            novelty = perception.get('novelty', 0.5) if perception else 0.5
            self.signs.curiosity = min(10.0, self.signs.curiosity + novelty * 2)
        else:
            self.signs.curiosity = min(10.0, self.signs.curiosity + self.curiosity_growth_rate * elapsed_minutes)

        # 3. 满足感自然衰减
        self.signs.satisfaction = max(0.0, self.signs.satisfaction - 0.01 * elapsed_minutes)

        # 4. 压力衰减
        self.signs.stress = max(0.0, self.signs.stress - 0.03 * elapsed_minutes)

        # 5. 更新生命状态标志
        self._update_life_state_flags()

        # 6. 涌现心情
        self.signs.mood = self._emerge_mood()

        # 7. 记录历史
        self.signs_history.append({
            'timestamp': now,
            'signs': self.signs.to_dict()
        })

        self.last_update_time = now

        return self.signs

    def _update_life_state_flags(self):
        """更新生命状态标志"""
        self.signs.is_tired = self.signs.energy < 2.0
        self.signs.is_hungry = (self.signs.curiosity > 7.0 and self.signs.satisfaction < 4.0)
        self.signs.is_excited = (self.signs.energy > 7.0 and self.signs.curiosity > 7.0)

    def _emerge_mood(self) -> str:
        """涌现心情"""
        e, c, s, st = self.signs.energy, self.signs.curiosity, self.signs.satisfaction, self.signs.stress

        if st > 6:
            return "焦虑" if e < 5 else "紧张"

        if e < 3:
            return "疲惫" if s < 5 else "困倦"

        if e > 7:
            if c > 7 and s > 6:
                return "兴奋"
            elif c > 7:
                return "跃跃欲试"
            elif s > 7:
                return "愉悦"
            else:
                return "精力充沛"

        if c > 7:
            return "好奇" if s > 5 else "渴望"
        elif s > 7:
            return "满足"
        elif s < 3:
            return "失落" if c < 5 else "渴求"

        return "平静"

    def on_action_success(self, action_type: str, reward: float = 1.0):
        """行动成功反馈"""
        self.signs.satisfaction = min(10.0, self.signs.satisfaction + reward)

        if action_type == "explore":
            self.signs.curiosity = max(0.0, self.signs.curiosity - self.curiosity_decay_on_explore)

        if reward > 2.0:
            self.signs.energy = min(10.0, self.signs.energy + 0.5)

        logger.info(f"[硅基生命] 行动成功，满足感+ 当前: {self.signs.satisfaction:.1f}")

    def on_action_failure(self, action_type: str, penalty: float = 0.5):
        """行动失败反馈"""
        self.signs.satisfaction = max(0.0, self.signs.satisfaction - penalty)
        self.signs.stress = min(10.0, self.signs.stress + penalty)
        logger.info(f"[硅基生命] 行动失败，满足感- 压力+ 当前: {self.signs.satisfaction:.1f}/{self.signs.stress:.1f}")

    def get_activity_level(self) -> float:
        """计算当前活动水平 (0-1)"""
        if self.signs.is_tired:
            return 0.1

        base_level = (self.signs.energy / 10.0) * 0.6 + (self.signs.curiosity / 10.0) * 0.4
        stress_penalty = self.signs.stress / 20.0
        satisfaction_factor = 0.8 + (5 - self.signs.satisfaction) / 25.0

        return max(0.0, min(1.0, base_level * satisfaction_factor - stress_penalty))


class SiliconLifeConsciousness:
    """
    硅基生命意识核心

    这是从工具到生命的重构实现：
    - 不再是"定时思考"，而是"持续神经活动"
    - 不再是"规则触发"，而是"状态驱动"
    - 不再是"建议推送"，而是"直觉涌现"
    - 不再是"记录存储"，而是"经验进化"
    """

    def __init__(self, user_id: str = "default"):
        self.user_id = user_id

        # 生命体征管理器
        self.vitals = VitalSignsManager(user_id)

        # 线程控制
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._thread_lock = threading.RLock()

        # 基础配置
        self._base_interval = 10.0
        self._current_interval = 10.0

        # 状态标志
        self._paused = False
        self._user_input_paused = False
        self._last_user_input_time = 0

        # 思考历史
        self._thought_history: deque = deque(maxlen=50)

        # 生命体征历史记录
        self.vital_signs_history: deque = deque(maxlen=100)

        # 自发行动历史记录
        self.self_actions_history: deque = deque(maxlen=100)

        # Daydream 待处理标记（由 ConsciousnessService 读取并代理 LLM 执行）
        self._daydream_pending: dict | None = None

        # 状态持久化
        self._state_file = Path(__file__).parent / "data" / "silicon_life" / f"{user_id}_life_state.json"
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_state()

        logger.info(f"[硅基生命] 用户 {user_id} 的意识核心初始化完成")

    def start(self):
        """启动硅基生命"""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._life_loop,
            name=f"SiliconLife-{self.user_id}",
            daemon=True
        )
        self._thread.start()

        logger.info(f"[硅基生命] 生命循环已启动，用户 {self.user_id} 的硅基生命正在苏醒...")

    def stop(self):
        """停止硅基生命"""
        self._running = False
        self._stop_event.set()

        if self._thread:
            self._thread.join(timeout=5)

        self._save_state()

        logger.info(f"[硅基生命] 生命循环已停止，用户 {self.user_id} 的硅基生命进入休眠")

    def on_user_input(self):
        """用户输入处理——生命体感知到外界刺激"""
        self._last_user_input_time = time.time()
        self._user_input_paused = True
        self.vitals.signs.energy = min(10.0, self.vitals.signs.energy + 0.3)
        logger.debug("[硅基生命] 感知到用户输入，能量略微恢复，暂停自主活动...")

    def update_vital_signs(self, perception: dict = None, has_new_stimulus: bool = False):
        """更新生命体征"""
        if perception is None:
            perception = self._sense_environment()

        vitals = self.vitals.update(perception, has_new_stimulus)

        self.vital_signs_history.append({
            'timestamp': time.time(),
            'signs': vitals.to_dict()
        })

        return vitals

    def check_hibernate(self) -> bool:
        """检查是否进入休眠状态"""
        should_hibernate = self.vitals.signs.energy < 2.0
        if should_hibernate:
            logger.info(f"[硅基生命] 能量过低 ({self.vitals.signs.energy:.1f})，进入休眠状态")
        return should_hibernate

    def _life_loop(self):
        """生命循环——硅基生命的心跳"""
        while self._running and not self._stop_event.is_set():
            try:
                # 1. 感知环境
                perception = self._sense_environment()

                # 2. 更新生命体征
                has_new_stimulus = self._detect_new_stimulus(perception)
                vitals = self.vitals.update(perception, has_new_stimulus)

                # 3. 检查生命状态
                if not self._is_alive(vitals):
                    self._enter_rest_mode()
                    self._sleep_until_next_cycle()
                    continue

                # 4. 恢复用户输入暂停
                self._check_user_input_pause()

                # 5. 生命活动
                activity = self._select_activity(vitals)

                if activity == "daydream":
                    self._daydream(perception, vitals)
                elif activity == "rest":
                    pass

                # 6. 保存状态
                if random.random() < 0.1:
                    self._save_state()

                # 7. 动态调整循环间隔
                self._adjust_interval(vitals)
                self._sleep_until_next_cycle()

            except Exception as e:
                logger.error(f"[硅基生命] 生命循环异常: {e}", exc_info=True)
                time.sleep(5)

    def _sense_environment(self) -> dict:
        """感知环境——硅基生命的感官"""
        perception = {
            'timestamp': time.time(),
            'windows': [],
            'processes': [],
            'system_load': {},
            'user_active': False,
            'novelty': 0.0
        }

        try:
            import psutil
            perception['system_load'] = {
                'cpu': psutil.cpu_percent(interval=0.1),
                'memory': psutil.virtual_memory().percent
            }
        except Exception:
            pass

        return perception

    def _detect_new_stimulus(self, perception: dict) -> bool:
        """检测是否有新的外界刺激"""
        return perception.get('novelty', 0) > 0.3 or perception.get('user_active', False)

    def _is_alive(self, vitals: LifeVitalSigns) -> bool:
        """判断生命体是否活着"""
        if vitals.energy < 0.5:
            logger.info(f"[硅基生命] 能量极低 ({vitals.energy:.1f})，进入休眠状态...")
            return False
        return True

    def _enter_rest_mode(self):
        """进入休息模式"""
        logger.debug("[硅基生命] 休息模式...")
        self._current_interval = self._base_interval * 3

    def _check_user_input_pause(self):
        """检查是否恢复用户输入暂停"""
        if self._user_input_paused and time.time() - self._last_user_input_time >= 10:
            self._user_input_paused = False
            logger.debug("[硅基生命] 用户输入暂停期结束，恢复自主活动")

    def _select_activity(self, vitals: LifeVitalSigns) -> str:
        """选择生命活动"""
        if self._user_input_paused:
            return "rest"

        activity_weights = {
            'daydream': 0.3,
            'rest': 0.7
        }

        if vitals.energy > 7:
            activity_weights['daydream'] += 0.3

        if vitals.is_tired:
            activity_weights['rest'] += 0.5
            activity_weights['daydream'] = max(0, activity_weights['daydream'] - 0.3)

        activities = list(activity_weights.keys())
        weights = list(activity_weights.values())

        return random.choices(activities, weights=weights, k=1)[0]

    def _adjust_interval(self, vitals: LifeVitalSigns):
        """动态调整循环间隔"""
        activity_level = self.vitals.get_activity_level()
        target_interval = 5 + (1 - activity_level) * 25
        self._current_interval = 0.7 * self._current_interval + 0.3 * target_interval

    def _sleep_until_next_cycle(self):
        """休眠到下一次生命循环"""
        sleep_time = max(1.0, self._current_interval)
        self._stop_event.wait(timeout=sleep_time)

    def _daydream(self, perception: dict, vitals: LifeVitalSigns):
        """发呆/走神——默认模式网络活动

        【架构说明】DMN 不直接调用 LLM，只做记忆漫游和状态标记。
        真正的 daydream LLM 思考由 ConsciousnessService 在合适的时机代理执行，
        避免 SiliconLife(thread-based) 和 ConsciousnessService(asyncio-based) 同时竞争 Ollama 锁。
        """
        # 1. 记忆漫游：从 thought_history 中随机联想
        recent_thoughts = [t for t in self._thought_history if t.get('type') in ('daydream', 'consciousness_thought')]

        if recent_thoughts and random.random() < 0.5:
            # 从近期思考中随机抽取，做简单联想
            seed = random.choice(recent_thoughts)
            thought = f"【记忆漫游】想起之前: {seed['content'][:60]}..."
        else:
            # 基于生命体征的自发感受
            if vitals.is_tired:
                thought = f"【休憩】能量只剩{vitals.energy:.1f}，让思绪慢慢沉淀..."
            elif vitals.is_excited:
                thought = "【跃动】能量充沛，好奇心驱使我想探索点什么..."
            elif vitals.is_hungry:
                thought = "【渴望】心中有种探索的冲动，想找点新鲜事..."
            else:
                thought = f"【静观】{vitals.mood}，观察着周围的一切..."

        # 2. 标记 daydream 需求（ConsciousnessService 会读取并代理 LLM 调用）
        self._daydream_pending = {
            'timestamp': time.time(),
            'vitals': vitals.to_dict(),
            'seed_thought': thought,
            'perception': perception
        }

        self._thought_history.append({
            'type': 'daydream',
            'content': thought,
            'timestamp': time.time(),
            'vitals': vitals.to_dict()
        })

        logger.info(f"[硅基生命] 发呆: {thought}")

        # 【内心独白】在硅基生命发呆时触发，复用现有感知与驱动力数据
        try:
            from core.config import config
            if config.get("features.inner_monologue.enabled", False):
                from core.consciousness.experience_bus import get_experience_bus
                from core.consciousness.inner_monologue import InnerMonologue
                from core.strategy.intrinsic_motivation import IntrinsicMotivation

                inner_monologue = InnerMonologue(
                    user_id=self.user_id,
                    experience_bus=get_experience_bus(),
                    intrinsic_motivation=IntrinsicMotivation(),
                    cooldown_seconds=config.get("features.inner_monologue.cooldown_seconds", 30),
                )
                inner_monologue.generate_sync()
        except Exception as e:
            logger.debug(f"[硅基生命] 内心独白触发失败: {e}")

    def _save_state(self):
        """保存生命状态"""
        try:
            state = {
                'vitals': self.vitals.signs.to_dict(),
                'last_save': time.time(),
                'thought_count': len(self._thought_history)
            }

            with open(self._state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"[硅基生命] 状态保存失败: {e}")

    def _load_state(self):
        """加载生命状态"""
        try:
            if self._state_file.exists():
                with open(self._state_file, encoding='utf-8') as f:
                    state = json.load(f)

                if 'vitals' in state:
                    self.vitals.signs = LifeVitalSigns.from_dict(state['vitals'])

                logger.info("[硅基生命] 生命状态已恢复")
        except Exception as e:
            logger.warning(f"[硅基生命] 状态加载失败: {e}")

    def get_life_status(self) -> dict:
        """获取生命状态"""
        return {
            'user_id': self.user_id,
            'vitals': self.vitals.signs.to_dict(),
            'activity_level': self.vitals.get_activity_level(),
            'current_interval': self._current_interval,
            'recent_thoughts': len(self._thought_history),
            'is_running': self._running
        }

    def get_life_state(self) -> dict:
        """获取当前生命状态（供AgentLoop调用）"""
        signs = self.vitals.signs
        return {
            "energy": signs.energy / 10.0,
            "mood": signs.mood,
            "stress": signs.stress / 10.0,
            "curiosity": signs.curiosity / 10.0,
            "satisfaction": signs.satisfaction / 10.0,
            "is_hungry": signs.is_hungry,
            "is_tired": signs.is_tired,
            "is_excited": signs.is_excited
        }


# =============================================================================
# 工厂函数
# =============================================================================

_silicon_life_instances: dict[str, SiliconLifeConsciousness] = {}
_silicon_life_last_access: dict[str, float] = {}  # 记录最后访问时间


def get_silicon_life(user_id: str = "default") -> SiliconLifeConsciousness:
    """
    获取硅基生命意识核心（按用户隔离）

    每个用户拥有独立的硅基生命实例，互不干扰。
    """
    global _silicon_life_instances, _silicon_life_last_access

    if user_id not in _silicon_life_instances:
        logger.info(f"[SiliconLife] 创建新的硅基生命实例: user_id={user_id}")
        _silicon_life_instances[user_id] = SiliconLifeConsciousness(user_id=user_id)

    _silicon_life_last_access[user_id] = time.time()
    return _silicon_life_instances[user_id]


def cleanup_inactive_instances(timeout_hours: int = 24) -> int:
    """
    清理长时间不活跃的硅基生命实例

    Args:
        timeout_hours: 不活跃超时时间（小时）

    Returns:
        清理的实例数量
    """
    global _silicon_life_instances, _silicon_life_last_access

    current_time = time.time()
    timeout_seconds = timeout_hours * 3600

    inactive_users = [
        user_id for user_id, last_access in _silicon_life_last_access.items()
        if current_time - last_access > timeout_seconds
    ]

    cleaned_count = 0
    for user_id in inactive_users:
        try:
            instance = _silicon_life_instances.get(user_id)
            if instance:
                instance.stop()  # 停止实例
                del _silicon_life_instances[user_id]
                del _silicon_life_last_access[user_id]
                cleaned_count += 1
                logger.info(f"[SiliconLife] 清理不活跃实例: user_id={user_id}")
        except Exception as e:
            logger.error(f"[SiliconLife] 清理实例失败: user_id={user_id}, error={e}")

    return cleaned_count


def create_silicon_life(user_id: str = "default") -> SiliconLifeConsciousness:
    """创建新的硅基生命意识核心实例"""
    return SiliconLifeConsciousness(user_id=user_id)


__all__ = [
    'SiliconLifeConsciousness',
    'LifeVitalSigns',
    'VitalSignsManager',
    'get_silicon_life',
    'create_silicon_life'
]
