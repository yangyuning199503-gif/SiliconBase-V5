"""
Sentence Transformers Embedding Provider

基于Hugging Face Sentence Transformers的本地向量模型Provider
复用core/vector_memory.py中的EmbeddingModelManager逻辑

支持的模型:
- all-MiniLM-L6-v2 (默认, 384维)
- all-MiniLM-L12-v2 (384维)
- all-mpnet-base-v2 (768维)
- paraphrase-multilingual-MiniLM-L12-v2 (多语言)
- 以及其他sentence-transformers兼容模型

参考: https://www.sbert.net/
"""

import logging
import os
from typing import Any

from core.ai_models.exceptions import EmbeddingException, ModelLoadException
from core.ai_models.providers.embedding.base_embedding_provider import BaseEmbeddingProvider

logger = logging.getLogger(__name__)


class SentenceTransformerProvider(BaseEmbeddingProvider):
    """
    Sentence Transformers本地向量模型Provider

    使用Hugging Face的sentence-transformers库在本地运行向量模型。
    无需API密钥，完全本地运行，适合隐私敏感场景。

    特性:
    - 自动模型下载和缓存
    - GPU加速支持（CUDA/MPS）
    - 高效的批量处理
    - 自动归一化选项

    配置示例:
        config = ModelConfig(
            provider="sentence_transformer",
            model_name="all-MiniLM-L6-v2",
            extra_params={
                "device": "cuda",  # 或 "cpu", "mps"
                "trust_remote_code": False
            }
        )

    环境变量:
        SENTENCE_TRANSFORMERS_HOME: 模型缓存目录
        TRANSFORMERS_CACHE: Transformers缓存目录
    """

    # 默认模型配置
    DEFAULT_MODEL = "all-MiniLM-L6-v2"
    DEFAULT_DIMENSION = 384  # all-MiniLM-L6-v2的维度

    def __init__(self, config):
        """
        初始化Sentence Transformer Provider

        Args:
            config: ModelConfig配置对象
                - model_name: 模型名称或路径
                - extra_params.device: 运行设备 (cpu/cuda/mps)
        """
        super().__init__(config)
        self._model = None
        self._vector_dim = None

        # 设置默认能力
        self._capabilities.supports_batch = True

        # 设置缓存目录环境变量
        self._setup_cache_dir()

        logger.info(f"[{self.__class__.__name__}] Provider实例创建")

    def _setup_cache_dir(self):
        """设置模型缓存目录"""
        # 优先从配置读取
        cache_dir = self.config.extra_params.get("cache_dir")

        if not cache_dir:
            # 使用项目默认路径
            from pathlib import Path
            project_root = Path(__file__).parent.parent.parent.parent.parent
            cache_dir = project_root / 'checkpoints' / 'hf_cache'

        cache_dir = str(cache_dir)

        # 设置环境变量
        # 注意：TRANSFORMERS_CACHE 已在Transformers v5中废弃，使用HF_HOME代替
        try:
            # 设置Sentence Transformers缓存（向后兼容）
            os.environ.setdefault('SENTENCE_TRANSFORMERS_HOME', cache_dir)

            # 设置Hugging Face主缓存（推荐方式）
            os.environ.setdefault('HF_HOME', cache_dir)

            # 如果用户设置了旧的TRANSFORMERS_CACHE，发出警告
            if 'TRANSFORMERS_CACHE' in os.environ:
                old_cache = os.environ['TRANSFORMERS_CACHE']
                logger.warning(f"[{self.__class__.__name__}] 检测到已废弃的TRANSFORMERS_CACHE={old_cache}，请改用HF_HOME")
                # 确保HF_HOME也被设置
                if 'HF_HOME' not in os.environ:
                    os.environ['HF_HOME'] = old_cache
                    logger.info(f"[{self.__class__.__name__}] 已迁移到HF_HOME={old_cache}")

            logger.debug(f"[{self.__class__.__name__}] 模型缓存目录: {cache_dir}")

        except OSError as e:
            logger.error(f"[{self.__class__.__name__}] 设置环境变量失败: {e}")
            raise RuntimeError(f"设置Hugging Face环境变量失败: {e}") from e

    async def initialize(self) -> bool:
        """
        异步初始化Provider

        加载Sentence Transformer模型到内存。
        首次加载可能需要下载模型（如果本地不存在）。

        Returns:
            bool: 初始化是否成功

        Raises:
            ModelLoadException: 模型加载失败时抛出
        """
        try:
            # 延迟导入，避免模块加载时失败
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as _exc:
                raise ModelLoadException(
                    "sentence-transformers库未安装。请运行: pip install sentence-transformers",
                    provider=self.config.provider
                ) from _exc

            # 获取模型名称
            model_name = self.config.model_name or self.DEFAULT_MODEL

            # 解析本地 HF 缓存快照路径
            from pathlib import Path
            project_root = Path(__file__).parent.parent.parent.parent.parent
            cache_dir = project_root / "checkpoints" / "hf_cache"
            local_root = cache_dir / f"models--{model_name.replace('/', '--')}"
            snapshot_dir = None
            if local_root.exists():
                snapshots = local_root / "snapshots"
                if snapshots.exists():
                    for child in snapshots.iterdir():
                        if child.is_dir():
                            snapshot_dir = child
                            break

            if snapshot_dir is None or not snapshot_dir.exists():
                raise FileNotFoundError(f"本地模型未找到: {local_root}，请确认模型已下载到本地缓存")

            model_path = str(snapshot_dir).replace('\\', '/')

            # 获取设备配置
            device = self.config.extra_params.get("device")
            if not device:
                # 自动检测最佳设备
                import torch
                if torch.cuda.is_available():
                    device = "cuda"
                elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                    device = "mps"
                else:
                    device = "cpu"

            logger.info(f"[{self.__class__.__name__}] 加载本地模型: {model_path} (设备: {device})")

            # 加载模型
            trust_remote_code = self.config.extra_params.get("trust_remote_code", False)
            self._model = SentenceTransformer(
                model_path,
                device=device,
                trust_remote_code=trust_remote_code,
                local_files_only=True
            )

            # 获取向量维度
            self._vector_dim = self._model.get_sentence_embedding_dimension()

            logger.info(
                f"[{self.__class__.__name__}] 模型加载成功, "
                f"维度: {self._vector_dim}, 设备: {device}"
            )

            self._mark_initialized()
            return True

        except ModelLoadException:
            raise
        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] 模型加载失败: {e}")
            raise ModelLoadException(
                f"Sentence Transformer模型加载失败: {e}",
                model_path=self.config.model_name,
                provider=self.config.provider
            ) from e

    async def embed_single(self, text: str, **kwargs) -> list[float]:
        """
        单文本嵌入

        Args:
            text: 要嵌入的文本
            **kwargs:
                - normalize: 是否归一化（默认False）

        Returns:
            List[float]: 文本的向量表示

        Raises:
            EmbeddingException: 嵌入失败时抛出
        """
        if not self._model:
            raise EmbeddingException("Provider未初始化，请先调用initialize()", error_code="PROVIDER_NOT_INITIALIZED")

        try:
            # 处理空文本
            if not text or not text.strip():
                logger.warning("[{self.__class__.__name__}] 收到空文本，返回零向量")
                return [0.0] * (self._vector_dim or self.DEFAULT_DIMENSION)

            # 执行嵌入
            embedding = self._model.encode(
                text,
                convert_to_numpy=True,
                show_progress_bar=False
            )

            # 转换为Python列表
            vector = embedding.tolist()

            # 可选归一化
            if kwargs.get("normalize", False):
                vector = self._normalize_vector(vector)

            return vector

        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] 单文本嵌入失败: {e}")
            raise EmbeddingException(
                f"文本嵌入失败: {e}",
                error_code="EMBEDDING_ERROR",
                details={"text_length": len(text) if text else 0}
            ) from e

    async def embed_batch(self, texts: list[str], **kwargs) -> list[list[float]]:
        """
        批量文本嵌入

        Args:
            texts: 要嵌入的文本列表
            **kwargs:
                - batch_size: 批处理大小（默认32）
                - normalize: 是否归一化（默认False）
                - show_progress: 是否显示进度条（默认False）

        Returns:
            List[List[float]]: 向量列表，与输入顺序一致

        Raises:
            EmbeddingException: 嵌入失败时抛出
        """
        if not self._model:
            raise EmbeddingException("Provider未初始化，请先调用initialize()", error_code="PROVIDER_NOT_INITIALIZED")

        try:
            # 处理空列表
            if not texts:
                return []

            # 处理空字符串
            processed_texts = []
            empty_indices = []
            for i, text in enumerate(texts):
                if not text or not text.strip():
                    processed_texts.append("")  # 保持位置
                    empty_indices.append(i)
                else:
                    processed_texts.append(text)

            # 执行批量嵌入
            batch_size = kwargs.get("batch_size", 32)
            show_progress = kwargs.get("show_progress", False)

            embeddings = self._model.encode(
                processed_texts,
                batch_size=batch_size,
                convert_to_numpy=True,
                show_progress_bar=show_progress
            )

            # 转换为列表
            vectors = embeddings.tolist()

            # 填充空文本的零向量
            for idx in empty_indices:
                vectors[idx] = [0.0] * (self._vector_dim or self.DEFAULT_DIMENSION)

            # 可选归一化
            if kwargs.get("normalize", False):
                vectors = [self._normalize_vector(v) for v in vectors]

            logger.debug(f"[{self.__class__.__name__}] 批量嵌入完成: {len(texts)} 条文本")
            return vectors

        except Exception as e:
            logger.error(f"[{self.__class__.__name__}] 批量嵌入失败: {e}")
            raise EmbeddingException(
                f"批量嵌入失败: {e}",
                error_code="BATCH_EMBEDDING_ERROR",
                details={"batch_size": len(texts) if texts else 0}
            ) from e

    @property
    def vector_dimension(self) -> int:
        """
        返回向量维度

        Returns:
            int: 向量维度（如384, 768等）
        """
        return self._vector_dim or self.DEFAULT_DIMENSION

    def get_model_info(self) -> dict[str, Any]:
        """
        获取模型信息

        Returns:
            Dict: 模型详细信息
        """
        info = {
            "model_name": self.config.model_name or self.DEFAULT_MODEL,
            "vector_dimension": self.vector_dimension,
            "initialized": self._initialized,
            "provider": self.config.provider
        }

        if self._model:
            info["max_seq_length"] = getattr(self._model, 'max_seq_length', 'unknown')
            info["device"] = str(self._model.device) if hasattr(self._model, 'device') else 'unknown'

        return info
