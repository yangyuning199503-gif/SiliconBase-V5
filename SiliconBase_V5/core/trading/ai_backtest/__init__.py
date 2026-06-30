#!/usr/bin/env python3
"""
AI 友好型回测引擎

设计目标：
- 极速回测：支持 AI 快速迭代测试数百个策略变体
- 信息丰富：提供详细的交易上下文，帮助 AI 理解成功/失败原因
- 结构化输出：方便 AI 解析和分析
- 实时反馈：支持流式结果，AI 可以边回测边分析
"""

from .engine import AIFriendlyBacktester, BacktestContext
from .feedback_generator import AIFeedbackGenerator
from .result_formatter import BacktestResultFormatter

__all__ = [
    'AIFriendlyBacktester',
    'BacktestContext',
    'BacktestResultFormatter',
    'AIFeedbackGenerator',
]
