"""
ASR (自动语音识别) Provider模块

支持的Provider:
- VoskASRProvider: 离线语音识别，支持中文
- WhisperASRProvider: OpenAI Whisper API或本地模型
"""

from core.ai_models.providers.audio.asr.vosk_asr_provider import VoskASRProvider
from core.ai_models.providers.audio.asr.whisper_asr_provider import WhisperASRProvider

__all__ = [
    'VoskASRProvider',
    'WhisperASRProvider',
]
