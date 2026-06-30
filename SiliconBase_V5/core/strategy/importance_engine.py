#!/usr/bin/env python3
"""
重要性评估引擎 - SiliconBase V5 智能信息投递核心
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

功能：
  ✓ 多维度重要性评分（语义/时间/结构/用户）
  ✓ 轻量级语义相似度计算
  ✓ 关键标记识别
  ✓ 与用户目标的相关性评估

作者: SiliconBase Team
版本: 1.0.0
"""

import logging
import math
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 设置本地模型缓存环境变量，确保离线模式优先使用本地缓存
_project_root = Path(__file__).parent.parent.parent  # 修正：指向项目根目录 (core/strategy/ -> core/ -> 项目根目录)
_cache_dir = str(_project_root / 'checkpoints' / 'hf_cache')
os.environ.setdefault('SENTENCE_TRANSFORMERS_HOME', _cache_dir)
os.environ.setdefault('HF_HOME', _cache_dir)
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')

# 【修复】智能查找模型路径 - 优先检查多个可能位置
def _find_model_path() -> str:
    """查找 sentence-transformers 模型的本地路径"""
    possible_paths = [
        # 项目根目录下的 checkpoints (推荐位置)
        _project_root / "checkpoints" / "hf_cache" / "models--sentence-transformers--all-MiniLM-L6-v2" /
        "snapshots" / "c9745ed1d9f207416be6d2e6f8de32d1f16199bf",
        # core 目录下的 checkpoints (旧位置，向后兼容)
        Path(__file__).parent.parent / "checkpoints" / "hf_cache" / "models--sentence-transformers--all-MiniLM-L6-v2" /
        "snapshots" / "c9745ed1d9f207416be6d2e6f8de32d1f16199bf",
        # 使用 HuggingFace 缓存目录格式
        Path(_cache_dir) / "models--sentence-transformers--all-MiniLM-L6-v2" /
        "snapshots" / "c9745ed1d9f207416be6d2e6f8de32d1f16199bf",
    ]

    for path in possible_paths:
        if path.exists():
            logger.info(f"[ImportanceEngine] 找到本地模型: {path}")
            return str(path)

    # 如果都不存在，返回默认路径（让后续代码报错时提示更明确）
    default_path = possible_paths[0]
    logger.warning(f"[ImportanceEngine] 本地模型不存在于任何已知位置，使用默认路径: {default_path}")
    return str(default_path)

_LOCAL_MODEL_PATH = _find_model_path()

# 可选依赖
try:
    from sentence_transformers import SentenceTransformer
    from sklearn.metrics.pairwise import cosine_similarity
    SENTENCE_TRANSFORMER_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMER_AVAILABLE = False
    SentenceTransformer = None
    cosine_similarity = None
    logger.warning("[ImportanceEngine] sentence-transformers未安装，将使用fallback模式")


class ImportanceLevel(Enum):
    """重要性级别枚举"""
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
    MINIMAL = "minimal"


@dataclass
class ImportanceBreakdown:
    """重要性评分细分"""
    semantic: float = 0.0
    temporal: float = 0.0
    structural: float = 0.0
    user: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            'semantic': round(self.semantic, 3),
            'temporal': round(self.temporal, 3),
            'structural': round(self.structural, 3),
            'user': round(self.user, 3)
        }


@dataclass
class ImportanceScore:
    """重要性评分结果"""
    total: float = 0.0
    level: ImportanceLevel = ImportanceLevel.NORMAL
    breakdown: ImportanceBreakdown = field(default_factory=ImportanceBreakdown)
    reasoning: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'total': round(self.total, 3),
            'level': self.level.value,
            'breakdown': self.breakdown.to_dict(),
            'reasoning': self.reasoning,
            'metadata': self.metadata
        }


class ImportanceConfig:
    """重要性评估配置"""

    DEFAULT_WEIGHTS = {
        'semantic': 0.35,
        'temporal': 0.20,
        'structural': 0.30,
        'user': 0.15
    }

    LEVEL_THRESHOLDS = {
        ImportanceLevel.CRITICAL: 0.85,
        ImportanceLevel.HIGH: 0.70,
        ImportanceLevel.NORMAL: 0.45,
        ImportanceLevel.LOW: 0.25,
        ImportanceLevel.MINIMAL: 0.0
    }

    CRITICAL_MARKERS = [
        (r'\b(?:关键|重要|核心|必须|务必|一定|绝对)\b', 0.30),
        (r'\b(?:错误|异常|失败|警告|报错|崩溃|超时)\b', 0.25),
        (r'\b(?:决策|选择|判断|分支|决定|抉择|选定)\b', 0.20),
        (r'\b(?:完成|成功|结束|结果|FINAL|最终结果|结论)\b', 0.25),
        (r'\b(?:问题|阻塞|卡住了|无法|不能|失败|需要用户)\b', 0.22),
    ]

    USER_EMPHASIS_MARKERS = [
        (r'[!！]{2,}', 0.25),
        (r'[？?]{2,}', 0.15),
        (r'"[^"]+"', 0.20),
        (r'【[^】]+】', 0.20),
        (r'\b(?:注意|请注意|重要的是|关键是)\b', 0.25),
    ]

    TEMPORAL_DECAY = {
        'half_life_steps': 10,
        'max_age_boost': 1.2,
        'old_age_penalty': 0.3
    }


class ImportanceEngine:
    """重要性评估引擎"""

    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self,
                 weights: dict[str, float] | None = None,
                 use_semantic: bool = True,
                 model_name: str = _LOCAL_MODEL_PATH):

        if ImportanceEngine._initialized:
            return

        self.weights = weights or ImportanceConfig.DEFAULT_WEIGHTS
        self.use_semantic = use_semantic and SENTENCE_TRANSFORMER_AVAILABLE
        self._encoder = None
        self._encoder_cache = {}
        self._cache_max_size = 1000

        if self.use_semantic:
            try:
                logger.info(f"[ImportanceEngine] 加载语义模型: {model_name}")
                self._encoder = SentenceTransformer(model_name, local_files_only=True)
                logger.info("[ImportanceEngine] 语义模型加载成功")
            except Exception as e:
                logger.error(f"[ImportanceEngine] 语义模型加载失败: {e}")
                self.use_semantic = False

        self._stats = {
            'total_calculations': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'semantic_fallbacks': 0
        }

        ImportanceEngine._initialized = True
        logger.info("[ImportanceEngine] 初始化完成")

    def calculate(self,
                  message: dict[str, Any],
                  context: dict[str, Any] = None,
                  step_number: int = 0) -> ImportanceScore:
        """计算消息的重要性评分"""
        self._stats['total_calculations'] += 1
        context = context or {}

        content = message.get('content', '')
        if not content:
            return ImportanceScore(total=0.0, level=ImportanceLevel.MINIMAL, reasoning="内容为空")

        try:
            semantic_score = self._calculate_semantic(content, context)
            temporal_score = self._calculate_temporal(message, context, step_number)
            structural_score = self._calculate_structural(content)
            user_score = self._calculate_user_emphasis(content)

            total = (
                semantic_score * self.weights['semantic'] +
                temporal_score * self.weights['temporal'] +
                structural_score * self.weights['structural'] +
                user_score * self.weights['user']
            )

            level = self._score_to_level(total)
            reasoning = self._generate_reasoning(semantic_score, temporal_score, structural_score, user_score)

            return ImportanceScore(
                total=round(total, 3),
                level=level,
                breakdown=ImportanceBreakdown(
                    semantic=round(semantic_score, 3),
                    temporal=round(temporal_score, 3),
                    structural=round(structural_score, 3),
                    user=round(user_score, 3)
                ),
                reasoning=reasoning,
                metadata={'content_length': len(content), 'has_goal': 'goal' in context}
            )
        except Exception as e:
            logger.error(f"[ImportanceEngine] 评分失败: {e}")
            return ImportanceScore(total=0.5, level=ImportanceLevel.NORMAL, reasoning=f"计算失败: {e}")

    def _calculate_semantic(self, content: str, context: dict[str, Any]) -> float:
        """计算语义重要性"""
        if not self.use_semantic:
            return self._fallback_semantic(content, context)

        goal = context.get('goal', '')
        if not goal:
            return 0.5

        try:
            goal_emb = self._encoder.encode(goal)
            content_emb = self._encoder.encode(content)
            similarity = cosine_similarity([content_emb], [goal_emb])[0][0]
            return float(similarity)
        except Exception as e:
            logger.warning(f"语义计算失败: {e}")
            return self._fallback_semantic(content, context)

    def _fallback_semantic(self, content: str, context: dict[str, Any]) -> float:
        """语义计算fallback"""
        self._stats['semantic_fallbacks'] += 1
        goal = context.get('goal', '')
        if not goal:
            return 0.5

        goal_words = set(self._extract_keywords(goal))
        content_words = set(self._extract_keywords(content))

        if not goal_words:
            return 0.5

        intersection = goal_words & content_words
        union = goal_words | content_words
        return len(intersection) / len(union) if union else 0.5

    def _calculate_temporal(self, message: dict, context: dict, step_number: int) -> float:
        """计算时间重要性"""
        current_step = context.get('current_step', step_number)
        msg_step = message.get('step_number', step_number)
        age = max(0, current_step - msg_step)
        half_life = ImportanceConfig.TEMPORAL_DECAY['half_life_steps']
        decay = math.exp(-age / half_life)
        return min(0.3 + 0.7 * decay, 1.0)

    def _calculate_structural(self, content: str) -> float:
        """计算结构重要性"""
        score = 0.0
        for pattern, weight in ImportanceConfig.CRITICAL_MARKERS:
            if re.search(pattern, content, re.IGNORECASE):
                score += weight
        return min(score, 1.0)

    def _calculate_user_emphasis(self, content: str) -> float:
        """计算用户强调程度"""
        score = 0.0
        for pattern, weight in ImportanceConfig.USER_EMPHASIS_MARKERS:
            matches = re.findall(pattern, content, re.IGNORECASE)
            score += len(matches) * weight
        return min(score, 1.0)

    def _score_to_level(self, score: float) -> ImportanceLevel:
        """分数转级别"""
        for level, threshold in sorted(ImportanceConfig.LEVEL_THRESHOLDS.items(), key=lambda x: x[1], reverse=True):
            if score >= threshold:
                return level
        return ImportanceLevel.MINIMAL

    def _generate_reasoning(self, semantic: float, temporal: float, structural: float, user: float) -> str:
        """生成评分理由"""
        reasons = []
        if semantic > 0.7:
            reasons.append("与目标高度相关")
        elif semantic < 0.3:
            reasons.append("与目标相关性低")
        if temporal > 0.8:
            reasons.append("最新信息")
        if structural > 0.5:
            reasons.append("包含关键标记")
        if user > 0.3:
            reasons.append("用户强调")
        return "; ".join(reasons) if reasons else "标准信息"

    def _extract_keywords(self, text: str) -> list[str]:
        """提取关键词"""
        words = re.findall(r'[\u4e00-\u9fa5]{2,}', text)
        stopwords = {'一个', '这个', '那个', '进行', '完成', '开始', '需要', '可以'}
        return [w for w in words if w not in stopwords and len(w) >= 2]

    def get_stats(self) -> dict[str, Any]:
        return self._stats.copy()


# 全局实例
_importance_engine: ImportanceEngine | None = None

def get_importance_engine() -> ImportanceEngine:
    """获取全局引擎实例"""
    global _importance_engine
    if _importance_engine is None:
        _importance_engine = ImportanceEngine()
    return _importance_engine


def calculate_importance(message: dict[str, Any], context: dict[str, Any] = None, step_number: int = 0) -> ImportanceScore:
    """便捷函数：计算重要性"""
    return get_importance_engine().calculate(message, context, step_number)
