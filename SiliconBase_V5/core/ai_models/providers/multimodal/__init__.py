"""
Multimodal Provider适配器

多模态模型Provider实现（视觉+动作+推理）
"""

__version__ = "1.0.0"

from .base_multimodal_provider import BaseMultimodalProvider
from .ui_tars_provider import UITarsProvider

__all__ = [
    "BaseMultimodalProvider",
    "UITarsProvider"
]
