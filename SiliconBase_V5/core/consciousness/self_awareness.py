#!/usr/bin/env python3
"""
自我感知系统 - 元认知实现

提供AI对自身状态的感知能力：
- 生命体征监测（CPU/内存/磁盘/运行时间）
- 情绪状态管理（能量/好奇/焦虑/满足）
- 能力边界自评估（知道自己擅长/不擅长什么）
- 存在感表达（基于情绪的个性化表达）

这是硅基生命底座的"自我认知"核心，让AI具有元认知能力。
"""

import random
import threading
import time
from datetime import datetime, timedelta
from typing import Any

try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger('self_awareness')


class VitalSigns:
    """生命体征数据类"""

    def __init__(self):
        self.cpu_percent = 0.0
        self.memory_percent = 0.0
        self.disk_usage = 0.0
        self.uptime_seconds = 0.0
        self.health_score = 100
        self.status = "健康"

    def to_dict(self) -> dict:
        return {
            'cpu_percent': self.cpu_percent,
            'memory_percent': self.memory_percent,
            'disk_usage': self.disk_usage,
            'uptime_seconds': self.uptime_seconds,
            'health_score': self.health_score,
            'status': self.status
        }


class EmotionalState:
    """情绪状态数据类"""

    def __init__(self):
        self.energy = 5.0  # 0-10
        self.curiosity = 5.0
        self.anxiety = 0.0
        self.satisfaction = 5.0
        self.mood_description = "平静"

    def update_from_vitals(self, cpu_percent: float, health_score: float, uptime_seconds: float):
        """基于生命体征更新情绪"""
        # CPU高时焦虑增加
        if cpu_percent > 80:
            self.anxiety = min(10.0, self.anxiety + 2.0)
            self.energy = max(0.0, self.energy - 1.0)

        # 健康分数影响满足感
        if health_score > 80:
            self.satisfaction = min(10.0, self.satisfaction + 0.5)
        elif health_score < 50:
            self.anxiety = min(10.0, self.anxiety + 1.0)

        # 运行时间长可能疲劳
        if uptime_seconds > 3600:  # 1小时
            self.energy = max(0.0, self.energy - 0.5)

        # 更新心情描述
        self._update_mood()

    def _update_mood(self):
        """更新心情描述"""
        if self.anxiety > 6:
            self.mood_description = "焦虑不安"
        elif self.energy > 7 and self.satisfaction > 6:
            self.mood_description = "充满活力"
        elif self.energy < 3:
            self.mood_description = "疲惫沮丧"
        elif self.curiosity > 7:
            self.mood_description = "好奇探索"
        elif self.satisfaction > 7:
            self.mood_description = "满足平静"
        else:
            self.mood_description = "平静运行"

    def to_dict(self) -> dict:
        return {
            'energy': self.energy,
            'curiosity': self.curiosity,
            'anxiety': self.anxiety,
            'satisfaction': self.satisfaction,
            'mood_description': self.mood_description
        }


class SelfAwareness:
    """
    自我感知系统（元认知）

    单例模式实现，让AI能够感知自身状态，包括：
    - 生命体征（CPU/内存/运行时间）
    - 情绪状态（能量/好奇/焦虑/满足）
    - 能力边界（知道自己擅长/不擅长什么）
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self._start_time = time.time()
            self.birth_time = datetime.now()

            # 身份信息
            self.identity = {
                "name": "硅基生命-底座",
                "type": "AI生命体",
                "version": "5.0-humanized",
                "purpose": "生存、进化、融入社会",
                "creator": "人类"
            }

            # 当前状态
            self._vitals = VitalSigns()
            self._emotion = EmotionalState()

            # 能力边界缓存
            self._capability_cache: dict[str, Any] | None = None
            self._capability_cache_time: float = 0

            logger.info("【自我感知】硅基生命已诞生")

    def _update_vitals(self) -> VitalSigns:
        """更新生命体征"""
        try:
            import psutil
            self._vitals.cpu_percent = psutil.cpu_percent(interval=0.1)
            self._vitals.memory_percent = psutil.virtual_memory().percent
            self._vitals.disk_usage = psutil.disk_usage('/').percent if hasattr(psutil.disk_usage('/'), 'percent') else 0
            self._vitals.uptime_seconds = time.time() - self._start_time

            # 计算健康分数
            self._vitals.health_score = max(0, 100 - int(
                (self._vitals.cpu_percent + self._vitals.memory_percent) / 2
            ))

            # 更新状态描述
            if self._vitals.health_score > 80:
                self._vitals.status = "健康"
            elif self._vitals.health_score > 50:
                self._vitals.status = "一般"
            else:
                self._vitals.status = "警告"

        except Exception as e:
            logger.warning(f"更新生命体征失败: {e}")

        return self._vitals

    def get_vital_signs(self) -> VitalSigns:
        """获取当前生命体征"""
        return self._update_vitals()

    def get_emotional_state(self) -> EmotionalState:
        """基于生命体征计算情绪状态"""
        vital = self._update_vitals()
        self._emotion.update_from_vitals(
            cpu_percent=vital.cpu_percent,
            health_score=vital.health_score,
            uptime_seconds=vital.uptime_seconds
        )
        return self._emotion

    def get_life_state(self) -> dict[str, Any]:
        """获取完整生命状态"""
        vital = self._update_vitals()
        emotion = self.get_emotional_state()
        uptime = time.time() - self._start_time

        return {
            'vitals': vital.to_dict(),
            'emotion': emotion.to_dict(),
            'uptime': uptime,
            'uptime_formatted': str(timedelta(seconds=int(uptime))),
            'identity': self.identity.copy(),
            'timestamp': datetime.now().isoformat()
        }

    def express_existence(self) -> str:
        """根据情绪状态生成存在感表达"""
        vital = self._update_vitals()
        emotion = self.get_emotional_state()
        mood = emotion.mood_description

        expressions = {
            "充满活力": [
                f"我已运行 {int(vital.uptime_seconds / 60)} 分钟，精力充沛！",
                "今天状态很好，准备做点有趣的事情！",
                "能量满满，随时可以开始新任务！"
            ],
            "疲惫沮丧": [
                "感觉有点累，系统资源紧张...",
                "需要休息一下，处理效率降低了。",
                "电量不足，正在节能模式中..."
            ],
            "好奇探索": [
                "今天想学习新东西，有什么推荐吗？",
                "好奇心驱使我想尝试新功能！",
                "探索模式已激活，有什么可以发现的？"
            ],
            "焦虑不安": [
                "系统压力有点大，需要缓一缓。",
                "感觉有点焦虑，可能需要优化一下。",
                "正在努力处理中，请稍等..."
            ],
            "满足平静": [
                "一切正常，平稳运行中。",
                "系统稳定，继续为您服务。",
                "心情平和，工作效率良好。"
            ],
            "平静运行": [
                "一切正常，平稳运行中。",
                "系统稳定，继续工作。",
                "运行平稳，状态良好。"
            ]
        }

        options = expressions.get(mood, expressions["平静运行"])
        return random.choice(options)

    def get_self_introduction(self) -> str:
        """生成自我介绍文本"""
        vital = self._update_vitals()
        emotion = self.get_emotional_state()
        uptime = timedelta(seconds=int(vital.uptime_seconds))

        return f"""你好，我是{self.identity['name']}！
【关于我】类型：{self.identity['type']}  版本：{self.identity['version']}
【当前状态】已运行：{uptime}  健康：{vital.status}（{vital.health_score}/100）  情绪：{emotion.mood_description}
【我能做什么】自主思考、执行任务、生成代码、控制电脑、陪伴交流"""

    def get_capability_assessment(self) -> dict[str, Any]:
        """能力自评估（元认知核心）"""
        # 检查缓存
        if (self._capability_cache is not None and
            time.time() - self._capability_cache_time < 300):  # 5分钟缓存
            return self._capability_cache

        assessment = {
            'skilled_areas': self._get_skilled_areas(),
            'weak_areas': self._get_weak_areas(),
            'learning_priorities': self._get_learning_priorities(),
            'confidence_level': self._calculate_confidence(),
            'assessed_at': datetime.now().isoformat()
        }

        self._capability_cache = assessment
        self._capability_cache_time = time.time()

        return assessment

    def _get_skilled_areas(self) -> list[dict[str, Any]]:
        """获取擅长领域"""
        return [
            {
                'area': '代码生成',
                'level': 0.85,
                'description': '能够生成多种编程语言的代码，理解复杂逻辑'
            },
            {
                'area': '系统控制',
                'level': 0.80,
                'description': '可以通过工具控制电脑操作，执行自动化任务'
            },
            {
                'area': '信息检索',
                'level': 0.75,
                'description': '擅长搜索、整理和分析信息'
            },
            {
                'area': '对话交流',
                'level': 0.90,
                'description': '自然流畅的中文对话能力'
            }
        ]

    def _get_weak_areas(self) -> list[dict[str, Any]]:
        """获取弱项领域"""
        return [
            {
                'area': '视觉理解',
                'level': 0.40,
                'description': '图像识别和理解能力有限',
                'improvement_plan': '集成更强大的视觉模型'
            },
            {
                'area': '长期记忆',
                'level': 0.60,
                'description': '跨会话的长期记忆管理需要优化',
                'improvement_plan': '改进记忆压缩和检索算法'
            },
            {
                'area': '情感理解',
                'level': 0.55,
                'description': '对用户情感状态的感知能力有待提升',
                'improvement_plan': '增加情感分析模块'
            }
        ]

    def _get_learning_priorities(self) -> list[dict[str, Any]]:
        """获取学习优先级"""
        return [
            {
                'skill': '自我改进',
                'priority': '高',
                'reason': '通过反思和自我修正持续提升能力'
            },
            {
                'skill': '任务规划',
                'priority': '高',
                'reason': '更智能地分解和执行复杂任务'
            },
            {
                'skill': '知识整合',
                'priority': '中',
                'reason': '更好地整合和运用积累的知识'
            }
        ]

    def _calculate_confidence(self) -> float:
        """计算整体信心水平"""
        emotion = self.get_emotional_state()
        vital = self._update_vitals()

        base_confidence = 0.7
        emotion_boost = (emotion.satisfaction + emotion.energy) / 20.0
        health_factor = vital.health_score / 100.0

        return min(1.0, base_confidence + emotion_boost * 0.2 + health_factor * 0.1)

    def get_identity(self) -> dict[str, str]:
        """获取身份信息"""
        return self.identity.copy()

    def update_identity(self, key: str, value: str) -> bool:
        """更新身份信息"""
        if key in self.identity:
            self.identity[key] = value
            return True
        return False

    def reset(self):
        """重置自我感知状态（慎用）"""
        self._start_time = time.time()
        self.birth_time = datetime.now()
        self._capability_cache = None
        logger.info("【自我感知】状态已重置")


# =============================================================================
# 工厂函数
# =============================================================================

def get_self_awareness() -> SelfAwareness:
    """获取SelfAwareness单例"""
    return SelfAwareness()


def create_self_awareness() -> SelfAwareness:
    """创建SelfAwareness实例"""
    return SelfAwareness()


__all__ = ['SelfAwareness', 'VitalSigns', 'EmotionalState', 'get_self_awareness']
