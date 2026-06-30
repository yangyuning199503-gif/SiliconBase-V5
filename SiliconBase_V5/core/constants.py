"""
SiliconBase V5 全局常量配置
所有魔法数字必须定义在这里，禁止硬编码
"""


class MemoryWeights:
    """记忆层级权重"""
    L2_SEMANTIC = 0.4      # L2语义层：高权重，最相关
    L3_WORKFLOW = 0.3      # L3工作流：中权重
    L4_EPISODIC = 0.2      # L4情景层：低权重
    L5_PROCEDURAL = 0.1    # L5程序层：最低权重


class MCTSConfig:
    """MCTS算法配置"""
    DEFAULT_SIMULATIONS = 50      # 默认模拟次数
    EXPLORATION_WEIGHT = 1.0      # UCB探索权重
    MAX_DEPTH = 10                # 最大搜索深度


class TimeFeatures:
    """时间特征归一化参数"""
    HOURS_PER_DAY = 24.0
    MINUTES_PER_HOUR = 60.0
    DAYS_PER_WEEK = 7.0
    SECONDS_PER_HOUR = 3600.0


class WindowLimits:
    """窗口限制配置"""
    MAX_WINDOW_COUNT = 10
    MAX_PROCESS_COUNT = 100
    DEFAULT_EMOTION_VALUE = 0.5


class ScreenshotConfig:
    """截图配置"""
    MIN_INTERVAL = 0.1       # 最小截图间隔(秒)
    DEFAULT_TIMEOUT = 10.0   # 默认超时(秒)
    MAX_HISTORY = 100        # 最大历史记录数


class CacheConfig:
    """缓存配置"""
    DEFAULT_TTL = 3600       # 默认缓存时间(秒)
    MAX_SIZE = 200           # 最大缓存条目数
    CLEANUP_INTERVAL = 300   # 清理间隔(秒)
