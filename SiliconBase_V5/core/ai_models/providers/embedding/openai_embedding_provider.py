"""
OpenAI Embedding Provider

支持OpenAI API格式的向量嵌入服务，包括:
- OpenAI官方API (text-embedding-3-small, text-embedding-3-large, text-embedding-ada-002)
- Azure OpenAI
- OpenAI兼容的第三方服务

文档: https://platform.openai.com/docs/guides/embeddings
"""

import logging
from typing import Any

from core.ai_models.exceptions import ConfigurationException, EmbeddingException, ModelLoadException
from core.ai_models.providers.embedding.base_embedding_provider import BaseEmbeddingProvider

logger = logging.getLogger(__name__)


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """
    OpenAI API Embedding Provider

    通过HTTP API调用OpenAI或兼容服务的嵌入接口。
    支持官方OpenAI API以及第三方兼容服务。

    支持的模型:
    - text-embedding-3-small (1536维，推荐)
    - text-embedding-3-large (3072维，高精度)
    - text-embedding-ada-002 (1536维，旧版)

    配置示例:
        # OpenAI官方
        config = ModelConfig(
            provider="openai_embedding",
            model_name="text-embedding-3-small",
            api_key="sk-...",
            base_url=None  # 使用官方默认
        )

        # 第三方兼容服务
        config = ModelConfig(
            provider="openai_embedding",
            model_name="embedding-model",
            api_key="...",
            base_url="https://api.example.com/v1"
        )

    环境变量:
        OPENAI_API_KEY: OpenAI API密钥
        OPENAI_API_BASE: 自定义API基础URL
    """

    # 默认模型和维度
    DEFAULT_MODEL = "text-embedding-3-small"

    # 已知模型的维度映射
    MODEL_DIMENSIONS = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536
    }

    def __init__(self, config):
        """
        初始化OpenAI Embedding Provider

        Args:
            config: ModelConfig配置对象
                - model_name: 模型名称
                - api_key: API密钥
                - base_url: API基础URL（可选，用于第三方服务）
                - timeout: 超时时间（秒，默认120）
        """
        super().__init__(config)
        self._client = None
        self._vector_dim = None

        logger.info(f"[{self.__class__.__name__}] Provider实例创建")

    async def initialize(self) -> bool:
        """
        异步初始化Provider

        初始化OpenAI客户端并验证API密钥。

        Returns:
            bool: 初始化是否成功

        Raises:
            ConfigurationException: 配置错误时抛出
            ModelLoadException: 初始化失败时抛出
        """
        try:
            # 延迟导入
            try:
                import openai
            except ImportError as _exc:
                raise ModelLoadException(
                    "openai库未安装。请运行: pip install openai",
                    provider=self.config.provider
                ) from _exc

            # 获取API密钥
            api_key = self.config.api_key
            if not api_key:
                # 尝试从环境变量获取
                import os
                api_key = os.environ.get("OPENAI_API_KEY")

            if not api_key:
                raise ConfigurationException(
                    "OpenAI API密钥未配置",
                    config_field="api_key",
                    config_value=None
                )

            # 获取基础URL
            base_url = self.config.base_url
            if not base_url:
                import os
                base_url = os.environ.get("OPENAI_API_BASE")

            # 获取超时配置
            timeout = self.config.timeout or 120

            # 创建客户端
            client_kwargs = {
                "api_key": api_key,
                "timeout": timeout
            }
            if base_url:
                client_kwargs["base_url"] = base_url

            self._client = openai.AsyncOpenAI(**client_kwargs)

            # 获取模型名称
            model_name = self.config.model_name or self.DEFAULT_MODEL

            # 从已知映射获取维度，或设为None等待首次调用确认
            self._vector_dim = self.MODEL_DIMENSIONS.get(model_name)

            logger.info(
                f"[{self.__class__.__name__}] 客户端初始化成功, "
                f"模型: {model_name}, 基础URL: {base_url or '默认'}"
            )

            self._mark_initialized()
            return True

        except ConfigurationException:
            raise
        except ModelLoadException:
            raise
        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] 初始化失败: {e}")
            raise ModelLoadException(
                f"OpenAI Embedding初始化失败: {e}",
                provider=self.config.provider
            ) from e

    async def embed_single(self, text: str, **kwargs) -> list[float]:
        """
        单文本嵌入

        Args:
            text: 要嵌入的文本
            **kwargs:
                - dimensions: 输出维度（仅text-embedding-3支持）

        Returns:
            List[float]: 文本的向量表示

        Raises:
            EmbeddingException: 嵌入失败时抛出
        """
        if not self._client:
            raise EmbeddingException("Provider未初始化", error_code="PROVIDER_NOT_INITIALIZED")

        try:
            # 处理空文本
            if not text or not text.strip():
                logger.warning("[{self.__class__.__name__}] 收到空文本，返回零向量")
                return [0.0] * (self._vector_dim or 1536)

            # OpenAI限制单条文本长度（约8191 tokens）
            # 这里做简单截断保护
            text = text[:8000] if len(text) > 8000 else text

            model_name = self.config.model_name or self.DEFAULT_MODEL

            # 构建请求参数
            request_params = {
                "model": model_name,
                "input": text
            }

            # 支持dimensions参数（text-embedding-3系列）
            if "dimensions" in kwargs:
                request_params["dimensions"] = kwargs["dimensions"]

            # 调用API
            response = await self._client.embeddings.create(**request_params)

            # 提取向量
            vector = response.data[0].embedding

            # 更新维度信息
            if self._vector_dim is None:
                self._vector_dim = len(vector)

            return vector

        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] 单文本嵌入失败: {e}")
            raise EmbeddingException(
                f"OpenAI嵌入失败: {e}",
                error_code="OPENAI_EMBEDDING_ERROR",
                details={
                    "text_length": len(text) if text else 0,
                    "model": self.config.model_name
                }
            ) from e

    async def embed_batch(self, texts: list[str], **kwargs) -> list[list[float]]:
        """
        批量文本嵌入

        OpenAI API原生支持批量嵌入，单次请求最多2048个文本。

        Args:
            texts: 要嵌入的文本列表
            **kwargs:
                - dimensions: 输出维度

        Returns:
            List[List[float]]: 向量列表，与输入顺序一致

        Raises:
            EmbeddingException: 嵌入失败时抛出
        """
        if not self._client:
            raise EmbeddingException("Provider未初始化", error_code="PROVIDER_NOT_INITIALIZED")

        try:
            # 处理空列表
            if not texts:
                return []

            # 记录空文本位置
            empty_indices = []
            processed_texts = []

            for i, text in enumerate(texts):
                if not text or not text.strip():
                    empty_indices.append(i)
                    processed_texts.append("")  # 保持位置
                else:
                    # 截断过长文本
                    processed_texts.append(text[:8000] if len(text) > 8000 else text)

            model_name = self.config.model_name or self.DEFAULT_MODEL

            # OpenAI批量限制为2048
            MAX_BATCH_SIZE = 2048
            all_vectors = []

            for i in range(0, len(processed_texts), MAX_BATCH_SIZE):
                batch = processed_texts[i:i + MAX_BATCH_SIZE]

                # 构建请求参数
                request_params = {
                    "model": model_name,
                    "input": batch
                }

                if "dimensions" in kwargs:
                    request_params["dimensions"] = kwargs["dimensions"]

                # 调用API
                response = await self._client.embeddings.create(**request_params)

                # 按顺序提取向量
                batch_vectors = [item.embedding for item in response.data]
                all_vectors.extend(batch_vectors)

                logger.debug(f"[{self.__class__.__name__}] 批量嵌入进度: {min(i + MAX_BATCH_SIZE, len(processed_texts))}/{len(processed_texts)}")

            # 填充空文本的零向量
            dim = len(all_vectors[0]) if all_vectors else (self._vector_dim or 1536)
            for idx in empty_indices:
                all_vectors[idx] = [0.0] * dim

            # 更新维度信息
            if self._vector_dim is None and all_vectors:
                self._vector_dim = len(all_vectors[0])

            logger.debug(f"[{self.__class__.__name__}] 批量嵌入完成: {len(texts)} 条文本")
            return all_vectors

        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] 批量嵌入失败: {e}")
            raise EmbeddingException(
                f"OpenAI批量嵌入失败: {e}",
                error_code="OPENAI_BATCH_EMBEDDING_ERROR",
                details={
                    "batch_size": len(texts) if texts else 0,
                    "model": self.config.model_name
                }
            ) from e

    @property
    def vector_dimension(self) -> int:
        """
        返回向量维度

        Returns:
            int: 向量维度
        """
        if self._vector_dim:
            return self._vector_dim

        # 从配置模型推断
        model_name = self.config.model_name or self.DEFAULT_MODEL
        return self.MODEL_DIMENSIONS.get(model_name, 1536)

    async def health_check(self) -> dict[str, Any]:
        """
        健康检查

        测试API连接和响应。

        Returns:
            Dict: 健康状态信息
        """
        import time

        if not self._initialized:
            return {
                "healthy": False,
                "latency_ms": 0.0,
                "message": "Provider未初始化",
                "details": {"provider": self.config.provider}
            }

        try:
            start_time = time.time()
            # 执行简单嵌入测试
            test_vector = await self.embed_single("health check test")
            latency_ms = (time.time() - start_time) * 1000

            return {
                "healthy": True,
                "latency_ms": round(latency_ms, 2),
                "message": f"OpenAI嵌入服务正常，向量维度: {len(test_vector)}",
                "details": {
                    "provider": self.config.provider,
                    "model": self.config.model_name,
                    "vector_dimension": len(test_vector),
                    "base_url": self.config.base_url or "default"
                }
            }

        except Exception as e:
            return {
                "healthy": False,
                "latency_ms": 0.0,
                "message": f"健康检查失败: {str(e)}",
                "details": {
                    "provider": self.config.provider,
                    "error": str(e)
                }
            }

    def get_model_info(self) -> dict[str, Any]:
        """
        获取模型信息

        Returns:
            Dict: 模型详细信息
        """
        model_name = self.config.model_name or self.DEFAULT_MODEL

        return {
            "model_name": model_name,
            "vector_dimension": self.vector_dimension,
            "initialized": self._initialized,
            "provider": self.config.provider,
            "base_url": self.config.base_url or "https://api.openai.com/v1",
            "known_dimensions": self.MODEL_DIMENSIONS
        }

    async def cleanup(self):
        """
        清理资源

        关闭HTTP客户端连接。
        """
        if self._client:
            await self._client.close()
            logger.info(f"[{self.__class__.__name__}] HTTP客户端已关闭")

        await super().cleanup()
