#!/usr/bin/env python3
"""
感知策略定义（PerceptionStrategy）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
白皮书模块：感知系统的策略枚举 + 请求/响应数据契约
职责：纯数据定义，零逻辑，零副作用
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class PerceptionStrategy(Enum):
    """
    感知策略枚举

    由 PerceptionPlanner 根据任务类型、轮次、历史决定，
    PerceptionManager 只负责执行，不做任何决策。
    """
    NONE = auto()           # 不触发感知（纯对话、数学计算、推理）
    ENVIRONMENT = auto()    # 仅系统环境（平台、时间、进程）
    VISION_QUICK = auto()   # 仅视觉理解，无 OCR（快速场景描述）
    VISION_FULL = auto()    # 视觉理解 + OCR + 元素地图（UI 操作）


@dataclass(frozen=True)
class PerceptionRequest:
    """
    感知请求——不可变数据契约

    Args:
        strategy: 感知策略（由 PerceptionPlanner 决定）
        user_input: 用户原始输入
        screenshot: 调用方可传入已截取的图，避免重复截图
        timeout: 超时时间（秒）
    """
    strategy: PerceptionStrategy
    user_input: str
    screenshot: Any | None = None
    timeout: float = 30.0


@dataclass(frozen=True)
class PerceptionData:
    """
    感知结果——不可变数据契约

    作为 PerceptionManager.perceive() 的标准返回类型。
    """
    source: str                      # 感知来源：environment / vision / fused
    description: str                 # 人类可读的感知摘要
    screenshot: Any | None = None # 使用的截图（如有）
    ocr_text: str | None = None   # OCR 结果（VISION_FULL 时填充）
    element_map: Any | None = None # 结构化元素地图（VISION_FULL 时填充）
    environment: dict | None = None # 系统环境字典（ENVIRONMENT 时填充）
