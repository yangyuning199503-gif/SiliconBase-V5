#!/usr/bin/env python3
"""
PerceptionManager - 感知管理器
【Phase 2 Week 3 - 任务2】AgentLoop集成感知能力
【Phase 2 增强】语义触发集成 - 三维度设计

职责:
1. 管理视觉感知、环境感知等多模态感知能力
2. 根据用户输入和上下文决定是否触发感知
3. 格式化感知数据用于Prompt注入
4. 发送感知触发事件到前端

设计原则:
- 感知失败不阻塞主流程
- 模块化设计，易于扩展新的感知类型
- 支持运行时开关控制

三维度集成策略:
- AI维度: 语义理解 > 关键词匹配（更智能）
- 用户维度: 零配置，自动选择最优策略
- 项目维度: 100%向后兼容，云端部署友好
"""

import asyncio
import contextlib
import hashlib
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from core.config import config
from core.diagnostic import safe_create_task
from core.logger import logger
from core.vision.visual_analysis_cache import get_visual_analysis_cache
from tools.visual_understand import VisualUnderstand

# 降级日志冷却控制（60 秒内最多打印一次）
_degraded_log_last_time = 0.0
_DEGRADED_LOG_COOLDOWN = 60.0


def _log_degraded_once():
    """降级状态下限制日志频率，避免刷屏。"""
    global _degraded_log_last_time
    now = time.time()
    if now - _degraded_log_last_time >= _DEGRADED_LOG_COOLDOWN:
        _degraded_log_last_time = now
        logger.info("[PerceptionManager] 视觉模型降级，跳过视觉理解调用")

# ═══════════════════════════════════════════════════════════════
# Phase4+ 白皮书架构：感知策略外置（Feature Flag 保护）
# ═══════════════════════════════════════════════════════════════
try:
    from core.vision.perception_strategy import (
        PerceptionData as V2PerceptionData,
    )
    from core.vision.perception_strategy import (
        PerceptionRequest as V2PerceptionRequest,
    )
    from core.vision.perception_strategy import (
        PerceptionStrategy as V2PerceptionStrategy,
    )
    _V2_PERCEPTION_AVAILABLE = True
except ImportError:
    _V2_PERCEPTION_AVAILABLE = False

# 【Phase 2 增强】尝试导入语义触发模块
try:
    from core.perception.trigger_with_fallback import should_trigger_perception as _should_trigger_semantic
    _SEMANTIC_TRIGGER_AVAILABLE = True
except ImportError:
    _SEMANTIC_TRIGGER_AVAILABLE = False
    logger.debug("[PerceptionManager] 语义触发模块未安装，使用关键词匹配")


class PerceptionType(Enum):
    """感知类型枚举"""
    VISION = "vision"           # 视觉感知
    ENVIRONMENT = "environment" # 环境感知
    SCREEN = "screen"          # 屏幕状态
    USER_CONTEXT = "user_context"  # 用户上下文


class TriggerReason(Enum):
    """感知触发原因"""
    USER_REQUEST = "user_request"      # 用户明确要求
    SCREEN_CHANGED = "screen_changed"  # 屏幕变化
    TASK_NEED = "task_need"           # 任务需要
    PERIODIC = "periodic"             # 周期性触发
    CONTEXTUAL = "contextual"         # 上下文推断
    SEMANTIC = "semantic"             # 语义推断触发


class SemanticIntent(Enum):
    """语义意图类型"""
    VISUAL_QUERY = "visual_query"         # 视觉查询（"看到了什么"）
    LOCATE_REQUEST = "locate_request"     # 定位请求（"在哪里"）
    STATUS_CHECK = "status_check"         # 状态检查（"进度如何"）
    INTERACTION_HELP = "interaction_help" # 交互帮助（"怎么点击"）
    UNKNOWN = "unknown"                   # 未知意图


class TaskPhase(Enum):
    """任务阶段"""
    INITIAL = "initial"       # 初始阶段（高触发敏感度）
    EXECUTING = "executing"   # 执行阶段（中敏感度）
    VERIFYING = "verifying"   # 验证阶段（低敏感度，主要error时触发）
    COMPLETED = "completed"   # 完成阶段


@dataclass
class PerceptionData:
    """感知数据结构"""
    perception_type: PerceptionType
    content: str
    timestamp: float = field(default_factory=time.time)
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    trigger_reason: TriggerReason = TriggerReason.CONTEXTUAL

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "type": self.perception_type.value,
            "content": self.content,
            "timestamp": self.timestamp,
            "confidence": self.confidence,
            "metadata": self.metadata,
            "trigger_reason": self.trigger_reason.value
        }


class PerceptionManager:
    """
    感知管理器 - 统一管理各类感知能力

    使用方式:
        perception_manager = PerceptionManager()
        if perception_manager.should_trigger_perception(user_input, context):
            perception = perception_manager.get_perception()
            prompt += perception_manager.format_for_prompt(perception)
    """

    # 触发关键词 - 用户输入包含这些词时触发感知
    # 【P1-修复】移除"打开/播放/发送"等启动类词汇，避免任务开始就无条件截图
    # 视觉触发应限于：明确需要看屏幕、找元素、查状态的场景
    TRIGGER_KEYWORDS = [
        # 基础视觉关键词
        "屏幕", "界面", "窗口", "截图", "看到", "显示",
        "在哪里", "在哪", "位置", "图标", "按钮",
        "当前页面", "这个页面", "网页", "应用",
        "看不清楚", "看不到", "看不见", "识别",
        "找找", "查找", "搜索", "定位",
        "怎么了", "什么情况", "什么状态", "进度",
        # 【Phase 2 Week 3 验证清单】新增关键词
        "查看状态", "我在做什么", "我在干嘛", "当前状态",
        "see", "check", "status", "where", "current", "now",
        "what is", "what are you doing", "what do you see",
        "screen", "desktop", "window", "app", "application",
        # 截图变体
        "截个图", "截一下图", "截屏",
    ]

    # 视觉相关任务关键词
    VISION_KEYWORDS = [
        "打开", "点击", "输入", "填写", "选择",
        "截图", "识别", "OCR", "查看",
    ]

    # ========== 语义意图识别规则 ==========
    # 语义意图模式：每种意图对应的关键词和正则模式
    SEMANTIC_PATTERNS = {
        SemanticIntent.VISUAL_QUERY: {
            "keywords": [
                "看到", "看见", "显示", "展示", "有什么", "是什么", "什么样",
                "看到了什么", "显示了什么", "看到什么", "看见什么",
                "see", "what do you see", "what is on", "show me", "what can you see",
            ],
            "threshold": 0.6,
        },
        SemanticIntent.LOCATE_REQUEST: {
            "keywords": [
                "在哪里", "在哪", "位置", "找不到", "去哪儿", "去哪里",
                "在哪儿", "在什么位置", "在哪里找", "在哪找",
                "where is", "where are", "find", "locate", "position",
            ],
            "threshold": 0.6,
        },
        SemanticIntent.STATUS_CHECK: {
            "keywords": [
                "进度", "状态", "如何", "怎么样", "完成了吗", "成功了吗",
                "进行到哪", "到哪一步", "当前状态", "任务状态",
                "status", "progress", "how is it going", "done yet", "finished",
            ],
            "threshold": 0.55,
        },
        SemanticIntent.INTERACTION_HELP: {
            "keywords": [
                "怎么", "如何", "怎样", "怎么做", "怎么办", "怎么操作",
                "怎么点击", "怎么输入", "怎么选择", "怎么填写",
                "how to", "how do i", "how can i", "help me", "guide me",
            ],
            "threshold": 0.55,
        },
    }

    # 任务阶段敏感度配置（触发阈值，越低越容易触发）
    PHASE_SENSITIVITY = {
        TaskPhase.INITIAL: {
            "threshold": 0.45,      # 高敏感度
            "min_interval": 2.0,    # 最短触发间隔(秒)
            "enable_semantic": True,
        },
        TaskPhase.EXECUTING: {
            "threshold": 0.60,      # 中敏感度
            "min_interval": 3.0,
            "enable_semantic": True,
        },
        TaskPhase.VERIFYING: {
            "threshold": 0.75,      # 低敏感度
            "min_interval": 4.0,
            "enable_semantic": True,
        },
        TaskPhase.COMPLETED: {
            "threshold": 0.80,      # 极低敏感度
            "min_interval": 5.0,
            "enable_semantic": False,
        },
    }

    def __init__(self, user_id: str = "default", session_id: str = ""):
        """
        初始化感知管理器

        Args:
            user_id: 用户ID
            session_id: 会话ID
        """
        self.user_id = user_id
        self.session_id = session_id

        # 【配置设计】全局部署级配置，在 __init__ 中静态读取
        # 理由：
        # 1. 这些是全局开关，不是用户级个性化设置
        # 2. 请求生命周期内配置不变，避免行为突变
        # 3. 性能最优（避免每次访问的函数调用和锁开销）
        # 4. 与项目其他模块（auto_loop.py等）保持一致
        self.enabled = config.get("perception.enabled", True)
        self.vision_enabled = config.get("perception.vision_enabled", True)
        self.learning_enabled = config.get("perception.learning_enabled", True)
        self.cache_ttl = config.get("perception.cache_ttl", 5.0)
        self.min_trigger_interval = config.get("perception.min_interval", 3.0)
        self._visual_cache_enabled = config.get("deduplication.visual_analysis.enabled", True)
        self._visual_cache_ttl = config.get("deduplication.visual_analysis.cache_ttl", 5)

        # 状态变量
        self._last_perception_time = 0
        self._cached_perception: PerceptionData | None = None
        self._last_trigger_time = 0

        # 统计信息
        self.trigger_count = 0
        self.error_count = 0

        # 视觉工具延迟初始化
        self._vision_tool = None
        self._screen_detector = None

        # 视觉分析缓存（Week 3 数据去重组件）
        self.visual_cache = get_visual_analysis_cache()

        # 任务阶段和语义相关状态
        self._current_task_phase = TaskPhase.INITIAL
        self._task_error_count = 0
        self._semantic_trigger_stats = dict.fromkeys(SemanticIntent, 0)

        # 去重统计
        self._cache_hits = 0
        self._cache_misses = 0
        self._duplicate_calls_avoided = 0

        # 【性能优化】复用线程池，避免重复创建
        self._fusion_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="fusion_")

        # 后台刷新任务状态
        self._refresh_task: asyncio.Task | None = None
        self._refresh_lock = asyncio.Lock()

        logger.info(f"[PerceptionManager] 初始化完成: user={user_id}, enabled={self.enabled}, cache_enabled={self._visual_cache_enabled}")

    def __del__(self):
        """清理资源，关闭线程池"""
        if hasattr(self, '_fusion_executor') and self._fusion_executor:
            self._fusion_executor.shutdown(wait=False)

    def _get_vision_tool(self):
        """延迟初始化视觉工具"""
        if VisualUnderstand.is_degraded():
            _log_degraded_once()
            return None
        if self._vision_tool is None:
            try:
                self._vision_tool = VisualUnderstand()
                logger.debug("[PerceptionManager] VisualUnderstand已初始化")
            except Exception as e:
                logger.warning(f"[PerceptionManager] VisualUnderstand初始化失败: {e}")
                return None
        return self._vision_tool

    def _get_screen_detector(self):
        """延迟初始化屏幕检测器"""
        if self._screen_detector is None:
            try:
                from core.vision.screen_change_detector import ScreenChangeDetector
                threshold = config.get("vision.change_threshold", 5)
                self._screen_detector = ScreenChangeDetector(threshold=threshold)
                logger.debug("[PerceptionManager] ScreenChangeDetector已初始化")
            except Exception as e:
                logger.warning(f"[PerceptionManager] ScreenChangeDetector初始化失败: {e}")
                return None
        return self._screen_detector

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """
        计算两段文本的相似度（向后兼容的包装方法）

        优先使用高级相似度算法（jieba+TF-IDF），
        如果失败则降级到改进的Jaccard算法。

        Args:
            text1: 输入文本1
            text2: 输入文本2

        Returns:
            float: 相似度分数 [0.0, 1.0]
        """
        return self._calculate_similarity_advanced(text1, text2)

    def _calculate_similarity_advanced(self, text1: str, text2: str) -> float:
        """
        高级相似度计算 - 使用jieba分词 + 加权Jaccard相似度

        针对中文优化：
        - 使用jieba进行中文分词，识别词语而非单字
        - 使用加权Jaccard：长词（如"浏览器"）权重更高
        - 对同义词对（如"打开"/"开启"）进行特殊处理

        降级策略：
        - 如果jieba不可用，使用改进的Jaccard（基于正则提取词组）
        - 如果所有方法失败，返回基础字符Jaccard

        Args:
            text1: 输入文本1
            text2: 输入文本2

        Returns:
            float: 相似度分数 [0.0, 1.0]

        Example:
            >>> pm = PerceptionManager()
            >>> pm._calculate_similarity_advanced("打开浏览器", "开启浏览器")
            0.6...  # 相似度较高，因为核心词汇"浏览器"相同
        """
        if not text1 or not text2:
            return 0.0

        # 标准化处理
        text1 = text1.lower().strip()
        text2 = text2.lower().strip()

        if text1 == text2:
            return 1.0

        # 尝试使用jieba + 加权Jaccard
        try:
            return self._calculate_weighted_jaccard(text1, text2)
        except Exception:
            # 降级到改进的Jaccard
            pass

        # 尝试使用改进的Jaccard（基于词语）
        try:
            return self._calculate_improved_jaccard(text1, text2)
        except Exception:
            # 最后的fallback：基础字符Jaccard
            return self._calculate_basic_jaccard(text1, text2)

    def _calculate_weighted_jaccard(self, text1: str, text2: str) -> float:
        """
        使用jieba分词 + 加权Jaccard相似度

        改进点：
        - 使用jieba进行中文分词，得到"打开"/"浏览器"而非单字
        - 加权策略：长词（如"浏览器"3字）权重 = 3，单字（如"打"）权重 = 1
        - 对同义词对进行特殊处理，提升相似度

        Args:
            text1: 输入文本1
            text2: 输入文本2

        Returns:
            float: 加权Jaccard相似度 [0.0, 1.0]
        """
        import re

        import jieba

        # 同义词映射表（简化版）
        SYNONYMS = {
            '打开': ['开启', '启动', '运行'],
            '开启': ['打开', '启动', '运行'],
            '启动': ['打开', '开启', '运行'],
            '运行': ['打开', '开启', '启动'],
            '关闭': ['退出', '结束', '停止'],
            '退出': ['关闭', '结束', '停止'],
            '查找': ['搜索', '寻找', '查找'],
            '搜索': ['查找', '寻找'],
            '点击': ['按下', '单击'],
            '哪里': ['哪儿', '何处'],
            '哪儿': ['哪里', '何处'],
            '看到': ['看见', '看到'],
            '看见': ['看到', '看见'],
            '怎么': ['如何', '怎样'],
            '如何': ['怎么', '怎样'],
            '截图': ['截屏', '抓屏', '截个图', '截一下图'],
            '截屏': ['截图', '抓屏'],
            '截个图': ['截图', '截个屏'],
            '看看': ['看一下', '看一看'],
        }

        # 部分匹配规则：如果词A包含词B，给予一定相似度
        PARTIAL_MATCH_RULES = {
            '截图': ['截个图', '截下图'],
            '截个图': ['截图'],
        }

        def tokenize(text):
            """使用jieba分词"""
            # 去除标点符号
            text = re.sub(r'[^\u4e00-\u9fff\w\s]', ' ', text)
            tokens = list(jieba.cut(text))
            # 过滤停用词和空字符串
            stopwords = {'的', '了', '在', '是', '我', '有', '和', '就', '不', '人',
                        '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去',
                        '你', '会', '着', '没有', '看', '好', '自己', '这', '那', '个'}
            return [t.strip() for t in tokens if t.strip() and t.strip() not in stopwords]

        def get_weight(word):
            """计算词的权重：词越长权重越高"""
            # 中文按字符数，英文按单词（本身就是单词）
            length = len(word)
            if length >= 3:
                return 3.0  # 长词（如"浏览器"）权重高
            elif length == 2:
                return 2.0  # 双字词（如"打开"）权重中等
            else:
                return 1.0  # 单字或短英文词权重低

        tokens1 = tokenize(text1)
        tokens2 = tokenize(text2)

        if not tokens1 or not tokens2:
            return 0.0

        set1 = set(tokens1)
        set2 = set(tokens2)

        # 计算加权交集
        intersection_weight = 0.0
        matched_words = set()

        for w1 in set1:
            if w1 in set2:
                # 直接匹配
                weight = get_weight(w1)
                intersection_weight += weight
                matched_words.add(w1)
            elif w1 in SYNONYMS:
                # 检查同义词
                for syn in SYNONYMS[w1]:
                    if syn in set2 and syn not in matched_words:
                        weight = get_weight(w1) * 0.8  # 同义词权重稍低
                        intersection_weight += weight
                        matched_words.add(w1)
                        break
            elif w1 in PARTIAL_MATCH_RULES:
                # 检查部分匹配规则
                for pattern in PARTIAL_MATCH_RULES[w1]:
                    if pattern in set2 and pattern not in matched_words:
                        weight = get_weight(w1) * 0.6  # 部分匹配权重更低
                        intersection_weight += weight
                        matched_words.add(w1)
                        break

        # 计算加权并集
        union_weight = 0.0
        all_words = set1 | set2
        for w in all_words:
            union_weight += get_weight(w)

        if union_weight == 0:
            return 0.0

        # 加权Jaccard
        jaccard = intersection_weight / union_weight

        # 长度相似度加成（长度相近的文本更相似）
        len_ratio = min(len(text1), len(text2)) / max(len(text1), len(text2)) if max(len(text1), len(text2)) > 0 else 0

        # 综合得分：加权Jaccard占80%，长度相似度占20%
        final_score = jaccard * 0.8 + len_ratio * 0.2

        return min(1.0, final_score)

    def _calculate_improved_jaccard(self, text1: str, text2: str) -> float:
        """
        改进的Jaccard相似度 - 基于正则提取词语

        不依赖jieba，使用规则提取：
        - 连续中文字符（2-4字词组）
        - 英文单词
        - 数字

        Args:
            text1: 输入文本1
            text2: 输入文本2

        Returns:
            float: Jaccard相似度 [0.0, 1.0]
        """
        import re

        def extract_words(text):
            """使用正则提取词语"""
            words = []

            # 提取英文单词
            words.extend(re.findall(r'[a-z]+', text.lower()))

            # 提取数字
            words.extend(re.findall(r'\d+', text))

            # 提取中文字符（尝试提取2-4字的词组）
            chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)

            # 策略1：尝试提取常见的双字词
            for i in range(len(chinese_chars) - 1):
                bigram = ''.join(chinese_chars[i:i+2])
                words.append(bigram)

            # 策略2：也保留单字作为fallback
            if len(chinese_chars) <= 4:
                words.extend(chinese_chars)

            return set(words)

        set1 = extract_words(text1)
        set2 = extract_words(text2)

        if not set1 or not set2:
            return 0.0

        intersection = set1 & set2
        union = set1 | set2

        # 加权Jaccard：交集越大，相似度越高
        jaccard = len(intersection) / len(union) if union else 0.0

        # 如果有很多共同的双字词，提升相似度
        bigram_bonus = 0.0
        common_bigrams = [w for w in intersection if len(w) >= 2]
        if common_bigrams:
            bigram_bonus = len(common_bigrams) * 0.05  # 每个共同词组加5%

        return min(1.0, jaccard + bigram_bonus)

    def _calculate_basic_jaccard(self, text1: str, text2: str) -> float:
        """
        基础Jaccard相似度 - 字符级别（最后的fallback）

        Args:
            text1: 输入文本1
            text2: 输入文本2

        Returns:
            float: Jaccard相似度 [0.0, 1.0]
        """
        import re

        def normalize(text):
            text = text.lower()
            # 保留中文字符和英文单词
            text = re.sub(r'[^\u4e00-\u9fff\w\s]', ' ', text)
            # 分词（中文按字，英文按词）
            words = []
            for token in text.split():
                if re.match(r'[\u4e00-\u9fff]', token):
                    words.extend(list(token))  # 中文分字
                else:
                    words.append(token)  # 英文保留词
            return set(words)

        set1 = normalize(text1)
        set2 = normalize(text2)

        if not set1 or not set2:
            return 0.0

        intersection = set1 & set2
        union = set1 | set2

        return len(intersection) / len(union) if union else 0.0

    def detect_semantic_intent(self, user_input: str) -> tuple[SemanticIntent, float]:
        """
        检测用户输入的语义意图

        Args:
            user_input: 用户输入文本

        Returns:
            Tuple[SemanticIntent, float]: (检测到的意图, 置信度分数)
        """
        if not user_input:
            return SemanticIntent.UNKNOWN, 0.0

        user_input_lower = user_input.lower()
        best_intent = SemanticIntent.UNKNOWN
        best_score = 0.0

        # 对每个意图类型计算最大相似度
        for intent, cfg in self.SEMANTIC_PATTERNS.items():
            keywords = cfg["keywords"]
            threshold = cfg["threshold"]

            # 计算与所有关键词的最大相似度
            max_similarity = 0.0
            matched_keyword = ""

            for keyword in keywords:
                # 首先检查是否包含关键词（精确匹配）
                if keyword in user_input_lower:
                    similarity = 1.0
                else:
                    # 否则计算相似度
                    similarity = self._calculate_similarity(user_input_lower, keyword)

                if similarity > max_similarity:
                    max_similarity = similarity
                    matched_keyword = keyword

            # 如果超过阈值，记录该意图
            if max_similarity >= threshold and max_similarity > best_score:
                best_score = max_similarity
                best_intent = intent
                logger.debug(f"[PerceptionManager] 语义意图匹配: {intent.value}, "
                           f"关键词='{matched_keyword}', 相似度={max_similarity:.2f}")

        return best_intent, best_score

    def get_task_phase(self, context: dict[str, Any]) -> TaskPhase:
        """
        根据上下文推断当前任务阶段

        Args:
            context: 上下文信息

        Returns:
            TaskPhase: 当前任务阶段
        """
        # 从上下文中获取任务信息
        task_info = context.get("task_info", {})
        execution_history = context.get("execution_history", [])
        step_count = len(execution_history)

        # 检查是否有错误
        has_error = context.get("last_error") is not None

        # 检查任务状态
        task_status = task_info.get("status", "unknown")

        # 阶段推断逻辑
        if task_status == "completed":
            return TaskPhase.COMPLETED
        elif task_status == "verifying" or (step_count > 5 and not has_error):
            return TaskPhase.VERIFYING
        elif step_count == 0 or task_status == "initial":
            return TaskPhase.INITIAL
        else:
            return TaskPhase.EXECUTING

    def set_task_phase(self, phase: TaskPhase):
        """
        显式设置当前任务阶段

        Args:
            phase: 任务阶段
        """
        if not isinstance(phase, TaskPhase):
            raise ValueError(f"Invalid task phase: {phase}")
        self._current_task_phase = phase
        logger.debug(f"[PerceptionManager] 任务阶段更新为: {phase.value}")

    def should_trigger_perception_semantic(
        self,
        user_input: str,
        context: dict[str, Any],
        force_phase: TaskPhase | None = None
    ) -> tuple[bool, dict[str, Any]]:
        """
        基于语义意图和任务阶段的智能感知触发判断

        这是增强版的触发判断，添加语义理解和任务阶段感知。

        Args:
            user_input: 用户输入文本
            context: 上下文信息
            force_phase: 强制指定任务阶段（用于测试或手动控制）

        Returns:
            Tuple[bool, Dict]: (是否触发, 触发信息字典)
        """
        trigger_info = {
            "method": "none",
            "intent": SemanticIntent.UNKNOWN.value,
            "intent_score": 0.0,
            "phase": TaskPhase.INITIAL.value,
            "phase_threshold": 0.5,
            "reason": ""
        }

        # 全局开关检查
        if not self.enabled:
            trigger_info["reason"] = "感知功能已禁用"
            return False, trigger_info

        # 空输入检查
        if not user_input:
            trigger_info["reason"] = "空输入"
            return False, trigger_info

        # 获取任务阶段
        task_phase = force_phase if force_phase else self.get_task_phase(context)
        phase_config = self.PHASE_SENSITIVITY.get(task_phase, self.PHASE_SENSITIVITY[TaskPhase.EXECUTING])

        trigger_info["phase"] = task_phase.value
        trigger_info["phase_threshold"] = phase_config["threshold"]

        # 检查阶段是否启用语义感知
        if not phase_config.get("enable_semantic", True):
            trigger_info["reason"] = f"当前阶段{task_phase.value}语义感知已禁用"
            return False, trigger_info

        # 触发间隔检查（使用阶段特定的间隔）
        current_time = time.time()
        time_since_last = current_time - self._last_trigger_time
        min_interval = phase_config.get("min_interval", self.min_trigger_interval)

        if time_since_last < min_interval:
            trigger_info["reason"] = f"触发间隔太短({time_since_last:.1f}s < {min_interval}s)"
            return False, trigger_info

        # ===== 快速路径：关键词匹配 =====
        user_input_lower = user_input.lower()
        for keyword in self.TRIGGER_KEYWORDS:
            if keyword in user_input_lower:
                logger.info(f"[PerceptionManager] 关键词快速路径触发: '{keyword}'")
                trigger_info["method"] = "keyword"
                trigger_info["matched_keyword"] = keyword
                trigger_info["reason"] = "关键词匹配"
                return True, trigger_info

        # ===== 语义意图识别 =====
        intent, intent_score = self.detect_semantic_intent(user_input)
        trigger_info["intent"] = intent.value
        trigger_info["intent_score"] = intent_score

        # 根据任务阶段判断是否触发
        phase_threshold = phase_config["threshold"]

        if intent != SemanticIntent.UNKNOWN and intent_score >= phase_threshold:
            self._semantic_trigger_stats[intent] += 1
            logger.info(f"[PerceptionManager] 语义意图触发: {intent.value}, "
                       f"分数={intent_score:.2f}, 阶段={task_phase.value}")
            trigger_info["method"] = "semantic"
            trigger_info["reason"] = f"语义意图匹配: {intent.value}"
            return True, trigger_info

        # 特殊处理：验证阶段仅在错误时触发
        if task_phase == TaskPhase.VERIFYING:
            last_error = context.get("last_error")
            if last_error:
                logger.info("[PerceptionManager] 验证阶段错误触发")
                trigger_info["method"] = "error_in_verifying"
                trigger_info["reason"] = "验证阶段检测到错误"
                return True, trigger_info

        # 上下文推断（保留原有逻辑）
        has_vision_keyword = any(kw in user_input_lower for kw in self.VISION_KEYWORDS)
        execution_history = context.get("execution_history", [])
        if execution_history and has_vision_keyword:
            last_tool = execution_history[-1].get("tool", "") if execution_history else ""
            ui_tools = ["mouse_click", "keyboard_input", "click_text", "pixel_click",
                       "launch_app", "window_action", "smart_form_fill"]
            if last_tool in ui_tools:
                logger.info(f"[PerceptionManager] 上下文推断触发: 上一步工具={last_tool}")
                trigger_info["method"] = "contextual"
                trigger_info["reason"] = f"上下文推断: UI工具={last_tool}"
                return True, trigger_info

        trigger_info["reason"] = "未满足任何触发条件"
        return False, trigger_info

    # 【修复】简单问答关键词统一引用 core.constants，避免多处定义不一致
    def _is_simple_chat(self, user_input: str) -> bool:
        """判断是否为简单闲聊/身份问答，此类问题不需要视觉感知"""
        if not user_input:
            return False
        from core.constants import is_simple_chat
        # 视觉感知用更宽松的阈值（<50字符），因为这里只需要决定是否跳过视觉
        text = user_input.strip()
        if len(text) < 50 and is_simple_chat(text):
            return True
        # 纯英文短问候兜底
        text_lower = text.lower()
        return bool(len(text_lower) < 20 and text_lower in ("who are you", "what can you do", "help"))

    def _is_launch_app_intent(self, user_input: str, context: dict[str, Any]) -> bool:
        """判断是否为打开/启动应用类意图，此类意图默认不需要屏幕感知"""
        if not user_input:
            return False
        # 1. 上下文意图短路：如果意图/工具明确是 launch_app，直接跳过
        intent = context.get("intent") if isinstance(context, dict) else None
        if isinstance(intent, dict) and intent.get("tool") == "launch_app":
            return True
        # 2. 关键词匹配：打开/启动/运行 + 应用名
        text = user_input.strip().lower()
        # 支持中文和英文常见表达
        launch_patterns = [
            r"^(打开|启动|运行|开启|开一下|帮我打开|帮我启动)\s*",
            r"^(open|launch|start|run)\s+",
        ]
        return any(re.search(p, text) for p in launch_patterns)

    def should_trigger_perception(self, user_input: str, context: dict[str, Any]) -> bool:
        """
        判断是否应触发感知（三维度集成版）

        设计思路:
        1. AI维度: 优先使用语义理解（更准确）
        2. 用户维度: 零配置，自动降级保证可用
        3. 项目维度: 向后兼容，不影响云端部署

        策略优先级:
        1. 全局开关检查
        2. 【增强】语义触发（如可用）
        3. 【降级】关键词匹配（100%兼容）

        Args:
            user_input: 用户输入文本
            context: 上下文信息

        Returns:
            True: 应该触发感知
            False: 不需要触发
        """
        # 【修复】简单问答直接跳过视觉感知，避免无效注入
        if self._is_simple_chat(user_input):
            logger.debug(f"[PerceptionManager] 简单问答跳过感知: '{user_input[:30]}...'")
            return False

        # 【P0修复】打开/启动应用类指令默认不需要屏幕感知，避免拖死任务
        if self._is_launch_app_intent(user_input, context):
            logger.info(f"[PerceptionManager] 打开应用类指令跳过感知: '{user_input[:60]}...'")
            return False

        # 【Phase 2 增强】优先尝试语义触发（AI维度）
        if _SEMANTIC_TRIGGER_AVAILABLE:
            try:
                should_trigger, trigger_info = _should_trigger_semantic(
                    user_input,
                    context,
                    trigger_keywords=self.TRIGGER_KEYWORDS
                )

                # 记录使用的策略（用于监控）
                method = trigger_info.get("method", "unknown")
                confidence = trigger_info.get("confidence", 0.0)

                if should_trigger:
                    logger.info(
                        f"[PerceptionManager] 语义触发成功 "
                        f"(method={method}, confidence={confidence:.2f}, "
                        f"reason={trigger_info.get('reason', '')}, "
                        f"input='{user_input[:60]}...')"
                    )
                    return True

                # 语义触发返回False，继续检查是否需要降级到关键词
                # （保持与原有逻辑一致）
                if method == "semantic" and confidence > 0.5:
                    # 语义分析认为不需要触发，信任其结果
                    return False

            except Exception as e:
                # 【用户维度】失败静默降级，不中断用户体验
                logger.debug(f"[PerceptionManager] 语义触发失败，降级到关键词: {e}")

        # 【项目维度】原有逻辑作为 fallback（100%兼容）
        should_trigger, trigger_info = self.should_trigger_perception_semantic(user_input, context)
        return should_trigger

    async def get_trigger_reason(self, user_input: str, context: dict[str, Any]) -> TriggerReason:
        """
        获取触发原因

        Args:
            user_input: 用户输入
            context: 上下文

        Returns:
            TriggerReason: 触发原因
        """
        user_input_lower = user_input.lower()

        # 检查是否是明确请求
        explicit_requests = ["截图", "看看", "看一下", "显示什么", "有什么"]
        if any(req in user_input_lower for req in explicit_requests):
            return TriggerReason.USER_REQUEST

        # 【P1修复】检查是否通过语义意图触发
        intent, intent_score = self.detect_semantic_intent(user_input)
        if intent != SemanticIntent.UNKNOWN and intent_score >= 0.5:
            return TriggerReason.SEMANTIC

        # 检查屏幕变化
        if await self._check_screen_changed():
            return TriggerReason.SCREEN_CHANGED

        # 检查任务需要
        execution_history = context.get("execution_history", [])
        if execution_history:
            last_tool = execution_history[-1].get("tool", "")
            ui_tools = ["mouse_click", "keyboard_input", "launch_app"]
            if last_tool in ui_tools:
                return TriggerReason.TASK_NEED

        return TriggerReason.CONTEXTUAL

    async def _check_screen_changed(self, screenshot=None) -> bool:
        """
        检查屏幕是否变化（异步化）

        Args:
            screenshot: 可选，传入已截取的屏幕图像，避免重复截图
        """
        detector = self._get_screen_detector()
        if detector is None:
            return False

        try:
            # 【性能优化】如果传入了截图，直接使用；否则重新截图
            if screenshot is not None:
                return detector.has_changed(screenshot)

            from tools.pixel_capture import PixelCapture
            capture = PixelCapture()
            result = await capture.run_async(output_format="pil")

            if result and result.get("success"):
                screenshot = result.get("data", {}).get("image")
                if screenshot:
                    return detector.has_changed(screenshot)
        except Exception as e:
            logger.debug(f"[PerceptionManager] 屏幕变化检测失败: {e}")

        return False

    async def get_perception(self, user_input: str = "", context: dict[str, Any] | None = None) -> PerceptionData | None:
        """
        获取感知数据（异步化）

        Args:
            user_input: 用户输入（用于构建查询问题）
            context: 上下文信息

        Returns:
            PerceptionData: 感知数据，失败返回None
        """
        context = context or {}

        # ── 后台刷新任务惰性启动（LeJEPA 视觉独立服务改造）─────────────
        await self._ensure_background_refresh()

        # 优先读取全局感知缓存（< 5秒新鲜）
        try:
            cache = get_visual_analysis_cache()
            cached = cache.get_latest("default", "_global_perception", max_age=5.0)
            if cached:
                logger.debug("[PerceptionManager] 全局感知缓存命中，跳过现场截图")
                return PerceptionData(
                    perception_type=PerceptionType(cached.get("type", "vision")),
                    content=cached.get("content", ""),
                    timestamp=cached.get("timestamp", time.time()),
                    confidence=cached.get("confidence", 0.9),
                    metadata=cached.get("metadata", {}),
                    trigger_reason=TriggerReason(cached.get("trigger_reason", "periodic"))
                )
        except Exception:
            pass

        # 更新触发时间
        self._last_trigger_time = time.time()
        self.trigger_count += 1

        # 获取触发原因
        trigger_reason = await self.get_trigger_reason(user_input, context)

        try:
            # 优先获取视觉感知
            if self.vision_enabled:
                # 【性能优化】一次性截图，供所有子方法复用
                screenshot = None
                screenshot_hash = None
                if self._visual_cache_enabled:
                    try:
                        from tools.pixel_capture import PixelCapture
                        capture = PixelCapture()
                        capture_result = await capture.run_async(output_format="pil")
                        if capture_result and capture_result.get("success"):
                            screenshot = capture_result.get("data", {}).get("image")
                            if screenshot:
                                screenshot_hash = self._generate_screenshot_hash(screenshot)
                    except Exception as e:
                        logger.warning(f"[PerceptionManager] 截图失败: {e}")

                vision_method = getattr(self, '_get_vision_perception', None)
                if vision_method:
                    perception = await vision_method(user_input, trigger_reason, screenshot, screenshot_hash)
                else:
                    perception = None
                if perception:
                    self._cached_perception = perception
                    self._last_perception_time = time.time()
                    return perception

            # 降级：获取环境感知
            perception = self._get_environment_perception(trigger_reason)
            if perception:
                return perception

            logger.warning("[PerceptionManager] 所有感知类型均失败")
            return None

        except Exception as e:
            self.error_count += 1
            logger.error(f"[PerceptionManager] 获取感知数据失败: {e}", exc_info=True)
            return None

    async def _ensure_background_refresh(self):
        """惰性启动后台感知刷新任务（并发安全）

        分层感知链路（婴儿学走路）：
        - DesktopMonitor: 一直截图+变化检测（轻量CPU）
        - ONNX: 识别已知元素（快速）
        - VisionProcessor 标注队列: 不认识的元素异步丢给视觉大模型打标签（学习）
        - 思维线程: 积累标签经验，逐步减少对大模型的依赖
        """
        # 启动 DesktopMonitor 全局感知（截图 + 实时检测）
        # 【P0修复】受全局视觉学习开关控制，关闭时不启动截图
        if self.vision_enabled:
            try:
                from core.vision.desktop_monitor import get_desktop_monitor
                get_desktop_monitor().start()
            except Exception:
                pass

        # 启动 PerceptionManager 自身后台刷新（fallback / 保活）
        async with self._refresh_lock:
            if self._refresh_task is not None and not self._refresh_task.done():
                return
            with contextlib.suppress(Exception):
                self._refresh_task = safe_create_task(self._background_refresh_loop(), name="_background_refresh_loop")

        # 启动 VisionProcessor 后台标注队列（深度大模型理解，用于学习）
        # 受独立学习开关控制，不与感知开关耦合
        if self.learning_enabled:
            try:
                from core.vision.vision_processor import ensure_annotation_worker
                await ensure_annotation_worker()
            except Exception:
                pass

    async def _background_refresh_loop(self):
        """后台感知刷新：定期截图+分析，更新全局缓存，不阻塞 AgentLoop

        LeJEPA 改造：优先检测 DesktopMonitor 全局缓存是否活跃，
        如果活跃则跳过自己，避免重复截图调大模型。

        【P1-修复】默认间隔从 10 秒改为 60 秒，避免后台频繁调用视觉大模型。
        视觉大模型应服务于 AgentLoop 的即时需求，而不是每 10 秒拍一张屏。
        """
        refresh_interval = config.get("perception.background_refresh_interval", 60.0)
        logger.info(
            f"[PerceptionManager] 后台感知刷新任务启动，间隔={refresh_interval}s"
        )
        while True:
            await asyncio.sleep(refresh_interval)  # 默认 60 秒检查一次
            try:
                if not self.vision_enabled:
                    continue

                # ── 检查 DesktopMonitor 全局缓存是否新鲜 ──
                try:
                    cache = get_visual_analysis_cache()
                    dm_cache = cache.get_latest("default", "_global_perception", max_age=8.0)
                    if dm_cache and dm_cache.get("metadata", {}).get("source") == "desktop_monitor_global":
                        logger.debug("[PerceptionManager] DesktopMonitor 全局缓存活跃，跳过本次刷新")
                        continue
                except Exception:
                    pass

                # ── DesktopMonitor 不活跃时才 fallback 到自己刷新 ──
                screenshot = None
                screenshot_hash = None
                if self._visual_cache_enabled:
                    try:
                        from tools.pixel_capture import PixelCapture
                        capture = PixelCapture()
                        capture_result = await capture.run_async(output_format="pil")
                        if capture_result and capture_result.get("success"):
                            screenshot = capture_result.get("data", {}).get("image")
                            if screenshot:
                                screenshot_hash = self._generate_screenshot_hash(screenshot)
                    except Exception as e:
                        logger.debug(f"[PerceptionManager] 后台截图失败: {e}")

                vision_method = getattr(self, '_get_vision_perception', None)
                if vision_method and screenshot is not None:
                    perception = await vision_method(
                        user_input="",
                        trigger_reason=TriggerReason.PERIODIC,
                        screenshot=screenshot,
                        screenshot_hash=screenshot_hash
                    )
                    if perception:
                        try:
                            cache = get_visual_analysis_cache()
                            cache.cache_latest(
                                "default", "_global_perception",
                                perception.to_dict(), ttl=10.0
                            )
                            self._cached_perception = perception
                            self._last_perception_time = time.time()
                            logger.debug("[PerceptionManager] 后台感知刷新完成")
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"[PerceptionManager] 后台刷新异常: {e}")

    # ═══════════════════════════════════════════════════════════════
    # Phase4+ 白皮书架构：纯异步执行器入口 perceive()
    # ═══════════════════════════════════════════════════════════════
    async def perceive(self, request: "V2PerceptionRequest") -> Optional["V2PerceptionData"]:
        """
        纯异步感知执行器——白皮书标准入口

        设计约束：
        - 只做执行，不做决策（决策由 PerceptionPlanner 完成）
        - 全 async 接口，禁止同步阻塞
        - 返回 V2PerceptionData 数据契约

        Args:
            request: PerceptionRequest（由 PerceptionPlanner 生成）

        Returns:
            V2PerceptionData 或 None
        """
        if not _V2_PERCEPTION_AVAILABLE:
            logger.warning("[PerceptionManager] V2 感知模块不可用，无法执行 perceive()")
            return None

        self._last_trigger_time = time.time()
        self.trigger_count += 1

        try:
            strategy = request.strategy

            if strategy == V2PerceptionStrategy.VISION_FULL:
                # 全量视觉感知：截图 + OCR + 元素地图
                screenshot = request.screenshot
                if screenshot is None and self._visual_cache_enabled:
                    try:
                        from tools.pixel_capture import PixelCapture
                        capture = PixelCapture()
                        capture_result = await capture.run_async(output_format="pil")
                        if capture_result and capture_result.get("success"):
                            screenshot = capture_result.get("data", {}).get("image")
                    except Exception as e:
                        logger.warning(f"[PerceptionManager] V2 截图失败: {e}")

                # 获取视觉理解 + OCR
                vision_tool = self._get_vision_tool()
                vision_result = None
                ocr_result = None
                if vision_tool and screenshot is not None:
                    vision_result = await self._get_vision_understanding_async(
                        request.user_input, vision_tool, screenshot
                    )
                    ocr_result = await self._get_structured_ocr_async(screenshot)

                description = self._fuse_results(vision_result, ocr_result, request.user_input)
                element_map = await self._get_ui_elements_async()

                return V2PerceptionData(
                    source="vision",
                    description=description,
                    screenshot=screenshot,
                    ocr_text=ocr_result.get("text") if ocr_result else None,
                    element_map=element_map,
                )

            elif strategy == V2PerceptionStrategy.VISION_QUICK:
                # 快速视觉感知：仅视觉理解，无 OCR
                screenshot = request.screenshot
                vision_tool = self._get_vision_tool()
                vision_result = None
                if vision_tool and screenshot is not None:
                    vision_result = await self._get_vision_understanding_async(
                        request.user_input, vision_tool, screenshot
                    )

                description = vision_result.get("description", "") if vision_result else ""
                return V2PerceptionData(
                    source="vision",
                    description=description,
                    screenshot=screenshot,
                )

            elif strategy == V2PerceptionStrategy.ENVIRONMENT:
                # 环境感知
                import platform
                env_info = {
                    "platform": platform.system(),
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "session_id": self.session_id,
                }
                description = f"当前系统: {env_info['platform']}, 时间: {env_info['time']}"
                return V2PerceptionData(
                    source="environment",
                    description=description,
                    environment=env_info,
                )

            elif strategy == V2PerceptionStrategy.NONE:
                # 不触发感知
                return None

            else:
                logger.warning(f"[PerceptionManager] 未知感知策略: {strategy}")
                return None

        except Exception as e:
            self.error_count += 1
            logger.error(f"[PerceptionManager] V2 感知执行失败: {e}", exc_info=True)
            return None

    async def _get_vision_understanding_async(self, user_input: str, vision_tool, screenshot=None) -> dict[str, Any] | None:
        """
        异步版视觉理解 - 直接调用 vision_tool.run_async() 利用原生异步能力

        与同步版 _get_vision_understanding 行为一致，但使用异步路径避免阻塞事件循环。
        """
        try:
            # 【P1-修复】prompt 聚焦任务目标，避免泛泛描述屏幕
            if user_input:
                question = (
                    f"用户请求：'{user_input[:100]}'。\n"
                    f"请只描述与这个请求相关的屏幕元素、控件位置和当前状态，"
                    f"忽略与任务无关的内容。如果需要操作某个应用，请指出该应用窗口是否已打开、"
                    f"关键按钮/菜单的位置。"
                )
            else:
                question = "请描述当前屏幕上与任务相关的元素和状态，忽略无关内容。"

            if screenshot is not None:
                import base64
                import io
                # PIL Image → PNG BytesIO → Base64（纯内存，不碰文件系统）
                buffer = io.BytesIO()
                screenshot.save(buffer, format="PNG")
                image_b64 = base64.b64encode(buffer.getvalue()).decode()
                buffer.close()
                try:
                    result = await vision_tool.run_async(image_source=image_b64, question=question)
                finally:
                    del image_b64
            else:
                result = await vision_tool.run_async(image_source="screenshot", question=question)

            if result and result.get("success"):
                return {
                    "description": result.get("data", {}).get("description", ""),
                    "confidence": result.get("data", {}).get("confidence", 0.9),
                    "model": getattr(vision_tool, 'MODEL', 'unknown')
                }
            return None
        except Exception as e:
            logger.warning(f"[PerceptionManager] 异步视觉理解异常: {e}")
            return None

    async def _get_structured_ocr_async(self, screenshot=None) -> dict[str, Any] | None:
        """异步包装：结构化 OCR"""
        import asyncio
        return await asyncio.to_thread(self._get_structured_ocr, screenshot)

    async def _get_ui_elements_async(self) -> list[dict] | None:
        """异步包装：UI 元素提取"""
        import asyncio
        return await asyncio.to_thread(self._get_ui_elements)

    def _generate_screenshot_hash(self, screenshot) -> str:
        """
        生成截图哈希值

        Args:
            screenshot: PIL Image对象或字节数据

        Returns:
            str: 哈希值
        """
        try:
            # 如果是PIL Image，转换为字节
            if hasattr(screenshot, 'tobytes'):
                # 缩放到小尺寸以提高相似度检测
                small = screenshot.resize((64, 64)).convert('L')
                img_bytes = small.tobytes()
            elif isinstance(screenshot, bytes):
                img_bytes = screenshot
            else:
                # 尝试其他方式
                img_bytes = str(screenshot).encode()

            return hashlib.md5(img_bytes).hexdigest()
        except Exception as e:
            logger.error(f"[PerceptionManager] 生成截图哈希失败: {e}")
            # 返回基于时间的唯一值，避免缓存污染
            return f"error_{time.time()}"

    async def _get_fused_perception(
        self,
        user_input: str,
        trigger_reason: TriggerReason,
        screenshot=None,
        screenshot_hash=None
    ) -> PerceptionData | None:
        """
        【P0修复】获取融合感知（OCR + 视觉理解）

        并行执行OCR和视觉理解，融合两个结果：
        - 视觉理解提供整体场景描述
        - OCR提供精确文字识别和坐标
        - 融合后生成带坐标的元素地图

        Args:
            user_input: 用户输入
            trigger_reason: 触发原因
            screenshot: 可选，传入已截取的屏幕图像，避免重复截图
            screenshot_hash: 可选，截图哈希值（外部已计算）

        Returns:
            PerceptionData: 融合感知数据
        """
        # 获取工具
        vision_tool = self._get_vision_tool()
        if vision_tool is None:
            return None

        # 并行执行视觉理解和OCR
        vision_result = None
        ocr_result = None

        try:
            # 【性能优化】缓存处理
            if self._visual_cache_enabled:
                # 如果传入了截图但没有哈希，计算哈希
                if screenshot is not None and screenshot_hash is None:
                    screenshot_hash = self._generate_screenshot_hash(screenshot)

                # 如果没有截图，尝试获取并计算哈希
                if screenshot is None:
                    try:
                        from tools.pixel_capture import PixelCapture
                        capture = PixelCapture()
                        capture_result = await capture.run_async(output_format="pil")

                        if capture_result and capture_result.get("success"):
                            screenshot = capture_result.get("data", {}).get("image")
                            if screenshot:
                                screenshot_hash = self._generate_screenshot_hash(screenshot)
                    except Exception as e:
                        logger.warning(f"[PerceptionManager] 截图失败: {e}")

                # 检查缓存（如果有哈希）
                if screenshot_hash is not None:
                    cached_result = self.visual_cache.get_analysis(self.user_id, screenshot_hash)
                    if cached_result:
                        self._cache_hits += 1
                        logger.info(f"[PerceptionManager] 融合感知缓存命中 (hash={screenshot_hash[:8]}...)")
                        return PerceptionData(
                            perception_type=PerceptionType.VISION,
                            content=cached_result.get("description", ""),
                            confidence=cached_result.get("confidence", 0.9),
                            metadata={
                                "source": "fused_perception",
                                "cached": True,
                                "cache_hash": screenshot_hash[:8],
                                "element_map": cached_result.get("element_map", []),
                                "has_ocr": cached_result.get("has_ocr", False)
                            },
                            trigger_reason=trigger_reason
                        )
                    else:
                        self._cache_misses += 1

            # 【蓝屏修复】视觉理解和OCR改为串行执行，避免两者同时在GPU上竞争CUDA驱动
            # 原因：视觉模型（qwen3-vl）和 EasyOCR（若配置gpu=True）同时在GPU推理会导致
            #       CUDA kernel mode 死锁，触发 Windows CLOCK_WATCHDOG_TIMEOUT (0x101)
            # 【注释】fusion_timeout 当前未使用：
            # 四个感知源（视觉理解、OCR、UI元素、视觉元素）采用串行执行策略，
            # 每个子调用内部已有自己的超时机制（如 visual_understand 的 VISION_MODEL_TIMEOUT）。
            # 若后续改为并发执行（asyncio.gather），可启用 fusion_timeout 作为总超时。

            # 先执行视觉理解（GPU 密集型）
            try:
                vision_result = await asyncio.to_thread(
                    self._get_vision_understanding, user_input, vision_tool, screenshot
                )
            except Exception as e:
                logger.warning(f"[PerceptionManager] 视觉理解失败: {e}")
                vision_result = None

            # 再执行 OCR（通常 CPU 即可，避免与视觉模型竞争 GPU）
            try:
                ocr_result = await asyncio.wait_for(
                    asyncio.to_thread(self._get_structured_ocr, screenshot),
                    timeout=10.0,
                )
            except asyncio.TimeoutError:
                logger.warning("[PerceptionManager] OCR识别超时(10s)，降级跳过")
                ocr_result = None
            except Exception as e:
                logger.warning(f"[PerceptionManager] OCR识别失败: {e}")
                ocr_result = None

            # 【改造】执行 UI 自动化元素检测（按钮、输入框、菜单等原生控件）
            ui_elements = None
            try:
                ui_elements = await asyncio.wait_for(
                    asyncio.to_thread(self._get_ui_elements), timeout=10.0
                )
            except asyncio.TimeoutError:
                logger.debug("[PerceptionManager] UI元素检测超时(10s)，降级跳过")
            except Exception as e:
                logger.debug(f"[PerceptionManager] UI元素检测失败: {e}")

            # 【改造】执行视觉模型元素检测（图标、图形按钮等兜底）
            visual_elements = None
            try:
                visual_elements = await asyncio.wait_for(
                    asyncio.to_thread(self._get_visual_elements), timeout=15.0
                )
            except asyncio.TimeoutError:
                logger.debug("[PerceptionManager] 视觉元素检测超时(15s)，降级跳过")
            except Exception as e:
                logger.debug(f"[PerceptionManager] 视觉元素检测失败: {e}")

            # 融合结果
            if vision_result or ocr_result or ui_elements or visual_elements:
                fused_description = self._fuse_results(vision_result, ocr_result, user_input)

                # 【改造】多源融合构建完整元素地图
                element_map = self._build_element_map(
                    ocr_result=ocr_result,
                    ui_elements=ui_elements,
                    visual_elements=visual_elements
                )

                # 缓存结果（screenshot_hash 级缓存）
                if self._visual_cache_enabled and screenshot_hash:
                    try:
                        cache_data = {
                            "description": fused_description,
                            "confidence": 0.9,
                            "element_map": element_map,
                            "has_ocr": ocr_result is not None,
                            "timestamp": time.time()
                        }
                        self.visual_cache.cache_analysis(
                            self.user_id,
                            screenshot_hash,
                            cache_data,
                            ttl=self._visual_cache_ttl
                        )
                    except Exception as e:
                        logger.warning(f"[PerceptionManager] 缓存融合结果失败: {e}")

                # 写入全局感知缓存（LeJEPA 视觉独立服务：供 AgentLoop 快速读取）
                try:
                    cache = get_visual_analysis_cache()
                    cache.cache_latest(
                        "default", "_global_perception",
                        {
                            "type": PerceptionType.VISION.value,
                            "content": fused_description,
                            "timestamp": time.time(),
                            "confidence": 0.9,
                            "metadata": {
                                "source": "fused_perception",
                                "element_map": element_map,
                                "has_vision": vision_result is not None,
                                "has_ocr": ocr_result is not None,
                            },
                            "trigger_reason": trigger_reason.value
                        },
                        ttl=10.0
                    )
                except Exception:
                    pass

                return PerceptionData(
                    perception_type=PerceptionType.VISION,
                    content=fused_description,
                    confidence=0.9,
                    metadata={
                        "source": "fused_perception",
                        "vision_raw": vision_result.get("description", "") if vision_result else "",
                        "ocr_raw": ocr_result.get("text", "") if ocr_result else "",
                        "element_map": element_map,
                        "has_vision": vision_result is not None,
                        "has_ocr": ocr_result is not None,
                        "has_ui": ui_elements is not None,
                        "has_visual": visual_elements is not None,
                        "cached": False
                    },
                    trigger_reason=trigger_reason
                )
            else:
                logger.warning("[PerceptionManager] 视觉理解和OCR都失败")
                return None

        except Exception as e:
            logger.error(f"[PerceptionManager] 融合感知异常: {e}")
            # 降级到单一视觉理解
            return self._get_vision_understanding_perception(user_input, trigger_reason)

    def _get_vision_understanding(self, user_input: str, vision_tool, screenshot=None) -> dict[str, Any] | None:
        """
        获取视觉理解结果（同步路径专用，桥接到异步实现）

        若从异步路径调用，请使用 _get_vision_understanding_async() 以避免阻塞事件循环。
        """
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            future = asyncio.run_coroutine_threadsafe(
                self._get_vision_understanding_async(user_input, vision_tool, screenshot),
                loop
            )
            return future.result(timeout=60)
        except RuntimeError:
            return asyncio.run(self._get_vision_understanding_async(user_input, vision_tool, screenshot))

    def _get_structured_ocr(self, screenshot=None) -> dict[str, Any] | None:
        """
        获取结构化OCR结果

        Args:
            screenshot: PIL Image 对象，如果传入则直接使用，否则重新截图
        """
        try:
            import numpy as np

            from tools.screen_ocr import ScreenOCR

            ocr_tool = ScreenOCR()
            reader = ocr_tool._get_reader()

            # 【健壮性】如果 _get_reader 返回 None，降级到 VisionAgentScreenOCR 直接读取 numpy 数组
            if reader is None:
                logger.warning("[PerceptionManager] OCR reader 初始化失败，降级到 VisionAgentScreenOCR 内存模式")
                if screenshot is not None:
                    import gc

                    import numpy as np
                    # 【P0终极修复】禁止临时文件，直接传 numpy 数组给 ScreenOCR
                    img_array = np.array(screenshot)
                    try:
                        result = ocr_tool.run(
                            image_data=img_array,
                            return_positions=True,
                            left=0, top=0,
                            width=img_array.shape[1],
                            height=img_array.shape[0]
                        )
                    finally:
                        del img_array
                        gc.collect()
                else:
                    result = ocr_tool.run(source="screenshot")

                if result and result.get("success"):
                    # 转换 ScreenOCR 返回格式为统一格式
                    data = result.get("data", {})
                    items = data.get("items", [])
                    regions = []
                    for item in items:
                        regions.append({
                            "text": item.get("text", ""),
                            "x": item.get("left", 0),
                            "y": item.get("top", 0),
                            "width": item.get("right", 0) - item.get("left", 0),
                            "height": item.get("bottom", 0) - item.get("top", 0),
                            "confidence": item.get("confidence", 0)
                        })
                    return {
                        "text": data.get("text", ""),
                        "regions": regions,
                        "language": "auto"
                    }
                return None

            # 【性能优化】如果传入了截图，直接使用；否则重新截图
            if screenshot is not None:
                # PIL Image 转 numpy 数组 (RGB)
                img_array = np.array(screenshot)
                # EasyOCR 需要 BGR 格式，但 readtext 内部通常处理 RGB
                # 这里直接使用 RGB，因为 reader.readtext 接受 RGB
            else:
                # 【蓝屏修复】使用线程安全的截图
                from core.vision.safe_screenshot import safe_screenshot_to_numpy
                img_array = safe_screenshot_to_numpy(monitor=1)
                if img_array is None:
                    return None

            # 执行OCR识别
            result = reader.readtext(img_array, detail=1, paragraph=False)

            # 解析结果
            regions = []
            texts = []
            for (bbox, text, confidence) in result:
                if bbox and len(bbox) >= 4:
                    x1, y1 = bbox[0]
                    x2, y2 = bbox[2]
                    regions.append({
                        "text": text,
                        "x": int(x1),
                        "y": int(y1),
                        "width": int(x2 - x1),
                        "height": int(y2 - y1),
                        "confidence": confidence
                    })
                texts.append(text)

            return {
                "text": " ".join(texts).strip(),
                "regions": regions,
                "language": "auto"
            }
        except Exception as e:
            logger.warning(f"[PerceptionManager] OCR异常: {e}")
            return None

    def _fuse_results(self, vision_result: dict | None, ocr_result: dict | None, user_input: str) -> str:
        """融合视觉理解和OCR结果"""
        parts = []

        # 添加视觉理解描述
        if vision_result and vision_result.get("description"):
            parts.append(f"【视觉分析】{vision_result['description']}")

        # 添加OCR识别结果（如果与视觉描述不同）
        if ocr_result and ocr_result.get("text"):
            ocr_text = ocr_result["text"][:500]  # 限制长度
            # 只有当OCR文本与视觉描述有显著不同时才添加
            vision_text = vision_result.get("description", "") if vision_result else ""
            if not self._is_similar_content(ocr_text, vision_text):
                parts.append(f"【文字识别】{ocr_text}")

        # 添加用户输入上下文
        if user_input:
            parts.append(f"【用户关注】{user_input[:100]}")

        return "\n".join(parts) if parts else "无法获取屏幕内容"

    def _is_similar_content(self, text1: str, text2: str, threshold: float = 0.6) -> bool:
        """判断两段文本内容是否相似"""
        if not text1 or not text2:
            return False
        # 简单相似度：共同子串比例
        text1_lower = text1.lower()
        text2_lower = text2.lower()
        # 提取关键词（简化版）
        words1 = set(text1_lower.split())
        words2 = set(text2_lower.split())
        if not words1 or not words2:
            return False
        intersection = words1 & words2
        union = words1 | words2
        similarity = len(intersection) / len(union) if union else 0
        return similarity > threshold

    def _get_ui_elements(self) -> list[dict] | None:
        """【改造】通过 UI Automation 获取原生控件（按钮、输入框、菜单等）"""
        try:
            from tools.ui_element_detect import UIElementDetect
            tool = UIElementDetect()
            result = tool.run(max_depth=5, include_invisible=False)
            if result and result.get("success"):
                elements = result.get("data", {}).get("elements", [])
                # 转换为统一格式
                mapped = []
                for el in elements:
                    rect = el.get("rect", {})
                    mapped.append({
                        "name": el.get("name", ""),
                        "text": el.get("name", ""),
                        "x": rect.get("left", 0),
                        "y": rect.get("top", 0),
                        "width": rect.get("right", 0) - rect.get("left", 0),
                        "height": rect.get("bottom", 0) - rect.get("top", 0),
                        "type": el.get("type", "unknown").lower(),
                        "source": "uiautomation"
                    })
                logger.info(f"[PerceptionManager] UIAutomation 检测到 {len(mapped)} 个控件")
                return mapped
        except Exception as e:
            logger.debug(f"[PerceptionManager] UIAutomation 检测异常: {e}")
        return None

    def _get_visual_elements(self) -> list[dict] | None:
        """【改造】通过视觉模型检测图标、图形按钮等非文字元素"""
        try:
            from tools.visual_element_detect import VisualElementDetect
            tool = VisualElementDetect()
            result = tool.run(target="", draw_grid=True)
            if result and result.get("success"):
                elements = result.get("data", {}).get("elements", [])
                mapped = []
                for el in elements:
                    mapped.append({
                        "name": el.get("name", ""),
                        "text": el.get("name", ""),
                        "x": el.get("x", 0),
                        "y": el.get("y", 0),
                        "width": 0,
                        "height": 0,
                        "type": el.get("type", "unknown").lower(),
                        "source": "visual"
                    })
                logger.info(f"[PerceptionManager] VisualElementDetect 检测到 {len(mapped)} 个元素")
                return mapped
        except Exception as e:
            logger.debug(f"[PerceptionManager] 视觉元素检测异常: {e}")
        return None


    def _build_element_map(
        self,
        ocr_result: dict | None = None,
        ui_elements: list[dict] | None = None,
        visual_elements: list[dict] | None = None
    ) -> list[dict]:
        """【改造】多源融合构建完整可交互元素地图，去重并标注来源"""
        element_map = []
        seen_positions = set()

        def add_unique(elem: dict):
            """去重：同一位置（±20px）的元素只保留一次，优先保留有名称的"""
            x, y = elem.get("x", 0), elem.get("y", 0)
            key = (round(x / 20), round(y / 20))  # 20px 网格量化去重
            if key in seen_positions:
                # 如果已存在且当前元素有名称，尝试替换无名称的旧元素
                for existing in element_map:
                    ex, ey = existing.get("x", 0), existing.get("y", 0)
                    if (round(ex / 20), round(ey / 20)) == key:
                        if not existing.get("name") and elem.get("name"):
                            existing.update(elem)
                        break
                return
            seen_positions.add(key)
            element_map.append(elem)

        # 1. UIAutomation 控件（最准，优先）
        if ui_elements:
            for el in ui_elements:
                add_unique(el)

        # 2. OCR 文字（补充文字坐标）
        if ocr_result and ocr_result.get("regions"):
            for region in ocr_result["regions"]:
                add_unique({
                    "name": region.get("text", ""),
                    "text": region.get("text", ""),
                    "x": region.get("x", 0),
                    "y": region.get("y", 0),
                    "width": region.get("width", 0),
                    "height": region.get("height", 0),
                    "type": "text",
                    "source": "ocr"
                })

        # 3. 视觉模型检测（兜底，图标/图形按钮）
        if visual_elements:
            for el in visual_elements:
                # 如果视觉模型检测到的位置附近已有 uiautomation 元素，跳过
                x, y = el.get("x", 0), el.get("y", 0)
                key = (round(x / 20), round(y / 20))
                if key not in seen_positions:
                    add_unique(el)

        # 按类型排序：按钮/输入框优先，然后是文字，最后是其他
        type_priority = {"button": 0, "edit": 1, "input": 1, "menuitem": 2, "text": 3}
        element_map.sort(key=lambda e: (type_priority.get(e.get("type", ""), 99), e.get("y", 0), e.get("x", 0)))

        logger.info(f"[PerceptionManager] 融合后 element_map: {len(element_map)} 个元素")
        # 【修复】更新全局缓存，供工具层元素引用解析使用
        set_last_element_map(element_map)
        return element_map

    async def _get_vision_understanding_perception_async(self, user_input: str, trigger_reason: TriggerReason) -> PerceptionData | None:
        """降级方案：仅使用视觉理解（异步版）"""
        vision_tool = self._get_vision_tool()
        if vision_tool is None:
            return None

        try:
            # 【P1-修复】prompt 聚焦任务目标
            if user_input:
                question = (
                    f"用户请求：'{user_input[:100]}'。\n"
                    f"请只描述与这个请求相关的屏幕元素、控件位置和当前状态，"
                    f"忽略与任务无关的内容。"
                )
            else:
                question = "请描述当前屏幕上与任务相关的元素和状态，忽略无关内容。"
            result = await vision_tool.run_async(image_source="screenshot", question=question)

            if result and result.get("success"):
                return PerceptionData(
                    perception_type=PerceptionType.VISION,
                    content=result.get("data", {}).get("description", ""),
                    confidence=result.get("data", {}).get("confidence", 0.9),
                    metadata={
                        "source": "vision_only_fallback",
                        "fused": False
                    },
                    trigger_reason=trigger_reason
                )
        except Exception as e:
            logger.error(f"[PerceptionManager] 降级视觉理解失败: {e}")

        return None

    def _get_vision_understanding_perception(self, user_input: str, trigger_reason: TriggerReason) -> PerceptionData | None:
        """降级方案：仅使用视觉理解（同步桥接）"""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            future = asyncio.run_coroutine_threadsafe(
                self._get_vision_understanding_perception_async(user_input, trigger_reason),
                loop
            )
            return future.result(timeout=60)
        except RuntimeError:
            return asyncio.run(self._get_vision_understanding_perception_async(user_input, trigger_reason))

    async def _get_vision_perception(
        self,
        user_input: str,
        trigger_reason: TriggerReason,
        screenshot=None,
        screenshot_hash=None
    ) -> PerceptionData | None:
        """
        获取视觉感知（带去重缓存和OCR融合）

        【P0修复】现在使用融合感知（OCR + 视觉理解）替代单一视觉理解

        Args:
            user_input: 用户输入
            trigger_reason: 触发原因
            screenshot: 可选，传入已截取的屏幕图像
            screenshot_hash: 可选，截图哈希值

        Returns:
            PerceptionData: 视觉感知数据
        """
        # 【P0修复】使用融合感知替代单一视觉理解，传递截图避免重复
        return await self._get_fused_perception(user_input, trigger_reason, screenshot, screenshot_hash)

    def _get_environment_perception(self, trigger_reason: TriggerReason) -> PerceptionData | None:
        """
        获取环境感知（降级方案）

        Args:
            trigger_reason: 触发原因

        Returns:
            PerceptionData: 环境感知数据
        """
        try:
            # 获取基础系统信息
            import datetime
            import platform

            env_info = {
                "platform": platform.system(),
                "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "session_id": self.session_id
            }

            content = f"当前系统: {env_info['platform']}, 时间: {env_info['time']}"

            return PerceptionData(
                perception_type=PerceptionType.ENVIRONMENT,
                content=content,
                confidence=0.7,
                metadata=env_info,
                trigger_reason=trigger_reason
            )

        except Exception as e:
            logger.debug(f"[PerceptionManager] 环境感知失败: {e}")
            return None

    def format_for_prompt(self, perception: PerceptionData | None) -> str:
        """
        将感知数据格式化为Prompt文本

        Args:
            perception: 感知数据

        Returns:
            str: 格式化后的Prompt文本
        """
        if perception is None:
            return ""

        # 根据感知类型选择不同的格式
        if perception.perception_type == PerceptionType.VISION:
            return self._format_vision_for_prompt(perception)
        elif perception.perception_type == PerceptionType.ENVIRONMENT:
            return self._format_environment_for_prompt(perception)
        else:
            # 通用格式
            return f"\n【感知信息 - {perception.perception_type.value}】\n{perception.content}\n"

    def _format_vision_for_prompt(self, perception: PerceptionData) -> str:
        """格式化视觉感知（增强：添加行动建议，使用 element_map 提供精确坐标）"""
        # 截断过长的描述
        content = perception.content
        max_len = 1500
        if len(content) > max_len:
            content = content[:max_len] + "...[截断]"

        trigger_info = f"(触发原因: {perception.trigger_reason.value})"

        # 【新增】基于视觉内容生成行动建议
        action_hint = ""

        # 【改造】使用完整 element_map 生成结构化坐标表，不再截断前5个
        element_map = perception.metadata.get("element_map", [])
        if element_map and len(element_map) > 0:
            action_hint += "\n【当前屏幕可交互元素坐标表】\n"
            action_hint += "格式: [类型] 名称 -> 中心点(x,y) 来源\n"
            action_hint += "---\n"

            # 按类型分组展示，方便 AI 快速定位
            type_labels = {
                "button": "按钮", "edit": "输入框", "input": "输入框",
                "menuitem": "菜单", "text": "文字", "icon": "图标",
                "unknown": "未知元素"
            }

            for elem in element_map[:30]:  # 最多展示30个，防止Prompt过长
                name = elem.get("name", "") or elem.get("text", "")
                name = name[:25]  # 限制长度
                x = elem.get("x", 0)
                y = elem.get("y", 0)
                w = elem.get("width", 0)
                h = elem.get("height", 0)
                center_x = x + w // 2 if w else x
                center_y = y + h // 2 if h else y
                el_type = elem.get("type", "unknown")
                source = elem.get("source", "unknown")
                type_label = type_labels.get(el_type, el_type)

                action_hint += f"[{type_label}] {name} -> ({center_x}, {center_y}) 来源:{source}\n"

            if len(element_map) > 30:
                action_hint += f"... 还有 {len(element_map) - 30} 个元素未显示\n"

            action_hint += "---\n"
            action_hint += "【AI行动规则】\n"
            action_hint += "1. 如需点击元素，直接从上方坐标表查找名称，使用 mouse_click(x=中心点x, y=中心点y)\n"
            action_hint += "2. 如需输入文本，先 mouse_click 聚焦输入框，再 keyboard_input\n"
            action_hint += "3. 不要重复调用查找工具，上方坐标表已包含当前屏幕所有可交互元素\n"
        elif any(kw in content for kw in ["图标", "按钮", "菜单", "链接", "可点击"]):
            action_hint = """
【基于视觉的行动建议】
检测到可交互元素！如需操作，请按以下顺序：
1. 使用 find_screen_element 定位元素坐标
2. 使用 mouse_click 执行点击（配合 move_mouse 可选）
3. 如需输入，使用 keyboard_input
"""
        elif any(kw in content for kw in ["输入框", "文本框", "搜索框"]):
            action_hint = """
【基于视觉的行动建议】
检测到输入框！如需输入：
1. 使用 find_screen_element 定位输入框
2. 使用 mouse_click 聚焦
3. 使用 keyboard_input 输入文本
"""

        return f"""
【视觉感知 - 当前屏幕状态】{trigger_info}
{content}
{action_hint}
【重要】请基于上述视觉信息判断任务进度。如果屏幕显示的内容与用户预期不符，请调整策略。
"""

    def _format_environment_for_prompt(self, perception: PerceptionData) -> str:
        """格式化环境感知"""
        return f"\n【环境感知】\n{perception.content}\n"

    def get_notification_data(self, perception: PerceptionData) -> dict[str, Any]:
        """
        获取用于WebSocket通知的数据

        Args:
            perception: 感知数据

        Returns:
            dict: 通知数据
        """
        return {
            "event": "perception_triggered",
            "data": {
                "type": perception.perception_type.value,
                "trigger_reason": perception.trigger_reason.value,
                "timestamp": perception.timestamp,
                "confidence": perception.confidence,
                "content_preview": perception.content[:200] + "..." if len(perception.content) > 200 else perception.content,
                "metadata": {
                    k: v for k, v in perception.metadata.items()
                    if k not in ["raw_data", "image_data"]  # 排除大体积数据
                }
            }
        }

    def get_semantic_stats(self) -> dict[str, Any]:
        """
        获取语义触发统计信息

        Returns:
            Dict: 语义意图触发统计
        """
        total_semantic_triggers = sum(self._semantic_trigger_stats.values())
        return {
            "semantic_triggers_by_intent": {
                intent.value: count for intent, count in self._semantic_trigger_stats.items()
            },
            "total_semantic_triggers": total_semantic_triggers,
            "current_task_phase": self._current_task_phase.value,
            "phase_sensitivity": {
                phase.value: config["threshold"]
                for phase, config in self.PHASE_SENSITIVITY.items()
            },
        }

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息

        Returns:
            Dict: 包含去重统计的完整信息
        """
        # 基础统计
        stats = {
            "trigger_count": self.trigger_count,
            "error_count": self.error_count,
            "enabled": self.enabled,
            "vision_enabled": self.vision_enabled,
            "cache_valid": self._cached_perception is not None and
                          (time.time() - self._last_perception_time) < self.cache_ttl
        }

        # 【Week 3 数据去重组件】去重统计
        total_cache_requests = self._cache_hits + self._cache_misses
        stats.update({
            "visual_cache_enabled": self._visual_cache_enabled,
            "visual_cache_ttl": self._visual_cache_ttl,
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_hit_rate": self._cache_hits / total_cache_requests if total_cache_requests > 0 else 0.0,
            "duplicate_calls_avoided": self._duplicate_calls_avoided
        })

        # 【P1修复】语义触发统计
        stats.update(self.get_semantic_stats())

        return stats

    def reset(self):
        """重置状态"""
        self._last_perception_time = 0
        self._last_trigger_time = 0
        self._cached_perception = None
        self.trigger_count = 0
        self.error_count = 0
        # 【P1修复】重置任务阶段和语义统计
        self._current_task_phase = TaskPhase.INITIAL
        self._task_error_count = 0
        self._semantic_trigger_stats = dict.fromkeys(SemanticIntent, 0)
        logger.info("[PerceptionManager] 状态已重置")


# ═════════════════════════════════════════════════════════════════════════════
# 【修复】全局 element_map 缓存，供工具层（如 mouse_click）通过元素名称解析坐标
# ═════════════════════════════════════════════════════════════════════════════
_last_element_map: list[dict] = []


def get_last_element_map() -> list[dict]:
    """获取最近一次构建的 element_map（供工具层元素引用解析使用）"""
    return _last_element_map.copy()


def set_last_element_map(element_map: list[dict]) -> None:
    """更新全局 element_map 缓存"""
    global _last_element_map
    _last_element_map = element_map


# 全局实例缓存
_perception_manager_instances: dict[str, PerceptionManager] = {}


def get_perception_manager(user_id: str = "default", session_id: str = "") -> PerceptionManager:
    """
    获取感知管理器实例（工厂函数）

    Args:
        user_id: 用户ID
        session_id: 会话ID

    Returns:
        PerceptionManager: 感知管理器实例
    """
    cache_key = f"{user_id}_{session_id}"

    if cache_key not in _perception_manager_instances:
        _perception_manager_instances[cache_key] = PerceptionManager(user_id, session_id)

    return _perception_manager_instances[cache_key]


def clear_perception_manager_cache():
    """清理感知管理器缓存"""
    global _perception_manager_instances
    _perception_manager_instances.clear()
    logger.info("[PerceptionManager] 缓存已清理")
