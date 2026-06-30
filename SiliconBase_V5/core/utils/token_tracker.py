#!/usr/bin/env python3
"""
Token追踪器 - 使用tiktoken精确计数
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
功能：
  ✓ 精确计算文本Token数量（基于tiktoken）
  ✓ 支持多种模型的编码器缓存
  ✓ 消息列表Token计数（包含OpenAI消息格式）
  ✓ 估算成本所需的Token统计

支持的模型：
  - OpenAI: gpt-4, gpt-4-turbo, gpt-3.5-turbo
  - 兼容模型: 使用cl100k_base编码
"""

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.logger import logger

# 尝试导入tiktoken
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    logger.warning("[TokenTracker] tiktoken未安装，将使用字符估算模式")
    tiktoken = None  # type: ignore


@dataclass
class TokenCountResult:
    """Token计数结果"""
    input_tokens: int
    output_tokens: int
    total_tokens: int
    model: str
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "model": self.model,
            "timestamp": self.timestamp.isoformat()
        }


class TokenTracker:
    """
    Token追踪器 - 精确计数与管理

    使用示例：
        tracker = TokenTracker()

        # 计数单条文本
        count = tracker.count_tokens("Hello world", model="gpt-4")

        # 计数消息列表
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"}
        ]
        count = tracker.count_message_tokens(messages, model="gpt-4")
    """

    # 模型到编码器的映射
    MODEL_ENCODING_MAP = {
        # GPT-4系列
        "gpt-4": "cl100k_base",
        "gpt-4-0314": "cl100k_base",
        "gpt-4-0613": "cl100k_base",
        "gpt-4-32k": "cl100k_base",
        "gpt-4-32k-0314": "cl100k_base",
        "gpt-4-32k-0613": "cl100k_base",
        "gpt-4-turbo": "cl100k_base",
        "gpt-4-turbo-preview": "cl100k_base",
        "gpt-4-1106-preview": "cl100k_base",
        "gpt-4-0125-preview": "cl100k_base",
        "gpt-4o": "o200k_base",
        "gpt-4o-mini": "o200k_base",

        # GPT-3.5系列
        "gpt-3.5-turbo": "cl100k_base",
        "gpt-3.5-turbo-0301": "cl100k_base",
        "gpt-3.5-turbo-0613": "cl100k_base",
        "gpt-3.5-turbo-1106": "cl100k_base",
        "gpt-3.5-turbo-0125": "cl100k_base",
        "gpt-3.5-turbo-16k": "cl100k_base",
        "gpt-3.5-turbo-16k-0613": "cl100k_base",

        # 文本嵌入
        "text-embedding-ada-002": "cl100k_base",
        "text-embedding-3-small": "cl100k_base",
        "text-embedding-3-large": "cl100k_base",

        # 其他模型默认使用cl100k_base
        "default": "cl100k_base"
    }

    def __init__(self):
        """初始化Token追踪器"""
        self._encoders: dict[str, Any] = {}  # 编码器缓存
        self._lock = threading.Lock()  # 线程锁
        self._stats_cache: dict[str, dict] = {}  # 统计缓存

        if not TIKTOKEN_AVAILABLE:
            logger.warning("[TokenTracker] 运行在估算模式（无tiktoken）")

    def _get_encoding_name(self, model: str) -> str:
        """
        获取模型对应的编码器名称

        Args:
            model: 模型名称

        Returns:
            编码器名称
        """
        # 精确匹配
        if model in self.MODEL_ENCODING_MAP:
            return self.MODEL_ENCODING_MAP[model]

        # 前缀匹配（如 gpt-4-*）
        for model_prefix, encoding in self.MODEL_ENCODING_MAP.items():
            if model.startswith(model_prefix):
                return encoding

        # 默认编码
        return self.MODEL_ENCODING_MAP["default"]

    def _get_encoder(self, model: str) -> Any:
        """
        获取模型的编码器（带缓存）

        Args:
            model: 模型名称

        Returns:
            tiktoken编码器
        """
        encoding_name = self._get_encoding_name(model)

        with self._lock:
            if encoding_name not in self._encoders:
                try:
                    if TIKTOKEN_AVAILABLE:
                        self._encoders[encoding_name] = tiktoken.get_encoding(encoding_name)
                        logger.debug(f"[TokenTracker] 加载编码器: {encoding_name}")
                    else:
                        self._encoders[encoding_name] = None
                except Exception as e:
                    logger.error(f"[TokenTracker] 加载编码器失败 {encoding_name}: {e}")
                    self._encoders[encoding_name] = None

            return self._encoders[encoding_name]

    def count_tokens(self, text: str, model: str = "gpt-4") -> int:
        """
        计算文本的Token数量

        Args:
            text: 要计数的文本
            model: 模型名称（影响编码选择）

        Returns:
            Token数量
        """
        if not text:
            return 0

        if not isinstance(text, str):
            text = str(text)

        encoder = self._get_encoder(model)

        if encoder:
            try:
                return len(encoder.encode(text))
            except Exception as e:
                logger.error(f"[TokenTracker] Token计数失败: {e}")
                # 失败时回退到估算
                return self._estimate_tokens(text)
        else:
            # 无tiktoken时使用估算
            return self._estimate_tokens(text)

    def _estimate_tokens(self, text: str) -> int:
        """
        估算Token数量（无tiktoken时使用）

        使用字符数/4作为粗略估算（适用于英文）
        中文按字符数/2估算

        Args:
            text: 要估算的文本

        Returns:
            估算的Token数量
        """
        if not text:
            return 0

        # 简单的启发式估算
        # 英文约4字符/token，中文约2字符/token
        total_chars = len(text)

        # 检测中文字符比例
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        chinese_ratio = chinese_chars / total_chars if total_chars > 0 else 0

        # 加权估算
        if chinese_ratio > 0.5:
            # 主要是中文
            return int(total_chars / 2)
        else:
            # 主要是英文
            return int(total_chars / 4)

    def count_message_tokens(
        self,
        messages: list[dict[str, str]],
        model: str = "gpt-4"
    ) -> int:
        """
        计算消息列表的Token数量（OpenAI格式）

        包含消息格式开销（如role标记等）

        Args:
            messages: 消息列表，格式为 [{"role": "user", "content": "..."}, ...]
            model: 模型名称

        Returns:
            Token数量
        """
        if not messages:
            return 0

        total_tokens = 0

        # 每条消息的固定开销（OpenAI格式）
        # 每条消息大约4个token的开销（role标记、分隔符等）
        MESSAGE_OVERHEAD = 4

        for message in messages:
            if not isinstance(message, dict):
                continue

            # 计算内容token
            content = message.get("content", "")
            if content:
                total_tokens += self.count_tokens(content, model)

            # 计算name字段（如果有）
            name = message.get("name", "")
            if name:
                total_tokens += self.count_tokens(name, model)

            # 角色标记开销
            role = message.get("role", "")
            if role:
                total_tokens += self.count_tokens(role, model)

            # 固定开销
            total_tokens += MESSAGE_OVERHEAD

        # 回复的固定开销（assistant标记）
        total_tokens += 3

        return total_tokens

    def count_chat_completion(
        self,
        messages: list[dict[str, str]],
        response_content: str,
        model: str = "gpt-4"
    ) -> TokenCountResult:
        """
        计算完整对话的Token数量（输入+输出）

        Args:
            messages: 输入消息列表
            response_content: AI响应内容
            model: 模型名称

        Returns:
            TokenCountResult对象
        """
        input_tokens = self.count_message_tokens(messages, model)
        output_tokens = self.count_tokens(response_content, model) if response_content else 0

        return TokenCountResult(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            model=model,
            timestamp=datetime.now()
        )

    def get_model_info(self, model: str) -> dict[str, Any]:
        """
        获取模型信息

        Args:
            model: 模型名称

        Returns:
            模型信息字典
        """
        encoding_name = self._get_encoding_name(model)
        encoder = self._get_encoder(model)

        return {
            "model": model,
            "encoding": encoding_name,
            "encoder_available": encoder is not None,
            "tiktoken_available": TIKTOKEN_AVAILABLE
        }

    def clear_cache(self):
        """清除编码器缓存"""
        with self._lock:
            self._encoders.clear()
            self._stats_cache.clear()
        logger.info("[TokenTracker] 缓存已清除")

    def get_supported_models(self) -> list[str]:
        """获取支持的模型列表"""
        return list(self.MODEL_ENCODING_MAP.keys())


# 全局单例实例
token_tracker = TokenTracker()


# 便捷函数
def count_tokens(text: str, model: str = "gpt-4") -> int:
    """便捷函数：计算文本Token数量"""
    return token_tracker.count_tokens(text, model)


def count_message_tokens(messages: list[dict[str, str]], model: str = "gpt-4") -> int:
    """便捷函数：计算消息列表Token数量"""
    return token_tracker.count_message_tokens(messages, model)


def count_chat_completion(
    messages: list[dict[str, str]],
    response_content: str,
    model: str = "gpt-4"
) -> TokenCountResult:
    """便捷函数：计算完整对话Token数量"""
    return token_tracker.count_chat_completion(messages, response_content, model)


# =============================================================================
# 测试代码
# =============================================================================
if __name__ == "__main__":
    # 简单测试
    tracker = TokenTracker()

    # 测试文本计数
    text = "Hello, world! 这是一个测试。"
    count = tracker.count_tokens(text, "gpt-4")
    print(f"文本: {text}")
    print(f"Token数: {count}")

    # 测试消息计数
    messages = [
        {"role": "system", "content": "你是一个有用的助手。"},
        {"role": "user", "content": "你好，请介绍一下自己。"}
    ]
    msg_count = tracker.count_message_tokens(messages, "gpt-4")
    print(f"\n消息Token数: {msg_count}")

    # 测试完整对话
    response = "你好！我是AI助手，很高兴为你服务。"
    result = tracker.count_chat_completion(messages, response, "gpt-4")
    print("\n完整对话统计:")
    print(f"  输入Token: {result.input_tokens}")
    print(f"  输出Token: {result.output_tokens}")
    print(f"  总Token: {result.total_tokens}")
