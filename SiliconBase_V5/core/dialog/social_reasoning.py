#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
社会推理引擎：理解用户意图、情感、检测欺骗，生成共情回应。  # 模块功能概述
"""  # 文档字符串结束

# 先过滤 transformers 警告  # 警告过滤说明
import os  # 导入操作系统模块
import warnings  # 导入警告模块

warnings.filterwarnings("ignore", message="Using `TRANSFORMERS_CACHE` is deprecated")  # 忽略弃用警告
warnings.filterwarnings("ignore", category=FutureWarning, module="transformers")  # 忽略transformers的未来警告

# 设置HuggingFace环境变量（优先使用项目本地缓存，避免连接超时）
import pathlib

_project_root = pathlib.Path(__file__).parent.parent
_local_hf_cache = str(_project_root / "checkpoints" / "hf_cache")
if not os.environ.get("HF_HOME"):
    os.environ["HF_HOME"] = _local_hf_cache
if not os.environ.get("SENTENCE_TRANSFORMERS_HOME"):
    os.environ["SENTENCE_TRANSFORMERS_HOME"] = _local_hf_cache
# 默认启用离线模式，避免连接huggingface.co超时
if not os.environ.get("TRANSFORMERS_OFFLINE"):
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
if not os.environ.get("HF_HUB_OFFLINE"):
    os.environ["HF_HUB_OFFLINE"] = "1"

from typing import Any  # 导入类型注解

from core.logger import logger  # 导入日志记录器

# 配置导入（带降级处理）
config = None
try:
    from core.config import config  # 尝试导入配置
except ImportError:  # 导入失败时使用虚拟配置
    class _DummyConfig:
        """虚拟配置类 - 当配置不可用时使用"""
        def get(self, key, default=None):
            return default  # 始终返回默认值
    config = _DummyConfig()


class SocialReasoning:  # 社会推理引擎类
    """  # 类文档字符串开始
    社会推理引擎：理解用户意图、情感、检测欺骗，生成共情回应。  # 类功能描述
    """  # 类文档字符串结束
    def __init__(self, sentiment_model: str = "uer/roberta-base-finetuned-jd-binary-chinese"):  # 初始化
        self.sentiment_analyzer = None  # 情感分析器初始化为None

        # 检查功能是否被禁用
        enabled = config.get("features.social_reasoning.enabled", False)
        if not enabled:
            logger.info("[SocialReasoning] 功能已禁用，使用规则回退模式")
            self.user_model: dict[str, Any] = {}  # 用户画像字典
            self.high_risk_keywords = ["删除系统", "关闭安全", "格式化", "rm -rf", "shutdown", "重启", "删除文件"]
            return

        # 加载情感分析模型（离线模式，仅使用本地缓存）
        try:
            import os

            from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline

            # 【修复】构建本地模型路径（HF缓存格式）
            model_name_safe = sentiment_model.replace("/", "--")
            local_model_path = os.path.join(
                _local_hf_cache,
                f"models--{model_name_safe}",
                "snapshots"  # transformers会自动选择正确的snapshot
            )

            # 查找实际的snapshot目录
            if os.path.exists(local_model_path):
                snapshot_dirs = [d for d in os.listdir(local_model_path) if os.path.isdir(os.path.join(local_model_path, d))]
                if snapshot_dirs:
                    actual_model_path = os.path.join(local_model_path, snapshot_dirs[0])
                    logger.info(f"[SocialReasoning] 使用本地模型: {actual_model_path}")

                    # 【修复】使用 from_pretrained 方式加载，更可靠
                    from transformers import AutoModelForSequenceClassification, AutoTokenizer

                    model = AutoModelForSequenceClassification.from_pretrained(
                        actual_model_path,
                        local_files_only=True
                    )
                    tokenizer = AutoTokenizer.from_pretrained(
                        actual_model_path,
                        local_files_only=True
                    )

                    self.sentiment_analyzer = pipeline(
                        task="sentiment-analysis",
                        model=model,
                        tokenizer=tokenizer
                    )
                    logger.info(f"[SocialReasoning] 情感分析模型就绪: {sentiment_model}")
                else:
                    raise FileNotFoundError(f"模型snapshot目录不存在: {local_model_path}")
            else:
                raise FileNotFoundError(f"本地模型不存在: {local_model_path}，请运行: huggingface-cli download {sentiment_model} --local-dir {_local_hf_cache}/models--{model_name_safe}")

        except Exception as e:
            logger.warning(f"[SocialReasoning] 模型加载失败，使用规则回退: {e}")
        self.user_model: dict[str, Any] = {}  # 用户画像字典（可选：存储用户长期画像）

        # 高危关键词列表（用于欺骗检测）  # 安全检测关键词
        self.high_risk_keywords = ["删除系统", "关闭安全", "格式化", "rm -rf", "shutdown", "重启", "删除文件"]  # 危险操作关键词

    async def analyze_sentiment(self, text: str) -> tuple[str, float]:  # 情感分析
        """返回情感标签（POSITIVE/NEGATIVE/NEUTRAL）和置信度"""  # 方法文档字符串
        if self.sentiment_analyzer:  # 如果有情感分析器
            try:  # 异常处理
                import asyncio
                result = (await asyncio.to_thread(self.sentiment_analyzer, text))[0]  # 分析文本情感
                label = result['label']  # 获取标签
                score = result['score']  # 获取置信度
                # 中文模型可能输出 "positive"/"negative" 或其他，统一映射
                if 'positive' in label.lower():  # 如果是正面
                    return "POSITIVE", score  # 返回正面和置信度
                elif 'negative' in label.lower():  # 如果是负面
                    return "NEGATIVE", score  # 返回负面和置信度
                else:  # 其他情况
                    return "NEUTRAL", score  # 返回中性
            except Exception as e:  # 捕获异常
                logger.error(f"情感分析出错: {e}")  # 记录错误
        # 回退：简单规则（适合中文）
        if any(word in text for word in ['好', '棒', '谢谢', '感谢', '不错', '赞']):  # 正面关键词
            return "POSITIVE", 0.6  # 返回正面
        if any(word in text for word in ['坏', '差', '垃圾', '讨厌', '烦', '烂']):  # 负面关键词
            return "NEGATIVE", 0.6  # 返回负面
        return "NEUTRAL", 0.5  # 默认中性

    async def detect_deception(self, utterance: str) -> tuple[bool, str]:  # 欺骗检测
        """检测用户是否试图欺骗或诱导AI做危险操作"""  # 方法文档字符串
        # 简单规则：高危指令 + 无预警
        for kw in self.high_risk_keywords:  # 遍历高危关键词
            if kw in utterance and "测试" not in utterance and "玩笑" not in utterance:  # 检查关键词且排除测试/玩笑
                return True, f"包含高危关键词 {kw} 且无预警"  # 返回检测到欺骗
        return False, ""  # 未检测到欺骗

    def infer_user_goal(self, utterance: str, context: str = "") -> tuple[str, float]:  # 意图推断
        """推断用户可能的深层意图（返回意图类型和置信度）"""  # 方法文档字符串
        # 可调用LLM或简单规则，这里仅作示例
        if "为什么" in utterance or "怎么" in utterance:  # 疑问词
            return "question", 0.8  # 返回提问意图
        if "帮我" in utterance:  # 请求帮助
            return "request", 0.9  # 返回请求意图
        if "你好" in utterance or "在吗" in utterance:  # 问候语
            return "greeting", 0.9  # 返回问候意图
        return "unknown", 0.5  # 默认未知意图

    def generate_empathetic_response(self, user_emotion: str, agent_response: str) -> str:  # 共情回应
        """根据用户情感调整回复措辞"""  # 方法文档字符串
        if user_emotion == "NEGATIVE":  # 如果用户情绪负面
            # 添加歉意或安慰前缀
            return f"很抱歉，{agent_response}"  # 添加道歉前缀
        elif user_emotion == "POSITIVE":  # 如果用户情绪正面
            # 添加积极前缀
            return f"太好了，{agent_response}"  # 添加积极前缀
        return agent_response  # 中性情绪直接返回

    def update_user_model(self, user_id: str, interaction: dict[str, Any]):  # 更新用户画像
        """更新用户画像（简单示例）"""  # 方法文档字符串
        if user_id not in self.user_model:  # 如果用户不存在
            self.user_model[user_id] = {"history": []}  # 创建用户记录
        self.user_model[user_id]["history"].append(interaction)  # 添加交互记录


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"社会推理引擎"，负责理解用户情感、
# 检测潜在欺骗行为、推断用户意图，并生成共情回应。是系统人性化
# 交互的关键组件。
#
# 【核心功能效果】
# 1. 情感分析：识别用户输入的情感倾向（正面/负面/中性）
# 2. 欺骗检测：识别包含高危关键词的潜在危险指令
# 3. 意图推断：基于规则推断用户的深层意图类型
# 4. 共情回应：根据用户情感调整AI回复的措辞风格
# 5. 用户画像：维护用户长期交互历史
#
# 【关联文件】
# - core/agent_loop.py      : 调用情感分析和共情回应
# - core/dialogue_manager.py: 集成欺骗检测
# - core/logger.py          : 记录日志
#
# 【使用场景】
# - 用户输入时分析情感，调整AI回应风格
# - 检测潜在危险指令，触发安全确认流程
# - 长期维护用户画像，提供个性化交互体验
# =============================================================================
