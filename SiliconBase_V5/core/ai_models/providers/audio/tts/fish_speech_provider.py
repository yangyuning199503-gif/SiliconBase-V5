"""
FishSpeech TTS Provider

高保真TTS引擎，支持声音克隆和零样本语音合成。
特点:
- 高保真音质
- 支持零样本声音克隆
- 多语言支持
- 开源可本地部署

项目地址: https://github.com/fishaudio/fish-speech
安装依赖: pip install fish-speech (或从源码安装)
"""

import io
import logging
import wave
from pathlib import Path
from typing import Any

import numpy as np

from core.ai_models.config import ModelConfig
from core.ai_models.exceptions import ModelLoadException, SynthesisException
from core.ai_models.providers.audio.tts.base_tts_provider import BaseTTSProvider

logger = logging.getLogger(__name__)


class FishSpeechProvider(BaseTTSProvider):
    """
    FishSpeech高保真TTS适配器

    配置示例:
    {
        "provider": "fishspeech",
        "model_name": "fish-speech-1.4",
        "base_url": "http://localhost:8080",  # 本地API地址
        "extra_params": {
            "reference_audio": "path/to/reference.wav",  # 参考音频（声音克隆）
            "reference_text": "参考音频的文本内容",
            "temperature": 0.7,
            "top_p": 0.7,
            "top_k": 20
        }
    }

    支持模式:
    1. API模式: 连接本地或远程FishSpeech服务
    2. 本地模式: 直接加载模型 (需要更多GPU内存)
    """

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self._client = None
        self._local_model = None
        self._is_local = False
        self._sample_rate = 44100  # FishSpeech默认44.1kHz

        # 推理参数
        self._temperature = config.extra_params.get('temperature', 0.7)
        self._top_p = config.extra_params.get('top_p', 0.7)
        self._top_k = config.extra_params.get('top_k', 20)
        self._reference_audio = config.extra_params.get('reference_audio')
        self._reference_text = config.extra_params.get('reference_text', '')

        # 检查是本地模式还是API模式
        if not config.base_url:
            self._is_local = True

    async def initialize(self) -> bool:
        """
        初始化FishSpeech

        Returns:
            bool: 初始化是否成功
        """
        try:
            if self._is_local:
                await self._init_local_model()
            else:
                await self._init_api_client()

            self._mark_initialized()
            logger.info(f"[FishSpeechProvider] 初始化成功 (模式: {'本地' if self._is_local else 'API'})")
            return True

        except Exception as e:
            error_msg = f"FishSpeech初始化失败: {e}"
            logger.error(f"[FishSpeechProvider] {error_msg}", exc_info=True)
            raise ModelLoadException(error_msg) from e

    async def _init_api_client(self):
        """初始化API客户端"""
        import httpx

        base_url = self.config.base_url or "http://localhost:8080"

        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=self.config.timeout
        )

        # 测试连接
        try:
            response = await self._client.get("/v1/health")
            if response.status_code != 200:
                raise ModelLoadException(f"FishSpeech服务不可用: {response.status_code}")
        except Exception as e:
            raise ModelLoadException(f"无法连接到FishSpeech服务: {e}") from e

        logger.info(f"[FishSpeechProvider] API客户端已连接到 {base_url}")

    async def _init_local_model(self):
        """初始化本地模型"""
        try:
            # 尝试导入FishSpeech本地库
            from fish_speech.inference_engine import TTSInferenceEngine

            model_path = self.config.model_name
            if not model_path or not Path(model_path).exists():
                raise ModelLoadException(f"模型路径不存在: {model_path}")

            logger.info(f"[FishSpeechProvider] 加载本地模型: {model_path}")

            # 初始化推理引擎
            self._local_model = TTSInferenceEngine(
                checkpoint_path=model_path,
                device="cuda" if self._check_cuda() else "cpu"
            )

            logger.info("[FishSpeechProvider] 本地模型加载成功")

        except ImportError as _exc:
            raise ModelLoadException(
                "fish-speech库未安装。请从源码安装: "
                "pip install git+https://github.com/fishaudio/fish-speech.git"
            ) from _exc

    def _check_cuda(self) -> bool:
        """检查是否有CUDA可用"""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False

    async def synthesize(self, text: str, **kwargs) -> bytes:
        """
        合成语音

        Args:
            text: 要合成的文本
            **kwargs:
                - reference_audio: 参考音频路径（覆盖配置）
                - reference_text: 参考文本（覆盖配置）
                - temperature: 采样温度
                - top_p: Top-p采样
                - top_k: Top-k采样
                - output_format: 输出格式 ('wav', 'pcm')

        Returns:
            WAV格式音频字节数据
        """
        if not text or not text.strip():
            logger.warning("[FishSpeechProvider] 合成文本为空")
            return b""

        try:
            if self._is_local:
                return await self._synthesize_local(text, **kwargs)
            else:
                return await self._synthesize_api(text, **kwargs)

        except SynthesisException:
            raise
        except Exception as e:
            error_msg = f"语音合成失败: {e}"
            logger.error(f"[FishSpeechProvider] {error_msg}", exc_info=True)
            raise SynthesisException(error_msg) from e

    async def _synthesize_api(self, text: str, **kwargs) -> bytes:
        """使用API合成"""

        # 获取参数
        reference_audio = kwargs.get('reference_audio', self._reference_audio)
        reference_text = kwargs.get('reference_text', self._reference_text)
        temperature = kwargs.get('temperature', self._temperature)
        top_p = kwargs.get('top_p', self._top_p)
        top_k = kwargs.get('top_k', self._top_k)
        output_format = kwargs.get('output_format', 'wav')

        logger.debug(f"[FishSpeechProvider] API合成: {text[:50]}...")

        # 构建请求
        request_data = {
            "text": text,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
        }

        files = {}

        # 如果有参考音频，添加它
        if reference_audio and Path(reference_audio).exists():
            import aiofiles
            async with aiofiles.open(reference_audio, 'rb') as af:
                files['reference_audio'] = ('reference.wav', await af.read())
            if reference_text:
                request_data['reference_text'] = reference_text

        try:
            response = await self._client.post(
                "/v1/tts",
                data=request_data,
                files=files if files else None,
                timeout=120  # TTS可能需要较长时间
            )

            if response.status_code != 200:
                raise SynthesisException(f"API请求失败: {response.status_code} - {response.text}")

            audio_data = response.content

            # FishSpeech API直接返回WAV格式
            if output_format == 'wav':
                return audio_data
            elif output_format == 'pcm':
                # 跳过WAV头
                return audio_data[44:] if audio_data.startswith(b'RIFF') else audio_data

            return audio_data

        finally:
            # 关闭文件（仅关闭真正的文件对象）
            for f in files.values():
                if hasattr(f, 'close'):
                    f.close()

    async def _synthesize_local(self, text: str, **kwargs) -> bytes:
        """使用本地模型合成"""
        if not self._local_model:
            raise SynthesisException("本地模型未初始化")

        # 获取参数
        reference_audio = kwargs.get('reference_audio', self._reference_audio)
        reference_text = kwargs.get('reference_text', self._reference_text)
        temperature = kwargs.get('temperature', self._temperature)
        top_p = kwargs.get('top_p', self._top_p)
        top_k = kwargs.get('top_k', self._top_k)
        output_format = kwargs.get('output_format', 'wav')

        logger.debug(f"[FishSpeechProvider] 本地合成: {text[:50]}...")

        # 加载参考音频（如果有）
        ref_audio = None
        if reference_audio and Path(reference_audio).exists():
            import soundfile as sf
            ref_audio, sr = sf.read(reference_audio)

        # 调用模型推理
        audio_data = self._local_model.inference(
            text=text,
            reference_audio=ref_audio,
            reference_text=reference_text if ref_audio is not None else None,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k
        )

        # 转换为字节
        pcm_data = (audio_data * 32767).astype(np.int16).tobytes() if isinstance(audio_data, np.ndarray) else audio_data

        if output_format == 'pcm':
            return pcm_data

        # 包装为WAV
        wav_data = self._pcm_to_wav(pcm_data, self._sample_rate)
        return wav_data

    def _pcm_to_wav(self, pcm_data: bytes, sample_rate: int) -> bytes:
        """将PCM数据包装为WAV格式"""
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_data)
        return wav_buffer.getvalue()

    async def clone_voice(self, reference_audio: str, reference_text: str, target_text: str, **kwargs) -> bytes:
        """
        声音克隆合成

        Args:
            reference_audio: 参考音频文件路径
            reference_text: 参考音频对应的文本
            target_text: 要合成的目标文本
            **kwargs: 其他合成参数

        Returns:
            WAV格式音频字节数据
        """
        if not Path(reference_audio).exists():
            raise SynthesisException(f"参考音频不存在: {reference_audio}")

        # 更新参数
        kwargs['reference_audio'] = reference_audio
        kwargs['reference_text'] = reference_text

        return await self.synthesize(target_text, **kwargs)

    async def is_available(self) -> bool:
        """检查Provider是否可用"""
        if self._is_local:
            return self._local_model is not None
        else:
            if not self._client:
                return False
            try:
                response = self._client.get("/v1/health")
                return response.status_code == 200
            except Exception as e:
                logger.debug(f"[FishSpeechProvider] 健康检查异常: {e}")
                return False

    async def cleanup(self):
        """清理资源"""
        logger.info("[FishSpeechProvider] 清理资源...")
        if self._client:
            await self._client.aclose()
            self._client = None
        self._local_model = None
        await super().cleanup()

    async def health_check(self) -> dict[str, Any]:
        """健康检查"""
        base_check = await super().health_check()
        base_check.update({
            "mode": "local" if self._is_local else "api",
            "model": self.config.model_name,
            "sample_rate": self._sample_rate,
            "temperature": self._temperature,
            "top_p": self._top_p,
            "top_k": self._top_k,
            "has_reference": self._reference_audio is not None
        })
        return base_check
