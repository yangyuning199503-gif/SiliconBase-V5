"""
音频Provider基类模块

定义音频相关Provider的抽象基类，包括ASR、TTS和语音增强。
"""

import logging
from abc import abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from core.ai_models.base import BaseModelProvider, ModelType
from core.ai_models.config import ModelConfig

logger = logging.getLogger(__name__)


class BaseAudioProvider(BaseModelProvider):
    """
    音频Provider基类

    所有音频相关Provider的抽象基类，提供通用的音频处理功能。
    """

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        # 音频模型默认能力
        self._capabilities.audio_input = True
        self._capabilities.audio_output = True


class BaseASRProvider(BaseAudioProvider):
    """
    语音识别(ASR) Provider基类

    所有语音识别Provider必须继承此类，实现recognize方法。

    支持的音频格式:
    - PCM 16-bit, 16kHz, 单声道 (默认)
    - 其他格式可通过extra_params指定
    """

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self._capabilities.audio_input = True
        self._capabilities.audio_output = False
        self._capabilities.supports_batch = False
        self._sample_rate = 16000  # 默认采样率

    @property
    def model_type(self) -> ModelType:
        return ModelType.AUDIO_ASR

    @property
    def sample_rate(self) -> int:
        """获取期望的音频采样率"""
        return self._sample_rate

    async def invoke(self, input_data: bytes, **kwargs) -> str:
        """
        ASR调用入口

        Args:
            input_data: PCM音频数据 (16kHz, 16bit, mono)
            **kwargs:
                - language: 识别语言代码 (如 'zh', 'en')
                - partial: 是否返回部分识别结果

        Returns:
            识别文本
        """
        return await self.recognize(input_data, **kwargs)

    @abstractmethod
    async def recognize(self, audio_data: bytes, **kwargs) -> str:
        """
        识别音频数据

        Args:
            audio_data: PCM音频字节数据
            **kwargs: 额外参数

        Returns:
            识别到的文本

        Raises:
            RecognitionException: 识别失败时抛出
        """
        pass

    async def recognize_stream(self, audio_stream: AsyncIterator[bytes], **kwargs) -> AsyncIterator[str]:
        """
        流式识别（可选实现）

        Args:
            audio_stream: 音频数据流
            **kwargs: 额外参数

        Yields:
            识别文本片段

        Raises:
            NotImplementedError: 如果Provider不支持流式识别
        """
        raise NotImplementedError("该Provider不支持流式识别")

    async def health_check(self) -> dict[str, Any]:
        """
        健康检查

        Returns:
            健康状态字典
        """
        available = await self.is_available()
        return {
            "healthy": available,
            "provider": self.config.provider,
            "model": self.config.model_name,
            "type": "asr",
            "sample_rate": self._sample_rate,
            "capabilities": {
                "streaming": self._capabilities.streaming,
                "batch": self._capabilities.supports_batch
            }
        }


class BaseTTSProvider(BaseAudioProvider):
    """
    语音合成(TTS) Provider基类

    所有语音合成Provider必须继承此类，实现synthesize方法。

    输出音频格式:
    - PCM 16-bit, 默认22050Hz, 单声道 (可通过extra_params指定)
    """

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self._capabilities.audio_input = False
        self._capabilities.audio_output = True
        self._capabilities.streaming = True
        self._sample_rate = 22050  # 默认采样率
        self._speaker_id = 0  # 默认说话人ID

    @property
    def model_type(self) -> ModelType:
        return ModelType.AUDIO_TTS

    @property
    def sample_rate(self) -> int:
        """获取输出的音频采样率"""
        return self._sample_rate

    async def invoke(self, input_data: str, **kwargs) -> bytes:
        """
        TTS调用入口

        Args:
            input_data: 要合成的文本
            **kwargs:
                - speaker_id: 说话人ID
                - speed: 语速倍率 (0.5-2.0)
                - reference_audio: 参考音频路径（用于声音克隆）
                - output_format: 输出格式 ('pcm', 'wav')

        Returns:
            音频字节数据 (默认WAV格式)
        """
        return await self.synthesize(input_data, **kwargs)

    @abstractmethod
    async def synthesize(self, text: str, **kwargs) -> bytes:
        """
        合成语音

        Args:
            text: 要合成的文本
            **kwargs:
                - speaker_id: 说话人ID
                - speed: 语速倍率
                - reference_audio: 参考音频路径

        Returns:
            音频字节数据 (WAV格式)

        Raises:
            SynthesisException: 合成失败时抛出
        """
        pass

    async def synthesize_stream(self, text_stream: AsyncIterator[str], **kwargs) -> AsyncIterator[bytes]:
        """
        流式合成（可选实现）

        Args:
            text_stream: 文本流
            **kwargs: 额外参数

        Yields:
            音频数据片段

        Raises:
            NotImplementedError: 如果Provider不支持流式合成
        """
        raise NotImplementedError("该Provider不支持流式合成")

    async def health_check(self) -> dict[str, Any]:
        """
        健康检查

        Returns:
            健康状态字典
        """
        available = await self.is_available()
        return {
            "healthy": available,
            "provider": self.config.provider,
            "model": self.config.model_name,
            "type": "tts",
            "sample_rate": self._sample_rate,
            "capabilities": {
                "streaming": self._capabilities.streaming,
                "batch": self._capabilities.supports_batch
            }
        }


class BaseEnhanceProvider(BaseAudioProvider):
    """
    语音增强/克隆 Provider基类

    用于语音增强、降噪、声音克隆等高级音频处理。
    占位实现，为后续功能预留接口。
    """

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self._capabilities.audio_input = True
        self._capabilities.audio_output = True

    @property
    def model_type(self) -> ModelType:
        return ModelType.AUDIO_ENHANCE

    async def invoke(self, input_data: bytes, **kwargs) -> bytes:
        """
        语音增强调用入口

        Args:
            input_data: 输入音频数据
            **kwargs:
                - operation: 操作类型 ('enhance', 'clone', 'denoise')
                - reference_audio: 参考音频（用于克隆）

        Returns:
            处理后的音频数据
        """
        operation = kwargs.get('operation', 'enhance')
        if operation == 'enhance':
            return await self.enhance(input_data, **kwargs)
        elif operation == 'clone':
            return await self.clone(input_data, **kwargs)
        elif operation == 'denoise':
            return await self.denoise(input_data, **kwargs)
        else:
            raise ValueError(f"不支持的操作类型: {operation}")

    async def enhance(self, audio_data: bytes, **kwargs) -> bytes:
        """
        语音增强（可选实现）

        Args:
            audio_data: 输入音频数据
            **kwargs: 额外参数

        Returns:
            增强后的音频数据
        """
        raise NotImplementedError("该Provider不支持语音增强")

    async def clone(self, audio_data: bytes, **kwargs) -> bytes:
        """
        声音克隆（可选实现）

        Args:
            audio_data: 输入音频数据
            **kwargs:
                - reference_audio: 参考音频数据
                - target_speaker: 目标说话人特征

        Returns:
            克隆后的音频数据
        """
        raise NotImplementedError("该Provider不支持声音克隆")

    async def denoise(self, audio_data: bytes, **kwargs) -> bytes:
        """
        语音降噪（可选实现）

        Args:
            audio_data: 输入音频数据
            **kwargs: 额外参数

        Returns:
            降噪后的音频数据
        """
        raise NotImplementedError("该Provider不支持语音降噪")

    async def health_check(self) -> dict[str, Any]:
        """
        健康检查

        Returns:
            健康状态字典
        """
        available = await self.is_available()
        return {
            "healthy": available,
            "provider": self.config.provider,
            "model": self.config.model_name,
            "type": "enhance",
            "capabilities": {
                "streaming": self._capabilities.streaming,
                "batch": self._capabilities.supports_batch
            }
        }
