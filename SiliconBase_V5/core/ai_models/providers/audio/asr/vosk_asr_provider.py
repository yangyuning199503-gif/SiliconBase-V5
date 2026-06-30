"""
Vosk ASR Provider

离线语音识别适配器，基于Vosk开源语音识别工具包。
支持本地模型加载，无需网络连接。

模型下载: https://alphacephei.com/vosk/models
推荐中文模型: vosk-model-cn-0.22
"""

import json
import logging
from typing import Any

from core.ai_models.config import ModelConfig
from core.ai_models.exceptions import ModelLoadException, RecognitionException
from core.ai_models.providers.audio.asr.base_asr_provider import BaseASRProvider

logger = logging.getLogger(__name__)


class VoskASRProvider(BaseASRProvider):
    """
    Vosk离线语音识别适配器

    特点:
    - 完全离线，无需网络
    - 支持实时流式识别
    - 支持多种语言模型
    - 低延迟，适合实时应用
    """

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self._model = None
        self._recognizer = None
        self._model_path: str | None = None
        self._sample_rate = 16000

        # 更新能力标志
        self._capabilities.supports_batch = False
        self._capabilities.streaming = True

    async def initialize(self) -> bool:
        """
        初始化Vosk模型

        Returns:
            bool: 初始化是否成功

        Raises:
            ModelLoadException: 模型加载失败时抛出
        """
        try:
            from vosk import KaldiRecognizer, Model

            # 获取模型路径
            self._model_path = self.config.model_name
            if not self._model_path:
                error_msg = "未配置Vosk模型路径"
                logger.error(f"[VoskASRProvider] {error_msg}")
                raise ModelLoadException(error_msg)

            logger.info(f"[VoskASRProvider] 正在加载模型: {self._model_path}")

            # 检查模型文件完整性
            import os
            if not os.path.exists(self._model_path):
                error_msg = f"Vosk模型路径不存在: {self._model_path}"
                logger.error(f"[VoskASRProvider] {error_msg}")
                raise ModelLoadException(error_msg)

            # 检查关键模型文件
            required_files = ["am/final.mdl"]
            for req_file in required_files:
                full_path = os.path.join(self._model_path, req_file)
                if not os.path.exists(full_path):
                    error_msg = f"Vosk模型文件不完整，缺失: {req_file}"
                    logger.error(f"[VoskASRProvider] {error_msg}")
                    raise ModelLoadException(error_msg)

            # 检查解码图文件
            has_hclg = os.path.exists(os.path.join(self._model_path, "graph/HCLG.fst"))
            has_hclr_gr = (os.path.exists(os.path.join(self._model_path, "graph/HCLr.fst")) and
                          os.path.exists(os.path.join(self._model_path, "graph/Gr.fst")))

            if not (has_hclg or has_hclr_gr):
                error_msg = "Vosk模型缺少解码图文件 (需要 HCLG.fst 或 HCLr.fst+Gr.fst)"
                logger.error(f"[VoskASRProvider] {error_msg}")
                raise ModelLoadException(error_msg)

            if has_hclg:
                logger.info("[VoskASRProvider] 检测到标准解码图 (HCLG.fst)")
            else:
                logger.info("[VoskASRProvider] 检测到重打分解码图 (HCLr.fst + Gr.fst)")

            # 加载模型
            self._model = Model(self._model_path)
            self._recognizer = KaldiRecognizer(self._model, self._sample_rate)
            self._recognizer.SetWords(True)  # 启用词级别时间戳

            self._mark_initialized()
            logger.info("[VoskASRProvider] 模型加载成功")
            return True

        except ImportError as e:
            error_msg = f"vosk库未安装: {e}. 请执行: pip install vosk"
            logger.error(f"[VoskASRProvider] {error_msg}")
            raise ModelLoadException(error_msg) from e
        except ModelLoadException:
            raise
        except Exception as e:
            error_msg = f"Vosk模型加载失败: {e}"
            logger.error(f"[VoskASRProvider] {error_msg}", exc_info=True)
            raise ModelLoadException(error_msg) from e

    async def recognize(self, audio_data: bytes, **kwargs) -> str:
        """
        识别音频数据

        Args:
            audio_data: PCM音频字节数据 (16kHz, 16bit, mono)
            **kwargs:
                - partial: 是否返回部分结果 (默认False)

        Returns:
            识别到的文本

        Raises:
            RecognitionException: 识别失败时抛出
        """
        if not self._recognizer:
            error_msg = "Provider未初始化"
            logger.error(f"[VoskASRProvider] {error_msg}")
            raise RecognitionException(error_msg)

        try:
            # 处理音频数据
            if self._recognizer.AcceptWaveform(audio_data):
                result = json.loads(self._recognizer.Result())
                text = result.get("text", "").strip()

                if not text:
                    logger.debug("[VoskASRProvider] 识别结果为空")
                else:
                    logger.debug(f"[VoskASRProvider] 识别成功: {text[:50]}...")

                return text
            else:
                # 返回部分结果（如果请求）
                if kwargs.get('partial', False):
                    partial_result = json.loads(self._recognizer.PartialResult())
                    return partial_result.get("partial", "").strip()
                return ""

        except Exception as e:
            error_msg = f"语音识别失败: {e}"
            logger.error(f"[VoskASRProvider] {error_msg}", exc_info=True)
            raise RecognitionException(error_msg) from e

    async def recognize_stream(self, audio_stream, **kwargs) -> str:
        """
        流式识别（实时识别）

        Args:
            audio_stream: 异步音频数据流 (AsyncIterator[bytes])
            **kwargs:
                - on_partial: 部分结果回调函数

        Yields:
            识别文本片段
        """
        if not self._recognizer:
            error_msg = "Provider未初始化"
            logger.error(f"[VoskASRProvider] {error_msg}")
            raise RecognitionException(error_msg)

        on_partial = kwargs.get('on_partial')

        try:
            async for audio_chunk in audio_stream:
                if self._recognizer.AcceptWaveform(audio_chunk):
                    result = json.loads(self._recognizer.Result())
                    text = result.get("text", "").strip()
                    if text:
                        logger.debug(f"[VoskASRProvider] 流式识别结果: {text[:50]}...")
                        yield text
                else:
                    # 部分结果
                    if on_partial:
                        partial_result = json.loads(self._recognizer.PartialResult())
                        partial_text = partial_result.get("partial", "").strip()
                        if partial_text:
                            on_partial(partial_text)

            # 获取最终剩余结果
            final_result = json.loads(self._recognizer.FinalResult())
            final_text = final_result.get("text", "").strip()
            if final_text:
                yield final_text

        except Exception as e:
            error_msg = f"流式识别失败: {e}"
            logger.error(f"[VoskASRProvider] {error_msg}", exc_info=True)
            raise RecognitionException(error_msg) from e

    async def is_available(self) -> bool:
        """
        检查Provider是否可用

        Returns:
            bool: 模型是否已加载
        """
        return self._model is not None and self._recognizer is not None

    async def reset(self):
        """
        重置识别器状态

        在长会话中定期调用，清除历史状态。
        """
        if self._recognizer:
            self._recognizer.Reset()
            logger.debug("[VoskASRProvider] 识别器已重置")

    async def cleanup(self):
        """
        清理资源
        """
        logger.info("[VoskASRProvider] 清理资源...")
        self._recognizer = None
        self._model = None
        await super().cleanup()

    async def health_check(self) -> dict[str, Any]:
        """
        健康检查

        Returns:
            包含健康状态的字典
        """
        base_check = await super().health_check()
        base_check.update({
            "model_path": self._model_path,
            "sample_rate": self._sample_rate,
            "recognizer_ready": self._recognizer is not None
        })
        return base_check
