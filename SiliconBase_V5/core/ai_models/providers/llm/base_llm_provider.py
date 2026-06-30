"""
LLM Provider基类

定义所有LLM Provider的通用接口和行为
"""

import asyncio
import logging
from abc import abstractmethod
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from core.ai_models.base import BaseModelProvider, ModelCapabilities, ModelType
from core.ai_models.config import ModelConfig
from core.ai_models.exceptions import ProviderUnavailableException, ValidationException

logger = logging.getLogger(__name__)


class BaseLLMProvider(BaseModelProvider):
    """
    LLM Provider基类

    所有LLM Provider适配器必须继承此类。
    提供了统一的消息格式处理和同步到异步的转换机制。
    """

    def __init__(self, config: ModelConfig):
        """
        初始化LLM Provider

        Args:
            config: 模型配置
        """
        super().__init__(config)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"{self.__class__.__name__}_")
        self._capabilities = ModelCapabilities(
            streaming=False,  # 子类需要显式开启
            vision=False,
            audio_input=False,
            audio_output=False,
            function_calling=False,
            max_context_length=4096,
            supports_batch=False,
            supports_system_prompt=True,
            supports_temperature=True,
            supports_max_tokens=True
        )
        logger.info(f"[{self.__class__.__name__}] LLM Provider实例创建: model={config.model_name}")

    @property
    def model_type(self) -> ModelType:
        """返回模型类型为LLM"""
        return ModelType.LLM

    async def invoke(
        self,
        input_data: str | dict | list,
        **kwargs
    ) -> str | AsyncIterator[str]:
        """
        统一调用接口

        自动处理输入格式转换：
        - str: 转换为单条用户消息
        - List[Dict]: 直接使用为标准消息格式

        Args:
            input_data: 输入数据
            **kwargs: 额外参数

        Returns:
            模型输出字符串或流式迭代器

        Raises:
            ValidationException: 输入格式无效
            InvokeException: 调用失败
        """
        self._ensure_initialized()

        # 统一输入格式转换
        try:
            messages = self._normalize_input(input_data)
        except Exception as e:
            error_msg = f"输入格式转换失败: {e}"
            logger.error(f"[{self.__class__.__name__}] {error_msg}")
            raise ValidationException(error_msg, "input_data", str(input_data)) from e

        # 检查是否请求流式输出
        stream = kwargs.get("stream", False)

        if stream and self._capabilities.streaming:
            return self.chat_stream(messages, **kwargs)
        else:
            return await self.chat(messages, **kwargs)

    def _normalize_input(self, input_data: str | list | dict) -> list[dict[str, str]]:
        """
        规范化输入数据为标准消息格式

        Args:
            input_data: 原始输入

        Returns:
            标准消息列表

        Raises:
            ValueError: 格式不支持
        """
        if isinstance(input_data, str):
            # 字符串转换为单条用户消息
            return [{"role": "user", "content": input_data}]

        elif isinstance(input_data, list):
            # 验证消息列表格式
            normalized = []
            for i, msg in enumerate(input_data):
                if isinstance(msg, dict):
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if not isinstance(content, str):
                        content = str(content)
                    normalized.append({"role": role, "content": content})
                else:
                    raise ValueError(f"消息列表第{i}项格式错误: {type(msg)}")
            return normalized

        elif isinstance(input_data, dict):
            # 单条消息字典
            role = input_data.get("role", "user")
            content = input_data.get("content", "")
            if not isinstance(content, str):
                content = str(content)
            return [{"role": role, "content": content}]

        else:
            raise ValueError(f"不支持的输入类型: {type(input_data)}")

    @abstractmethod
    async def chat(self, messages: list[dict[str, str]], **kwargs) -> str:
        """
        执行聊天对话

        Args:
            messages: 消息列表，格式为 [{"role": "user", "content": "..."}, ...]
            **kwargs: 额外参数（temperature, max_tokens等）

        Returns:
            模型生成的文本响应

        Raises:
            ProviderUnavailableException: Provider不可用
            InvokeException: 调用失败
        """
        pass

    @abstractmethod
    async def chat_stream(self, messages: list[dict[str, str]], **kwargs) -> AsyncIterator[str]:
        """
        执行流式聊天对话

        Args:
            messages: 消息列表
            **kwargs: 额外参数

        Returns:
            异步文本迭代器

        Raises:
            ProviderUnavailableException: Provider不可用
            InvokeException: 调用失败
        """
        pass

    async def health_check(self) -> dict[str, Any]:
        """
        执行健康检查

        Returns:
            健康状态字典
        """
        import time
        start_time = time.time()

        try:
            is_available = await self.is_available()
            latency_ms = (time.time() - start_time) * 1000

            if is_available:
                return {
                    "healthy": True,
                    "latency_ms": latency_ms,
                    "message": "Provider正常运行",
                    "details": {
                        "provider": self.config.provider,
                        "model": self.config.model_name,
                        "initialized": self._initialized
                    }
                }
            else:
                return {
                    "healthy": False,
                    "latency_ms": latency_ms,
                    "message": "Provider不可用",
                    "details": {
                        "provider": self.config.provider,
                        "model": self.config.model_name,
                        "initialized": self._initialized
                    }
                }
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.error(f"[{self.__class__.__name__}] 健康检查失败: {e}")
            return {
                "healthy": False,
                "latency_ms": latency_ms,
                "message": f"健康检查异常: {e}",
                "details": {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "provider": self.config.provider
                }
            }

    async def _run_sync_in_executor(self, func, *args, **kwargs):
        """
        在线程池中运行同步函数

        Args:
            func: 同步函数
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            函数执行结果
        """
        return await asyncio.to_thread(func, *args, **kwargs)

    async def cleanup(self):
        """清理资源"""
        await super().cleanup()
        if self._executor:
            self._executor.shutdown(wait=False)
            logger.info(f"[{self.__class__.__name__}] 线程池已关闭")


class ModelNotFoundException(ProviderUnavailableException):
    """模型不存在异常"""

    def __init__(self, provider: str, model_name: str):
        super().__init__(
            provider=provider,
            reason=f"模型 '{model_name}' 不存在",
            error_code="MODEL_NOT_FOUND"
        )
        self.model_name = model_name
