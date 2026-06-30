#!/usr/bin/env python3
"""
进化系统 - 核心实现

提供AI的自我进化能力：
- 经验管理（记录、检索、更新）
- 进化引擎（基于经验的策略优化）
- 增强进化引擎（支持复杂场景）
- 知识积累与传承

设计目标：
- 从每次交互中学习
- 积累可复用的经验
- 持续优化任务执行策略
- 实现能力的螺旋式上升
"""

import json
import random
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger('evolution')


@dataclass
class Experience:
    """经验记录"""
    experience_id: str
    task_type: str
    task_description: str
    approach: str           # 采取的方法
    outcome: str           # 结果 (success/failure/partial)
    effectiveness: float   # 效果评分 (0-1)
    context: dict[str, Any] = field(default_factory=dict)
    lessons: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    use_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def value_score(self) -> float:
        """计算经验价值分"""
        recency = 1.0 / (1 + (time.time() - self.created_at) / 86400)  # 24小时内为1，随时间衰减
        usage = min(1.0, self.use_count / 10)  # 使用10次以上为1
        return self.effectiveness * 0.5 + recency * 0.3 + usage * 0.2


@dataclass
class EvolutionStrategy:
    """进化策略"""
    strategy_id: str
    name: str
    description: str
    applicable_task_types: list[str]
    rules: list[dict[str, Any]]  # 策略规则
    success_rate: float = 0.0
    use_count: int = 0
    created_from_experience: str | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


class ExperienceManager:
    """
    经验管理器

    负责经验的存储、检索、更新和评估
    """

    def __init__(self, storage_path: str | None = None):
        self._experiences: dict[str, Experience] = {}
        self._tag_index: dict[str, list[str]] = defaultdict(list)
        self._type_index: dict[str, list[str]] = defaultdict(list)

        self._storage_path = storage_path
        self._max_experiences = 1000

        if storage_path:
            self._load_from_storage()

        logger.info(f"【经验管理器】初始化完成，当前经验数: {len(self._experiences)}")

    def add_experience(self,
                       task_type: str,
                       task_description: str,
                       approach: str,
                       outcome: str,
                       effectiveness: float,
                       context: dict = None,
                       lessons: list[str] = None,
                       tags: list[str] = None) -> Experience:
        """
        添加新经验

        Args:
            task_type: 任务类型
            task_description: 任务描述
            approach: 采取的方法
            outcome: 结果
            effectiveness: 效果评分
            context: 上下文
            lessons: 经验教训
            tags: 标签

        Returns:
            Experience: 创建的经验记录
        """
        exp_id = f"exp_{int(time.time())}_{random.randint(1000, 9999)}"

        experience = Experience(
            experience_id=exp_id,
            task_type=task_type,
            task_description=task_description,
            approach=approach,
            outcome=outcome,
            effectiveness=effectiveness,
            context=context or {},
            lessons=lessons or [],
            tags=tags or []
        )

        self._experiences[exp_id] = experience

        # 更新索引
        for tag in experience.tags:
            self._tag_index[tag].append(exp_id)
        self._type_index[task_type].append(exp_id)

        # 清理过期经验
        self._cleanup_if_needed()

        # 持久化
        if self._storage_path:
            self._save_to_storage()

        logger.info(f"【经验管理器】添加经验 {exp_id} 类型:{task_type} 效果:{effectiveness:.2f}")

        return experience

    def get_experience(self, exp_id: str) -> Experience | None:
        """获取经验"""
        return self._experiences.get(exp_id)

    def find_similar_experiences(self,
                                  task_type: str,
                                  context: dict = None,
                                  outcome: str = None,
                                  limit: int = 5) -> list[Experience]:
        """
        查找相似经验

        Args:
            task_type: 任务类型
            context: 上下文匹配
            outcome: 结果筛选
            limit: 返回数量

        Returns:
            List[Experience]: 匹配的经验列表
        """
        candidates = []

        # 从类型索引获取
        for exp_id in self._type_index.get(task_type, []):
            exp = self._experiences.get(exp_id)
            if exp and (outcome is None or exp.outcome == outcome):
                candidates.append(exp)

        # 按价值分排序
        candidates.sort(key=lambda e: e.value_score, reverse=True)

        return candidates[:limit]

    def update_experience(self, exp_id: str, updates: dict[str, Any]) -> bool:
        """更新经验"""
        exp = self._experiences.get(exp_id)
        if not exp:
            return False

        for key, value in updates.items():
            if hasattr(exp, key):
                setattr(exp, key, value)

        exp.last_used = time.time()

        if self._storage_path:
            self._save_to_storage()

        return True

    def record_usage(self, exp_id: str):
        """记录经验使用"""
        exp = self._experiences.get(exp_id)
        if exp:
            exp.use_count += 1
            exp.last_used = time.time()

    def get_lessons_for_task_type(self, task_type: str) -> list[str]:
        """获取某类任务的经验教训"""
        lessons = []
        for exp_id in self._type_index.get(task_type, []):
            exp = self._experiences.get(exp_id)
            if exp and exp.lessons:
                lessons.extend(exp.lessons)
        return list(set(lessons))  # 去重

    def _cleanup_if_needed(self):
        """清理过期经验"""
        if len(self._experiences) <= self._max_experiences:
            return

        # 按价值分排序，删除低价值的
        sorted_exps = sorted(self._experiences.values(), key=lambda e: e.value_score)
        to_remove = len(sorted_exps) - self._max_experiences

        for exp in sorted_exps[:to_remove]:
            del self._experiences[exp.experience_id]
            # 更新索引
            for tag in exp.tags:
                if exp.experience_id in self._tag_index[tag]:
                    self._tag_index[tag].remove(exp.experience_id)
            if exp.experience_id in self._type_index[exp.task_type]:
                self._type_index[exp.task_type].remove(exp.experience_id)

        logger.info(f"【经验管理器】清理了 {to_remove} 条过期经验")

    def _save_to_storage(self):
        """保存到存储"""
        try:
            data = {
                'experiences': {k: v.to_dict() for k, v in self._experiences.items()},
                'metadata': {
                    'saved_at': time.time(),
                    'count': len(self._experiences)
                }
            }
            with open(self._storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"【经验管理器】保存失败: {e}")

    def _load_from_storage(self):
        """从存储加载"""
        try:
            import os
            if not os.path.exists(self._storage_path):
                return

            with open(self._storage_path, encoding='utf-8') as f:
                data = json.load(f)

            for exp_id, exp_data in data.get('experiences', {}).items():
                exp = Experience(**exp_data)
                self._experiences[exp_id] = exp

                # 重建索引
                for tag in exp.tags:
                    self._tag_index[tag].append(exp_id)
                self._type_index[exp.task_type].append(exp_id)

            logger.info(f"【经验管理器】加载了 {len(self._experiences)} 条经验")
        except Exception as e:
            logger.warning(f"【经验管理器】加载失败: {e}")

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        total = len(self._experiences)
        if total == 0:
            return {'total': 0}

        success_count = sum(1 for e in self._experiences.values() if e.outcome == 'success')

        return {
            'total': total,
            'success_count': success_count,
            'success_rate': success_count / total,
            'avg_effectiveness': sum(e.effectiveness for e in self._experiences.values()) / total,
            'task_types': len(self._type_index),
            'tags': len(self._tag_index)
        }


class EvolutionEngine:
    """
    进化引擎

    基于经验进行策略进化

    【线程安全】
    - 使用单例模式确保全局唯一实例
    - 使用 RLock 保护共享数据访问
    - 关键操作（学习、策略生成）受锁保护
    """

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        # 双检锁确保线程安全的单例
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True

        # 线程锁保护共享数据
        self._lock = threading.RLock()

        self._experience_manager = ExperienceManager()
        self._strategies: dict[str, EvolutionStrategy] = {}
        self._evolution_history: list[dict] = []

        logger.info("【进化引擎】初始化完成")

    def learn_from_execution(self,
                            task_type: str,
                            task_description: str,
                            approach: str,
                            outcome: str,
                            effectiveness: float,
                            context: dict = None) -> Experience | None:
        """
        从执行中学习

        Args:
            task_type: 任务类型
            task_description: 任务描述
            approach: 采取的方法
            outcome: 结果
            effectiveness: 效果
            context: 上下文

        Returns:
            Optional[Experience]: 创建的经验，失败返回 None
        """
        # 参数校验
        if not task_type or not approach:
            logger.warning("【进化引擎】学习失败: task_type 和 approach 不能为空")
            return None

        # 使用锁保护共享数据操作
        with self._lock:
            try:
                # 提取经验教训
                lessons = self._extract_lessons(outcome, effectiveness)

                # 创建经验
                experience = self._experience_manager.add_experience(
                    task_type=task_type,
                    task_description=task_description or "",
                    approach=approach,
                    outcome=outcome or "unknown",
                    effectiveness=max(0.0, min(1.0, effectiveness)),  # 限制在0-1范围
                    context=context or {},
                    lessons=lessons,
                    tags=[task_type, outcome]
                )

                if experience is None:
                    logger.warning("【进化引擎】添加经验失败")
                    return None

                # 如果成功且效果好，尝试生成策略
                if outcome == 'success' and effectiveness > 0.7:
                    self._generate_strategy_from_experience(experience)

                # 记录进化历史
                self._evolution_history.append({
                    'type': 'learn',
                    'experience_id': experience.experience_id,
                    'timestamp': time.time()
                })

                return experience
            except Exception as e:
                logger.error(f"【进化引擎】学习过程出错: {e}", exc_info=True)
                return None

    def _extract_lessons(self, outcome: str, effectiveness: float) -> list[str]:
        """提取经验教训"""
        lessons = []

        if outcome == 'success':
            if effectiveness > 0.8:
                lessons.append("该方法非常有效，应作为首选策略")
            else:
                lessons.append("方法可行，但仍有优化空间")
        elif outcome == 'failure':
            lessons.append("当前方法不适合该场景，需要尝试其他方案")
        else:
            lessons.append("部分成功，需要分析哪些环节可以改进")

        return lessons

    def _generate_strategy_from_experience(self, experience: Experience):
        """从经验生成策略"""
        strategy_id = f"strategy_{experience.experience_id}"

        strategy = EvolutionStrategy(
            strategy_id=strategy_id,
            name=f"{experience.task_type}策略",
            description=f"基于经验 {experience.experience_id} 生成的策略",
            applicable_task_types=[experience.task_type],
            rules=[{'approach': experience.approach, 'context': experience.context}],
            success_rate=experience.effectiveness,
            created_from_experience=experience.experience_id
        )

        self._strategies[strategy_id] = strategy

        logger.info(f"【进化引擎】从经验生成策略 {strategy_id}")

    def get_recommended_approach(self, task_type: str, context: dict = None) -> str | None:
        """获取推荐方法"""
        # 查找相似经验
        similar = self._experience_manager.find_similar_experiences(
            task_type=task_type,
            outcome='success',
            limit=3
        )

        if similar:
            # 返回效果最好的经验的方法
            best = max(similar, key=lambda e: e.effectiveness)
            self._experience_manager.record_usage(best.experience_id)
            return best.approach

        # 查找适用策略
        for strategy in self._strategies.values():
            if task_type in strategy.applicable_task_types and strategy.rules:
                return strategy.rules[0].get('approach')

        return None

    def get_experience_for_task(self, task_type: str, limit: int = 3) -> list[Experience]:
        """获取任务相关经验"""
        return self._experience_manager.find_similar_experiences(
            task_type=task_type,
            limit=limit
        )

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return {
            'experience_stats': self._experience_manager.get_stats(),
            'strategy_count': len(self._strategies),
            'evolution_count': len(self._evolution_history)
        }

    async def need_new_tool(self, task_history: Any) -> bool:
        """检查是否需要新工具（异步存根）"""
        return False

    async def analyze_and_generate_tool(self, task_history: Any) -> dict[str, Any] | None:
        """分析并生成新工具（异步存根）"""
        return None

    async def evolve_new_tool(self, new_tool_spec: dict[str, Any]) -> bool:
        """进化新工具（异步存根）"""
        return False


class EnhancedEvolutionEngine(EvolutionEngine):
    """
    增强进化引擎

    支持更复杂的进化场景
    """

    def __init__(self):
        super().__init__()
        self._adaptation_rules: list[Callable] = []
        self._performance_history: list[dict] = []

    def adapt_to_feedback(self, task_id: str, feedback: dict[str, Any]):
        """根据反馈自适应调整"""
        self._performance_history.append({
            'task_id': task_id,
            'feedback': feedback,
            'timestamp': time.time()
        })

        # 简化实现：记录反馈
        logger.info(f"【增强进化引擎】收到任务 {task_id} 的反馈")

    def predict_effectiveness(self, task_type: str, approach: str) -> float:
        """预测方法效果"""
        # 基于历史经验预测
        similar = self._experience_manager.find_similar_experiences(task_type=task_type)

        matching = [e for e in similar if e.approach == approach]
        if matching:
            return sum(e.effectiveness for e in matching) / len(matching)

        return 0.5  # 默认中等效果


# =============================================================================
# 便捷函数
# =============================================================================

def get_experience_for_task(task_type: str, limit: int = 3) -> list[Experience]:
    """获取任务经验"""
    engine = EvolutionEngine()
    return engine.get_experience_for_task(task_type, limit)


# =============================================================================
# 工厂函数
# =============================================================================

_evolution_engine: EvolutionEngine | None = None
_enhanced_evolution_engine: EnhancedEvolutionEngine | None = None
_factory_lock = threading.Lock()


def get_evolution_engine() -> EvolutionEngine:
    """
    获取进化引擎

    【线程安全】使用双检锁确保单例
    """
    global _evolution_engine
    if _evolution_engine is None:
        with _factory_lock:
            if _evolution_engine is None:
                _evolution_engine = EvolutionEngine()
    return _evolution_engine


def get_enhanced_evolution_engine() -> EnhancedEvolutionEngine:
    """
    获取增强进化引擎

    【线程安全】使用双检锁确保单例
    """
    global _enhanced_evolution_engine
    if _enhanced_evolution_engine is None:
        with _factory_lock:
            if _enhanced_evolution_engine is None:
                _enhanced_evolution_engine = EnhancedEvolutionEngine()
    return _enhanced_evolution_engine


# 全局实例
try:
    evolution = get_evolution_engine()
    enhanced_evolution = get_enhanced_evolution_engine()
except Exception as e:
    logger.error(f"创建evolution实例失败: {e}")
    evolution = None
    enhanced_evolution = None


__all__ = [
    'EvolutionEngine',
    'ExperienceManager',
    'EnhancedEvolutionEngine',
    'Experience',
    'EvolutionStrategy',
    'get_evolution_engine',
    'get_enhanced_evolution_engine',
    'get_experience_for_task',
    'evolution',
    'enhanced_evolution'
]
