#!/usr/bin/env python3
"""
意识系统模块 - SiliconBase V5

包含：
- 生命感管理器 (life_presence)
- 硅基生命意识 (silicon_life_consciousness)
- 自我意识 (self_awareness)
- 工具反馈过滤器 (tool_feedback_filter / tool_feedback_manager)
- 工具反馈增强层 (tool_feedback_enhanced) - 连接 Reflector + RL Engine
- 生命感增强层 (life_presence_enhanced) - 连接 ImportanceEngine
- 意识集成 (consciousness_integration)

作者: SiliconBase Team
"""

# 导出主要组件
from core.consciousness.Consciousness import (
    get_consciousness_manager,
)

# 意识路由器（思维线程调度 LLM 入口）
from core.consciousness.consciousness_router import (
    ConsciousnessRouter,
    RouteDecision,
)
from core.consciousness.life_presence import (
    AIState,
    EventType,
    LifePresenceManager,
    NotificationLevel,
    get_life_presence_manager,
)

# 生命感增强层（V1.1 - 连接 ImportanceEngine）
from core.consciousness.life_presence_enhanced import (
    AnnouncementLearningMemory,
    EnhancedDecision,
    EnhancedSmartAnnouncer,
    create_enhanced_announcer,
)
from core.consciousness.silicon_life_consciousness import (
    LifeVitalSigns,
    SiliconLifeConsciousness,
    VitalSignsManager,
    get_silicon_life,
)

# 工具反馈增强层（V1.1 - 连接 Reflector + RL Engine）
from core.consciousness.tool_feedback_enhanced import (
    EnhancedFeedbackDecision,
    EnhancedToolFeedbackFilter,
    EnhancedToolFeedbackManager,
    EventSource,
    enhanced_tool_feedback_manager,
    filter_with_enhancement,
)

# 工具反馈过滤系统（V1.0 - 静态规则，基础层）
from core.consciousness.tool_feedback_filter import (
    FeedbackDecision,
    FeedbackLevel,
    ToolFeedbackConfig,
    ToolFeedbackFilter,
)
from core.consciousness.tool_feedback_manager import (
    ToolFeedbackManager,
    process_tool_result,
    tool_feedback_manager,
)

__all__ = [
    # 意识主控
    'get_consciousness_manager',

    # 生命感（基础层）
    'AIState',
    'NotificationLevel',
    'EventType',
    'LifePresenceManager',
    'get_life_presence_manager',

    # 生命感（增强层）
    'EnhancedSmartAnnouncer',
    'EnhancedDecision',
    'AnnouncementLearningMemory',
    'create_enhanced_announcer',

    # 硅基生命
    'SiliconLifeConsciousness',
    'LifeVitalSigns',
    'VitalSignsManager',
    'get_silicon_life',

    # 自我意识（已清理，数据由 IntrinsicMotivation 提供）

    # 工具反馈过滤（基础层 V1.0）
    'FeedbackLevel',
    'FeedbackDecision',
    'ToolFeedbackFilter',
    'ToolFeedbackConfig',
    'ToolFeedbackManager',
    'tool_feedback_manager',
    'process_tool_result',

    # 工具反馈过滤（增强层 V1.1）
    'EventSource',
    'EnhancedFeedbackDecision',
    'EnhancedToolFeedbackFilter',
    'EnhancedToolFeedbackManager',
    'enhanced_tool_feedback_manager',
    'filter_with_enhancement',

    # 意识路由器
    'RouteDecision',
    'ConsciousnessRouter',
]
