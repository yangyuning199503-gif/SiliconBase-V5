"""
core.constants - 项目级常量定义
避免多处硬编码重复定义
"""

from .chat_keywords import (
    FORCE_TASK_KEYWORDS,
    FORCE_VISION_KEYWORDS,
    REALTIME_MONITOR_START_KEYWORDS,
    REALTIME_MONITOR_STOP_KEYWORDS,
    SIMPLE_CHAT_KEYWORDS,
    TASK_CONTROL_KEYWORDS,
    TASK_STATUS_QUERY_KEYWORDS,
    classify_user_input,
    is_simple_chat,
    is_start_monitor_command,
    is_stop_monitor_command,
    is_task_control_command,
    is_task_status_query,
)


# 记忆层级权重
class MemoryWeights:
    L2_SEMANTIC = 0.4
    L3_WORKFLOW = 0.3
    L4_EPISODIC = 0.2
    L5_PROCEDURAL = 0.1

# MCTS算法配置
class MCTSConfig:
    DEFAULT_SIMULATIONS = 50
    EXPLORATION_WEIGHT = 1.0
    MAX_DEPTH = 10

# 截图配置
class ScreenshotConfig:
    MIN_INTERVAL = 0.1
    DEFAULT_TIMEOUT = 10.0
    MAX_RETRIES = 3
    RETRY_DELAY = 0.5

# 时间特征归一化参数
class TimeFeatures:
    HOURS_PER_DAY = 24.0
    MINUTES_PER_HOUR = 60.0
    SECONDS_PER_MINUTE = 60.0
    DAYS_PER_WEEK = 7.0

# 窗口限制配置
class WindowLimits:
    MAX_WINDOW_COUNT = 10
    MAX_PROCESS_COUNT = 100

# 缓存配置
class CacheConfig:
    DEFAULT_TTL = 3600
    MAX_SIZE = 200
    CLEANUP_INTERVAL = 300

__all__ = [
    "SIMPLE_CHAT_KEYWORDS",
    "TASK_STATUS_QUERY_KEYWORDS",
    "TASK_CONTROL_KEYWORDS",
    "REALTIME_MONITOR_START_KEYWORDS",
    "REALTIME_MONITOR_STOP_KEYWORDS",
    "FORCE_TASK_KEYWORDS",
    "FORCE_VISION_KEYWORDS",
    "is_simple_chat",
    "is_task_status_query",
    "is_task_control_command",
    "is_start_monitor_command",
    "is_stop_monitor_command",
    "classify_user_input",
    "MemoryWeights",
    "MCTSConfig",
    "ScreenshotConfig",
    "TimeFeatures",
    "WindowLimits",
    "CacheConfig",
]
