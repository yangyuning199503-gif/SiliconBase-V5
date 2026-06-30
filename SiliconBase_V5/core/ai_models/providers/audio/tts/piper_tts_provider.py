"""
Piper TTS Provider

本地轻量级文本转语音引擎，基于Piper项目。
特点:
- 完全离线，无需网络
- 低延迟，实时合成
- 模型体积小 (约100MB)
- 支持多说话人

模型下载: https://github.com/rhasspy/piper/releases/tag/v1.2.0
"""

import io
import logging
import wave
from typing import Any

import numpy as np

from core.ai_models.config import ModelConfig
from core.ai_models.exceptions import ModelLoadException, SynthesisException
from core.ai_models.providers.audio.tts.base_tts_provider import BaseTTSProvider

logger = logging.getLogger(__name__)


class PiperTTSProvider(BaseTTSProvider):
    """
    Piper本地TTS适配器

    配置示例:
    {
        "provider": "piper",
        "model_name": "assets/models/piper/zh_CN-huayan-medium.onnx",
        "extra_params": {
            "config_path": "assets/models/piper/zh_CN-huayan-medium.onnx.json",
            "speaker_id": 0,
            "length_scale": 1.0  # 语速控制
        }
    }
    """

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self._voice = None
        self._model_path: str | None = None
        self._config_path: str | None = None
        self._speaker_id: int = 0
        self._length_scale: float = 1.0

        # 从配置读取参数
        self._speaker_id = config.extra_params.get('speaker_id', 0)
        self._length_scale = config.extra_params.get('length_scale', 1.0)
        self._sample_rate = 22050  # Piper默认采样率

    async def initialize(self) -> bool:
        """
        初始化Piper TTS模型

        Returns:
            bool: 初始化是否成功

        Raises:
            ModelLoadException: 模型加载失败时抛出
        """
        try:
            from piper import PiperVoice

            self._model_path = self.config.model_name
            if not self._model_path:
                error_msg = "未配置Piper模型路径"
                logger.error(f"[PiperTTSProvider] {error_msg}")
                raise ModelLoadException(error_msg)

            # 检查模型文件
            import os
            if not os.path.exists(self._model_path):
                error_msg = f"Piper模型文件不存在: {self._model_path}"
                logger.error(f"[PiperTTSProvider] {error_msg}")
                logger.info("[PiperTTSProvider] 请从 https://github.com/rhasspy/piper/releases 下载中文语音模型")
                logger.info("[PiperTTSProvider] 推荐模型: zh_CN-huayan-medium")
                raise ModelLoadException(error_msg)

            # 获取配置文件路径
            self._config_path = self.config.extra_params.get('config_path')
            if not self._config_path:
                # 尝试默认路径
                default_config = self._model_path + ".json"
                if os.path.exists(default_config):
                    self._config_path = default_config

            logger.info(f"[PiperTTSProvider] 正在加载模型: {self._model_path}")

            # 加载模型
            if self._config_path and os.path.exists(self._config_path):
                self._voice = PiperVoice.load(self._model_path, self._config_path)
            else:
                self._voice = PiperVoice.load(self._model_path)

            # 从配置文件中获取实际采样率
            if self._config_path and os.path.exists(self._config_path):
                import json

                import aiofiles
                async with aiofiles.open(self._config_path, encoding='utf-8') as f:
                    content = await f.read()
                    config_data = json.loads(content)
                    self._sample_rate = config_data.get('audio', {}).get('sample_rate', 22050)

            self._mark_initialized()
            logger.info(f"[PiperTTSProvider] 模型加载成功 (采样率: {self._sample_rate}Hz)")
            return True

        except ImportError as _exc:
            error_msg = "piper-tts库未安装，请执行: pip install piper-tts"
            logger.error(f"[PiperTTSProvider] {error_msg}")
            raise ModelLoadException(error_msg) from _exc
        except ModelLoadException:
            raise
        except Exception as e:
            error_msg = f"Piper模型加载失败: {e}"
            logger.error(f"[PiperTTSProvider] {error_msg}", exc_info=True)
            raise ModelLoadException(error_msg) from e

    async def synthesize(self, text: str, **kwargs) -> bytes:
        """
        合成语音

        Args:
            text: 要合成的文本
            **kwargs:
                - speaker_id: 说话人ID (覆盖配置)
                - speed: 语速倍率 (0.5-2.0, 默认1.0)
                - output_format: 输出格式 ('wav', 'pcm')

        Returns:
            WAV格式音频字节数据

        Raises:
            SynthesisException: 合成失败时抛出
        """
        if not self._voice:
            error_msg = "Provider未初始化"
            logger.error(f"[PiperTTSProvider] {error_msg}")
            raise SynthesisException(error_msg)

        if not text or not text.strip():
            logger.warning("[PiperTTSProvider] 合成文本为空")
            return b""

        try:
            # 获取参数
            speaker_id = kwargs.get('speaker_id', self._speaker_id)
            speed = kwargs.get('speed', 1.0)
            output_format = kwargs.get('output_format', 'wav')

            # 计算length_scale (语速控制)
            # length_scale < 1.0 语速加快, > 1.0 语速减慢
            length_scale = self._length_scale / speed

            logger.debug(f"[PiperTTSProvider] 开始合成: {text[:50]}... (speaker={speaker_id}, speed={speed})")

            # 使用Piper合成音频
            synthesize_args = {
                "speaker_id": speaker_id,
                "length_scale": length_scale
            }

            # 合成音频流
            audio_chunks = []
            for audio_result in self._voice.synthesize_stream_raw(text, **synthesize_args):
                if hasattr(audio_result, 'audio_int16_bytes'):
                    audio_chunks.append(audio_result.audio_int16_bytes)
                elif isinstance(audio_result, bytes):
                    audio_chunks.append(audio_result)
                elif hasattr(audio_result, 'cpu'):
                    # 处理PyTorch张量
                    audio_array = audio_result.cpu().numpy()
                    audio_array = np.squeeze(audio_array).astype(np.int16)
                    audio_chunks.append(audio_array.tobytes())

            if not audio_chunks:
                raise SynthesisException("合成未产生任何音频数据")

            # 合并音频数据
            audio_bytes = b"".join(audio_chunks)

            if output_format == 'pcm':
                return audio_bytes

            # 包装为WAV格式
            wav_data = self._pcm_to_wav(audio_bytes, self._sample_rate)

            logger.debug(f"[PiperTTSProvider] 合成成功: {len(wav_data)} bytes")
            return wav_data

        except SynthesisException:
            raise
        except Exception as e:
            error_msg = f"语音合成失败: {e}"
            logger.error(f"[PiperTTSProvider] {error_msg}", exc_info=True)
            raise SynthesisException(error_msg) from e

    async def synthesize_stream(self, text: str, **kwargs):
        """
        流式合成（生成器模式）

        Args:
            text: 要合成的文本
            **kwargs: 额外参数

        Yields:
            PCM音频数据片段
        """
        if not self._voice:
            raise SynthesisException("Provider未初始化")

        try:
            speaker_id = kwargs.get('speaker_id', self._speaker_id)
            speed = kwargs.get('speed', 1.0)
            length_scale = self._length_scale / speed

            synthesize_args = {
                "speaker_id": speaker_id,
                "length_scale": length_scale
            }

            # 流式生成音频
            for audio_result in self._voice.synthesize_stream_raw(text, **synthesize_args):
                if hasattr(audio_result, 'audio_int16_bytes'):
                    yield audio_result.audio_int16_bytes
                elif isinstance(audio_result, bytes):
                    yield audio_result
                elif hasattr(audio_result, 'cpu'):
                    audio_array = audio_result.cpu().numpy()
                    audio_array = np.squeeze(audio_array).astype(np.int16)
                    yield audio_array.tobytes()

        except Exception as e:
            error_msg = f"流式合成失败: {e}"
            logger.error(f"[PiperTTSProvider] {error_msg}", exc_info=True)
            raise SynthesisException(error_msg) from e

    def _pcm_to_wav(self, pcm_data: bytes, sample_rate: int) -> bytes:
        """
        将PCM数据包装为WAV格式

        Args:
            pcm_data: PCM音频数据
            sample_rate: 采样率

        Returns:
            WAV格式字节数据
        """
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)  # 单声道
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_data)
        return wav_buffer.getvalue()

    async def is_available(self) -> bool:
        """检查Provider是否可用"""
        return self._voice is not None

    async def cleanup(self):
        """清理资源"""
        logger.info("[PiperTTSProvider] 清理资源...")
        self._voice = None
        import gc
        gc.collect()
        await super().cleanup()

    async def health_check(self) -> dict[str, Any]:
        """健康检查"""
        base_check = await super().health_check()
        base_check.update({
            "model_path": self._model_path,
            "config_path": self._config_path,
            "speaker_id": self._speaker_id,
            "sample_rate": self._sample_rate
        })
        return base_check

    def get_speakers(self) -> dict[int, str]:
        """
        获取可用的说话人列表

        Returns:
            说话人ID到名称的映射字典
        """
        if not self._config_path:
            return {0: "default"}

        try:
            import json
            with open(self._config_path, encoding='utf-8') as f:
                config = json.load(f)
                speakers = config.get('speaker_id_map', {})
                if not speakers:
                    return {0: "default"}
                return {int(k): v for k, v in speakers.items()}
        except Exception as e:
            logger.warning(f"[PiperTTSProvider] 读取说话人配置失败: {e}")
            return {0: "default"}
