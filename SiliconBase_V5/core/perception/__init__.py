#!/usr/bin/env python3
"""
感知模块 - SiliconBase V5
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

设计原则（三维度思考）：
1. AI 维度：智能语义理解 > 关键词匹配
2. 用户维度：零配置，无缝升级
3. 项目维度：向后兼容，云端友好

集成策略：
- 运行时自动选择最优策略
- 零环境变量配置
- 100% 向后兼容
"""

from .trigger_with_fallback import should_trigger_perception

__all__ = ['should_trigger_perception']
