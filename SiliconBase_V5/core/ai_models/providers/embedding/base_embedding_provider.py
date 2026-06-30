"""
向量嵌入Provider基类

定义所有Embedding Provider的通用接口和行为
"""

import logging
from abc import abstractmethod
from typing import Any

from core.ai_models.base import BaseModelProvider, ModelType

logger = logging.getLogger(__name__)


class BaseEmbeddingProvider(BaseModelProvider):
    """
    向量嵌入Provider基类

    所有向量嵌入Provider必须继承此类，实现embed_single和embed_batch方法。
    支持单文本和批量文本的向量化，自动处理输入类型分发。

    特性:
    - 自动区分单文本和批量文本输入
    - 支持归一化选项
    - 提供向量维度信息
    - 统一的错误处理

    Example:
        provider = SentenceTransformerProvider(config)
        await provider.initialize()

        # 单文本嵌入
        vector = await provider.embed_single("Hello World")

        # 批量文本嵌入
        vectors = await provider.embed_batch(["Text 1", "Text 2"], batch_size=32)
    """

    def __init__(self, config):
        """
        初始化Embedding Provider

        Args:
            config: ModelConfig配置对象
        """
        super().__init__(config)
        # 设置embedding专用能力
        self._capabilities.supports_batch = True
        self._capabilities.supports_temperature = False
        self._capabilities.supports_max_tokens = False
        self._capabilities.supports_system_prompt = False

        logger.info(f"[{self.__class__.__name__}] Embedding Provider实例创建")

    @property
    def model_type(self) -> ModelType:
        """
        返回模型类型

        Returns:
            ModelType.EMBEDDING
        """
        return ModelType.EMBEDDING

    async def invoke(
        self,
        input_data: str | list[str],
        **kwargs
    ) -> list[float] | list[list[float]]:
        """
        文本向量化 - 统一入口

        根据输入类型自动分发到embed_single或embed_batch方法。
        这是BaseModelProvider.invoke的Embedding专用实现。

        Args:
            input_data: 输入数据，可以是:
                - str: 单个文本，返回单个向量
                - List[str]: 文本列表，返回向量列表
            **kwargs: 额外参数:
                - batch_size: 批量大小（仅批量模式有效）
                - normalize: 是否归一化（Provider支持时）

        Returns:
            Union[List[float], List[List[float]]]:
                - 单文本输入返回List[float]（向量）
                - 批量输入返回List[List[float]]（向量列表）

        Raises:
            ValueError: 输入类型不支持
            EmbeddingException: 嵌入过程中发生错误

        Example:
            # 单文本
            vector = await provider.invoke("Hello")

            # 批量文本
            vectors = await provider.invoke(["Hello", "World"], batch_size=16)
        """
        if isinstance(input_data, str):
            # 单文本模式
            logger.debug(f"[{self.__class__.__name__}] 单文本嵌入")
            return await self.embed_single(input_data, **kwargs)

        elif isinstance(input_data, list):
            # 批量模式
            if not input_data:
                logger.warning(f"[{self.__class__.__name__}] 批量嵌入收到空列表")
                return []

            # 验证列表元素类型
            if not all(isinstance(item, str) for item in input_data):
                raise ValueError("批量嵌入要求所有元素必须是字符串")

            logger.debug(f"[{self.__class__.__name__}] 批量嵌入: {len(input_data)} 条文本")
            return await self.embed_batch(input_data, **kwargs)

        else:
            error_msg = f"不支持的输入类型: {type(input_data).__name__}，期望str或List[str]"
            logger.error(f"[{self.__class__.__name__}] {error_msg}")
            raise ValueError(error_msg)

    @abstractmethod
    async def embed_single(self, text: str, **kwargs) -> list[float]:
        """
        单文本嵌入

        将单个文本转换为向量表示。

        Args:
            text: 要嵌入的文本
            **kwargs: Provider特定参数:
                - normalize: 是否归一化向量（某些Provider支持）

        Returns:
            List[float]: 文本的向量表示

        Raises:
            EmbeddingException: 嵌入失败时抛出

        Example:
            vector = await provider.embed_single("Hello World")
            # 返回: [0.1, 0.2, 0.3, ...] （维度取决于模型）
        """
        pass

    @abstractmethod
    async def embed_batch(self, texts: list[str], **kwargs) -> list[list[float]]:
        """
        批量文本嵌入

        将多个文本批量转换为向量表示。批量处理通常比逐个处理更高效。

        Args:
            texts: 要嵌入的文本列表
            **kwargs: Provider特定参数:
                - batch_size: 内部批处理大小（某些Provider支持）
                - normalize: 是否归一化向量（某些Provider支持）
                - show_progress: 是否显示进度条（某些Provider支持）

        Returns:
            List[List[float]]: 向量列表，与输入文本顺序一一对应

        Raises:
            EmbeddingException: 嵌入失败时抛出

        Example:
            vectors = await provider.embed_batch(
                ["Hello", "World", "Python"],
                batch_size=32
            )
            # 返回: [[0.1, ...], [0.2, ...], [0.3, ...]]
        """
        pass

    @property
    @abstractmethod
    def vector_dimension(self) -> int:
        """
        返回向量维度

        返回此Provider生成的向量维度数。
        需要在Provider初始化后可用。

        Returns:
            int: 向量维度（如384, 768, 1536等）

        Example:
            dim = provider.vector_dimension
            # 返回: 384
        """
        pass

    async def health_check(self) -> dict[str, Any]:
        """
        健康检查

        检查Provider是否健康可用。执行一个简单嵌入测试。

        Returns:
            Dict: 健康状态信息
            {
                "healthy": bool,
                "latency_ms": float,
                "message": str,
                "details": Dict
            }
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
            test_vector = await self.embed_single("health check")
            latency_ms = (time.time() - start_time) * 1000

            return {
                "healthy": True,
                "latency_ms": round(latency_ms, 2),
                "message": f"嵌入服务正常，向量维度: {len(test_vector)}",
                "details": {
                    "provider": self.config.provider,
                    "vector_dimension": len(test_vector),
                    "model": self.config.model_name
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

    async def is_available(self) -> bool:
        """
        检查Provider是否可用

        Returns:
            bool: 是否已初始化且可用
        """
        return self._initialized

    def _normalize_vector(self, vector: list[float]) -> list[float]:
        """
        归一化向量（L2归一化）

        将向量转换为单位长度，使余弦相似度等于点积。

        Args:
            vector: 输入向量

        Returns:
            List[float]: 归一化后的向量
        """
        import math

        # 计算L2范数
        norm = math.sqrt(sum(x * x for x in vector))

        if norm == 0:
            return vector

        # 归一化
        return [x / norm for x in vector]

    def _cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """
        计算两个向量的余弦相似度

        Args:
            vec1: 第一个向量
            vec2: 第二个向量

        Returns:
            float: 余弦相似度（-1到1）
        """
        import math

        if len(vec1) != len(vec2):
            raise ValueError("向量维度不匹配")

        dot_product = sum(a * b for a, b in zip(vec1, vec2, strict=False))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)
