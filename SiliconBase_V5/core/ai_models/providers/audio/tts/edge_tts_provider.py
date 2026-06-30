"""
Edge TTS Provider

微软Edge浏览器在线TTS服务，无需API Key。
特点:
- 免费使用
- 多种语音选择
- 自然流畅的中文语音
- 需要网络连接

安装依赖: pip install edge-tts
"""

import io
import logging
import wave
from typing import Any

from core.ai_models.config import ModelConfig
from core.ai_models.exceptions import ModelLoadException, SynthesisException
from core.ai_models.providers.audio.tts.base_tts_provider import BaseTTSProvider

logger = logging.getLogger(__name__)


class EdgeTTSProvider(BaseTTSProvider):
    """
    微软Edge TTS适配器

    配置示例:
    {
        "provider": "edge",
        "model_name": "zh-CN-XiaoxiaoNeural",
        "extra_params": {
            "rate": "+0%",      # 语速调整
            "volume": "+0%",    # 音量调整
            "pitch": "+0Hz"     # 音调调整
        }
    }

    可用语音:
    - zh-CN-XiaoxiaoNeural: 晓晓 (女声，推荐)
    - zh-CN-YunxiNeural: 云希 (男声)
    - zh-CN-YunjianNeural: 云健 (男声，新闻)
    - zh-CN-XiaoyiNeural: 晓伊 (女声，儿童)
    - zh-CN-XiaochenNeural: 晓晨 (女声)
    - zh-CN-XiaohanNeural: 晓涵 (女声)
    """

    # 中文语音映射
    CHINESE_VOICES = {
        "xiaoxiao": "zh-CN-XiaoxiaoNeural",
        "xiaoyi": "zh-CN-XiaoyiNeural",
        "yunxi": "zh-CN-YunxiNeural",
        "yunjian": "zh-CN-YunjianNeural",
        "xiaochen": "zh-CN-XiaochenNeural",
        "xiaohan": "zh-CN-XiaohanNeural",
    }

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self._voice: str = "zh-CN-XiaoxiaoNeural"
        self._rate: str = "+0%"
        self._volume: str = "+0%"
        self._pitch: str = "+0Hz"
        self._sample_rate = 24000  # Edge TTS输出24kHz

        # 从配置读取参数
        voice = config.model_name or "zh-CN-XiaoxiaoNeural"
        # 支持简短名称映射
        self._voice = self.CHINESE_VOICES.get(voice.lower(), voice)

        self._rate = config.extra_params.get('rate', '+0%')
        self._volume = config.extra_params.get('volume', '+0%')
        self._pitch = config.extra_params.get('pitch', '+0Hz')

    async def initialize(self) -> bool:
        """
        初始化Edge TTS

        Returns:
            bool: 初始化是否成功
        """
        try:
            import importlib.util
            if importlib.util.find_spec("edge_tts") is None:
                raise ImportError("edge-tts not found")

            # 测试Edge TTS是否可用
            self._mark_initialized()
            logger.info(f"[EdgeTTSProvider] 初始化成功 (语音: {self._voice})")
            return True

        except ImportError as _exc:
            error_msg = "edge-tts库未安装，请执行: pip install edge-tts"
            logger.error(f"[EdgeTTSProvider] {error_msg}")
            raise ModelLoadException(error_msg) from _exc
        except Exception as e:
            error_msg = f"Edge TTS初始化失败: {e}"
            logger.error(f"[EdgeTTSProvider] {error_msg}", exc_info=True)
            raise ModelLoadException(error_msg) from e

    async def synthesize(self, text: str, **kwargs) -> bytes:
        """
        合成语音

        Args:
            text: 要合成的文本
            **kwargs:
                - voice: 语音名称 (覆盖配置)
                - speed: 语速倍率 (0.5-2.0)
                - output_format: 输出格式 ('wav', 'mp3', 'pcm')

        Returns:
            音频字节数据 (默认WAV格式)
        """
        if not text or not text.strip():
            logger.warning("[EdgeTTSProvider] 合成文本为空")
            return b""

        try:
            import edge_tts

            # 获取参数
            voice = kwargs.get('voice', self._voice)
            speed = kwargs.get('speed', 1.0)
            output_format = kwargs.get('output_format', 'wav')

            # 语速转换: speed=1.0 -> "+0%", speed=1.5 -> "+50%", speed=0.5 -> "-50%"
            rate_percent = int((speed - 1.0) * 100)
            rate = f"{'+' if rate_percent >= 0 else ''}{rate_percent}%"

            logger.debug(f"[EdgeTTSProvider] 开始合成: {text[:50]}... (voice={voice}, rate={rate})")

            # 创建Communicate对象
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice,
                rate=rate,
                volume=self._volume,
                pitch=self._pitch
            )

            # 收集音频数据
            mp3_chunks = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    mp3_chunks.append(chunk["data"])

            if not mp3_chunks:
                raise SynthesisException("合成未产生任何音频数据")

            # 合并MP3数据
            mp3_data = b"".join(mp3_chunks)

            if output_format == 'mp3':
                return mp3_data

            # 转换为PCM/WAV
            pcm_data = self._mp3_to_pcm(mp3_data)

            if output_format == 'pcm':
                return pcm_data

            # 包装为WAV
            wav_data = self._pcm_to_wav(pcm_data, self._sample_rate)

            logger.debug(f"[EdgeTTSProvider] 合成成功: {len(wav_data)} bytes")
            return wav_data

        except SynthesisException:
            raise
        except Exception as e:
            error_msg = f"语音合成失败: {e}"
            logger.error(f"[EdgeTTSProvider] {error_msg}", exc_info=True)
            raise SynthesisException(error_msg) from e

    def _mp3_to_pcm(self, mp3_data: bytes) -> bytes:
        """
        将MP3数据解码为PCM

        Args:
            mp3_data: MP3格式音频数据

        Returns:
            PCM格式音频数据
        """
        try:
            from pydub import AudioSegment

            # 加载MP3
            audio = AudioSegment.from_mp3(io.BytesIO(mp3_data))

            # 转换为16kHz, 16-bit, 单声道
            audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)

            # 导出PCM
            pcm_buffer = io.BytesIO()
            audio.export(pcm_buffer, format="raw")
            return pcm_buffer.getvalue()

        except ImportError:
            logger.warning("[EdgeTTSProvider] pydub未安装，尝试使用备用解码")
            # 尝试使用pydub的备用方案
            try:
                import os
                import subprocess
                import tempfile

                # 创建临时文件
                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as mp3_file:
                    mp3_file.write(mp3_data)
                    mp3_path = mp3_file.name

                wav_path = mp3_path.replace('.mp3', '.wav')

                try:
                    # 使用ffmpeg转换
                    subprocess.run([
                        'ffmpeg', '-i', mp3_path,
                        '-ar', '16000', '-ac', '1', '-acodec', 'pcm_s16le',
                        '-y', wav_path
                    ], check=True, capture_output=True)

                    # 读取WAV数据
                    with open(wav_path, 'rb') as f:
                        wav_data = f.read()

                    # 跳过WAV头，返回PCM
                    return wav_data[44:]  # 标准WAV头44字节

                finally:
                    # 清理临时文件
                    os.unlink(mp3_path)
                    if os.path.exists(wav_path):
                        os.unlink(wav_path)

            except Exception as e:
                raise SynthesisException(f"MP3解码失败: {e}. 请安装pydub: pip install pydub") from e

    def _pcm_to_wav(self, pcm_data: bytes, sample_rate: int) -> bytes:
        """将PCM数据包装为WAV格式"""
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_data)
        return wav_buffer.getvalue()

    async def is_available(self) -> bool:
        """检查Provider是否可用"""
        import importlib.util
        return importlib.util.find_spec("edge_tts") is not None

    async def cleanup(self):
        """清理资源"""
        logger.info("[EdgeTTSProvider] 清理资源...")
        await super().cleanup()

    async def health_check(self) -> dict[str, Any]:
        """健康检查"""
        base_check = await super().health_check()
        base_check.update({
            "voice": self._voice,
            "rate": self._rate,
            "volume": self._volume,
            "pitch": self._pitch,
            "sample_rate": self._sample_rate
        })
        return base_check

    @classmethod
    def get_available_voices(cls, locale: str = "zh-CN") -> dict[str, str]:
        """
        获取可用的语音列表

        Args:
            locale: 语言区域代码

        Returns:
            语音ID到描述的字典
        """
        voices = {
            "zh-CN-XiaoxiaoNeural": "晓晓 - 年轻女性，友好热情",
            "zh-CN-XiaoyiNeural": "晓伊 - 儿童声音，活泼可爱",
            "zh-CN-YunxiNeural": "云希 - 年轻男性，自然随和",
            "zh-CN-YunjianNeural": "云健 - 男性，新闻播报风格",
            "zh-CN-XiaochenNeural": "晓晨 - 女性，温柔优雅",
            "zh-CN-XiaohanNeural": "晓涵 - 女性，专业正式",
            "zh-CN-XiaomengNeural": "晓梦 - 女性，甜美亲切",
            "zh-CN-XiaomoNeural": "晓墨 - 男性，成熟稳重",
            "zh-CN-XiaoqiuNeural": "晓秋 - 女性，清新自然",
            "zh-CN-XiaoruiNeural": "晓睿 - 女性，知性干练",
            "zh-CN-XiaoshuangNeural": "晓双 - 女性，活泼俏皮",
            "zh-CN-XiaoyanNeural": "晓颜 - 女性，标准普通话",
            "zh-CN-XiaoyouNeural": "晓悠 - 儿童声音，天真烂漫",
            "zh-CN-YunfengNeural": "云枫 - 男性，磁性低沉",
            "zh-CN-YunhaoNeural": "云浩 - 男性，阳光开朗",
            "zh-CN-YunyeNeural": "云野 - 男性，沉稳大气",
            "zh-CN-YunzeNeural": "云泽 - 男性，温和儒雅",
        }

        if locale == "all":
            return voices

        # 按locale过滤
        return {k: v for k, v in voices.items() if k.startswith(locale)}
