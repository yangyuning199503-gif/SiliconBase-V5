#!/usr/bin/env python3
"""
经验量化模块入口

此包提供经验量化的核心能力：A/B 测试、效果追踪、自动淘汰。
历史上曾尝试迁移到 core.evaluation，但该模块并未实际落地，因此真实实现仍在此包内。
本文件作为统一入口，通过相对导入暴露所需符号，保持外部调用接口不变。
"""

# ═══════════════════════════════════════════════════════════════════
# A/B测试
# ═══════════════════════════════════════════════════════════════════
from .ab_test_framework import (
    ABTestFramework,
    ABTestGroup,
    ABTestMetrics,
    TaskExecutionRecord,
    TaskOutcome,
    get_ab_test_framework,
    should_use_experience,
)

# ═══════════════════════════════════════════════════════════════════
# 自动淘汰
# ═══════════════════════════════════════════════════════════════════
from .auto_purge_engine import (
    AutoPurgeEngine,
    ExperienceStatus,
    PurgeAction,
    PurgeCandidate,
    PurgeRecord,
    get_auto_purge_engine,
    run_experience_purge,
)

# ═══════════════════════════════════════════════════════════════════
# 效果追踪 - 提供新名称别名保持兼容
# ═══════════════════════════════════════════════════════════════════
from .experience_effectiveness_tracker import (
    ExperienceEffectivenessStats,
    ExperienceEffectivenessTracker,
    ExperienceUsageEvent,
    TaskOutcomeRecord,
    get_effectiveness_tracker,
)

# 新名称兼容：外部代码可能使用 EffectivenessTracker
EffectivenessTracker = ExperienceEffectivenessTracker

# ═══════════════════════════════════════════════════════════════════
# 导出列表
# ═══════════════════════════════════════════════════════════════════
__all__ = [
    # A/B测试
    'ABTestFramework',
    'ABTestGroup',
    'TaskOutcome',
    'ABTestMetrics',
    'TaskExecutionRecord',
    'get_ab_test_framework',
    'should_use_experience',

    # 效果追踪
    'EffectivenessTracker',
    'ExperienceEffectivenessTracker',  # 原名
    'ExperienceEffectivenessStats',
    'ExperienceUsageEvent',
    'TaskOutcomeRecord',
    'get_effectiveness_tracker',

    # 自动淘汰
    'AutoPurgeEngine',
    'PurgeAction',
    'ExperienceStatus',
    'PurgeCandidate',
    'PurgeRecord',
    'get_auto_purge_engine',
    'run_experience_purge'
]
