"""
ModelBus Providers - 模型Provider适配器

包含各类模型的Provider实现：
- llm: 大语言模型
- vision: 视觉模型
- audio: 音频模型（ASR/TTS/增强）
- embedding: 向量模型
- multimodal: 多模态模型
"""

__version__ = "1.0.0"

# 这里将在后续Phase中导入具体的Provider实现
# from .llm import OpenAIProvider, AnthropicProvider
# from .vision import OpenAIVisionProvider
# from .audio import OpenAIAudioProvider
# from .embedding import OpenAIEmbeddingProvider
# from .multimodal import GPT4VProvider

__all__ = []
