"""
Whisper ASR Provider

支持OpenAI Whisper API和本地Whisper模型。
- API模式: 使用OpenAI API，需要api_key
- 本地模式: 使用faster-whisper等本地库

安装依赖:
- API模式: pip install openai
- 本地模式: pip install faster-whisper
"""

import asyncio
import io
import logging
import tempfile
import wave
from pathlib import Path
from typing import Any

from core.ai_models.config import ModelConfig
from core.ai_models.exceptions import ModelLoadException, RecognitionException
from core.ai_models.providers.audio.asr.base_asr_provider import BaseASRProvider

logger = logging.getLogger(__name__)


class WhisperASRProvider(BaseASRProvider):
    """
    Whisper语音识别适配器

    特点:
    - 支持云端API和本地模型
    - 多语言支持
    - 高精度识别
    - 支持翻译功能

    配置示例:
    - API模式: provider="whisper", model_name="whisper-1", api_key="sk-..."
    - 本地模式: provider="whisper", model_name="base", base_url="local"
    """

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self._client = None
        self._local_model = None
        self._is_local = False
        self._sample_rate = 16000

        # 更新能力标志
        self._capabilities.supports_batch = True
        self._capabilities.streaming = False

    async def initialize(self) -> bool:
        """
        初始化Whisper

        根据配置决定使用API模式还是本地模式

        Returns:
            bool: 初始化是否成功
        """
        try:
            # 判断是本地模式还是API模式
            base_url = self.config.base_url

            if base_url and base_url.lower() == "local":
                # 本地模式
                self._is_local = True
                await self._init_local_model()
            else:
                # API模式
                self._is_local = False
                await self._init_api_client()

            self._mark_initialized()
            logger.info(f"[WhisperASRProvider] 初始化成功 (模式: {'本地' if self._is_local else 'API'})")
            return True

        except Exception as e:
            error_msg = f"Whisper初始化失败: {e}"
            logger.error(f"[WhisperASRProvider] {error_msg}", exc_info=True)
            raise ModelLoadException(error_msg) from e

    async def _init_api_client(self):
        """初始化OpenAI API客户端"""
        try:
            from openai import AsyncOpenAI

            api_key = self.config.api_key
            if not api_key:
                raise ModelLoadException("API模式需要提供api_key")

            base_url = self.config.base_url or "https://api.openai.com/v1"

            self._client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=self.config.timeout
            )

            logger.info("[WhisperASRProvider] OpenAI API客户端已创建")

        except ImportError as _exc:
            raise ModelLoadException("openai库未安装，请执行: pip install openai") from _exc

    async def _init_local_model(self):
        """初始化本地Whisper模型"""
        try:
            from faster_whisper import WhisperModel

            model_size = self.config.model_name or "base"

            # 检查是否有CUDA
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            compute_type = "float16" if device == "cuda" else "int8"

            logger.info(f"[WhisperASRProvider] 加载本地模型: {model_size}, 设备: {device}")

            self._local_model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type
            )

            logger.info("[WhisperASRProvider] 本地模型加载成功")

        except ImportError as _exc:
            raise ModelLoadException("faster-whisper库未安装，请执行: pip install faster-whisper") from _exc

    async def recognize(self, audio_data: bytes, **kwargs) -> str:
        """
        识别音频数据

        Args:
            audio_data: PCM音频字节数据 (16kHz, 16bit, mono) 或 WAV数据
            **kwargs:
                - language: 语言代码 (如 'zh', 'en', 'auto')
                - translate: 是否翻译成英文 (默认False)

        Returns:
            识别到的文本
        """
        if self._is_local:
            return await self._recognize_local(audio_data, **kwargs)
        else:
            return await self._recognize_api(audio_data, **kwargs)

    async def _recognize_api(self, audio_data: bytes, **kwargs) -> str:
        """使用API识别"""
        if not self._client:
            raise RecognitionException("API客户端未初始化")

        try:
            # 将PCM数据包装为WAV格式
            wav_data = self._pcm_to_wav(audio_data, self._sample_rate)

            # 创建临时文件
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(wav_data)
                tmp_path = tmp.name

            try:
                # 调用API
                language = kwargs.get('language', 'zh')
                import io

                import aiofiles
                async with aiofiles.open(tmp_path, "rb") as af:
                    audio_bytes = await af.read()
                response = await self._client.audio.transcriptions.create(
                    model=self.config.model_name or "whisper-1",
                    file=io.BytesIO(audio_bytes),
                    language=None if language == "auto" else language
                )

                text = response.text.strip()
                logger.debug(f"[WhisperASRProvider] API识别成功: {text[:50]}...")
                return text

            finally:
                # 清理临时文件
                await asyncio.to_thread(Path(tmp_path).unlink, True)

        except Exception as e:
            error_msg = f"API识别失败: {e}"
            logger.error(f"[WhisperASRProvider] {error_msg}", exc_info=True)
            raise RecognitionException(error_msg) from e

    async def _recognize_local(self, audio_data: bytes, **kwargs) -> str:
        """使用本地模型识别"""
        if not self._local_model:
            raise RecognitionException("本地模型未初始化")

        try:
            # 将PCM数据包装为WAV格式
            wav_data = self._pcm_to_wav(audio_data, self._sample_rate)

            # 创建临时文件
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(wav_data)
                tmp_path = tmp.name

            try:
                # 调用本地模型
                language = kwargs.get('language', 'zh')

                segments, info = self._local_model.transcribe(
                    tmp_path,
                    language=None if language == "auto" else language,
                    beam_size=5
                )

                # 合并所有片段
                text_parts = []
                for segment in segments:
                    text_parts.append(segment.text)

                text = " ".join(text_parts).strip()
                logger.debug(f"[WhisperASRProvider] 本地识别成功: {text[:50]}...")
                return text

            finally:
                # 清理临时文件
                await asyncio.to_thread(Path(tmp_path).unlink, missing_ok=True)

        except Exception as e:
            error_msg = f"本地识别失败: {e}"
            logger.error(f"[WhisperASRProvider] {error_msg}", exc_info=True)
            raise RecognitionException(error_msg) from e

    def _pcm_to_wav(self, pcm_data: bytes, sample_rate: int) -> bytes:
        """
        将PCM数据转换为WAV格式

        Args:
            pcm_data: PCM音频数据
            sample_rate: 采样率

        Returns:
            WAV格式字节数据
        """
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_data)
        return wav_buffer.getvalue()

    async def is_available(self) -> bool:
        """检查Provider是否可用"""
        if self._is_local:
            return self._local_model is not None
        else:
            return self._client is not None

    async def cleanup(self):
        """清理资源"""
        logger.info("[WhisperASRProvider] 清理资源...")
        self._client = None
        self._local_model = None
        await super().cleanup()

    async def health_check(self) -> dict[str, Any]:
        """健康检查"""
        base_check = await super().health_check()
        base_check.update({
            "mode": "local" if self._is_local else "api",
            "model": self.config.model_name,
            "sample_rate": self._sample_rate
        })
        return base_check
