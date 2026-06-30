#!/usr/bin/env python3
"""
SiliconBase V5 核心异常模块

统一存放所有自定义异常类，避免重复定义
所有异常类用于支持【静默失败阻断】机制：
- 任何无效返回必须抛出明确异常
- 配合 logger.error("[SILENT_FAILURE_BLOCKED] ...") 使用
"""

# ═══════════════════════════════════════════════════════════════
# AI 相关异常
# ═══════════════════════════════════════════════════════════════

class SiliconBaseException(Exception):
    """SiliconBase V5 统一异常根类

    所有 SiliconBase 自定义异常应直接或间接继承此类，
    便于调用方通过 except SiliconBaseException 捕获所有已知系统异常。
    """
    pass


class AIError(SiliconBaseException):
    """AI 相关错误的基类 - 禁止静默失败"""
    pass


class AIResponseError(AIError):
    """AI 响应错误 - AI返回空内容或无效格式"""
    pass


class AIConnectionError(AIError):
    """AI 连接错误 - 无法连接到AI服务"""
    pass


class AITimeoutError(AIError):
    """AI 超时错误 - AI响应超时"""
    pass


class AIEmptyResponseError(AIError):
    """AI 空响应错误 - AI返回None或空字符串"""
    pass


class AIInvocationError(AIError):
    """AI 调用错误 - AI调用过程中发生异常"""
    pass


class AIProviderError(AIError):
    """AI 提供商错误 - AI提供商返回错误"""
    pass


# ═══════════════════════════════════════════════════════════════
# 检查点/快照/状态持久化相关异常
# ═══════════════════════════════════════════════════════════════

class ModelBusError(SiliconBaseException):
    """ModelBus 初始化或调用失败 - 禁止静默失败

    当 ModelBus 未初始化、provider 注册失败、或模型调用返回无效结果时抛出。
    使用场景：
    - init_model_bus() 失败
    - call_model_bus_sync() 返回无效响应
    - get_model_bus() 返回 None

    【异常处理铁律】
    - ❌ 禁止 return None 伪装成功
    - ✅ 必须 logger.error("[ModelBus] ...") + raise ModelBusError
    """
    pass


class VisionAnalysisError(SiliconBaseException):
    """视觉分析失败 - 图像处理、UI 识别、截图分析失败时抛出

    【异常处理铁律】
    - ❌ 禁止 return None 伪装成功
    - ✅ 必须 logger.error("[Vision] ...") + raise VisionAnalysisError
    """
    pass


class AgentLoopInterrupted(SiliconBaseException):
    """Agent Loop 被外部信号中断 - 区别于执行错误

    当 Agent Loop 收到用户中断、超时信号、或 pre-tool 中断时抛出，
    让调用方明确知道是"被中断"而非"执行失败"。

    【使用场景】
    - 用户点击停止
    - 超时中断
    - pre-tool 安全检查中断

    【异常处理铁律】
    - ❌ 禁止 return None, working_memory 伪装正常结束
    - ✅ 必须 raise AgentLoopInterrupted("中断原因")
    """
    pass


class CheckpointError(SiliconBaseException):
    """检查点操作错误 - 状态保存/加载失败时抛出

    用于区分"状态不存在"(返回None)和"状态操作失败"(抛异常)
    """
    pass


class CheckpointSaveError(CheckpointError):
    """检查点保存错误 - 断点保存失败时抛出

    状态丢失是严重问题，必须抛出异常通知调用方
    """
    pass


class CheckpointLoadError(CheckpointError):
    """检查点加载错误 - 断点加载失败时抛出

    无法恢复任务状态时必须抛出异常
    """
    pass


class SnapshotError(SiliconBaseException):
    """快照操作错误 - 快照保存/加载/恢复失败时抛出"""
    pass


class PersistenceError(SiliconBaseException):
    """持久化操作错误 - 通用持久化失败异常"""
    pass


class LoadError(SiliconBaseException):
    """数据加载错误 - 文件/数据加载失败时抛出"""
    pass


class ProcessingError(SiliconBaseException):
    """处理流程错误 - 主处理流程或降级流程失败时抛出"""
    pass


# ═══════════════════════════════════════════════════════════════
# 长任务相关异常
# ═══════════════════════════════════════════════════════════════

class LongRunningError(SiliconBaseException):
    """长任务操作错误 - 长任务暂停/恢复/管理失败时抛出"""
    pass


class TaskStateError(SiliconBaseException):
    """任务状态错误 - 任务状态转换不合法时抛出"""
    pass


# ═══════════════════════════════════════════════════════════════
# 反思系统相关异常
# ═══════════════════════════════════════════════════════════════

class ReflectionError(SiliconBaseException):
    """反思系统错误 - 禁止静默失败"""
    pass


class ReflectionAIError(ReflectionError):
    """反思AI调用错误 - LLM调用失败时抛出"""
    pass


# ═══════════════════════════════════════════════════════════════
# 记忆系统相关异常
# ═══════════════════════════════════════════════════════════════

class MemorySystemError(SiliconBaseException):
    """记忆系统错误 - 记忆操作失败时抛出

    注意：原名 MemoryError 与 Python 内置异常冲突，已重命名。
    """
    pass


class MemoryNotFoundError(MemorySystemError):
    """记忆不存在错误 - 查询的记忆不存在时抛出"""
    pass


# ═══════════════════════════════════════════════════════════════
# 工具/插件相关异常
# ═══════════════════════════════════════════════════════════════

class ToolError(SiliconBaseException):
    """工具执行错误 - 工具调用失败时抛出"""
    pass


class ToolNotFoundError(ToolError):
    """工具不存在错误 - 请求的工具未找到时抛出"""
    pass


class ToolExecutionError(ToolError):
    """工具执行错误 - 工具执行过程中发生异常时抛出"""
    pass


class ToolLoadError(ToolError):
    """工具加载错误 - 工具加载失败时抛出"""
    pass


# ═══════════════════════════════════════════════════════════════
# 配置/初始化相关异常
# ═══════════════════════════════════════════════════════════════

class ConfigError(SiliconBaseException):
    """配置错误 - 配置加载/验证失败时抛出"""
    pass


class InitializationError(SiliconBaseException):
    """初始化错误 - 组件初始化失败时抛出"""
    pass


# ═══════════════════════════════════════════════════════════════
# 语音系统相关异常
# ═══════════════════════════════════════════════════════════════

class VoiceError(SiliconBaseException):
    """语音系统错误 - 语音操作失败时抛出"""
    pass


class TTSInitError(VoiceError):
    """TTS初始化错误 - TTS引擎初始化失败时抛出"""
    pass


class VoiceInitError(VoiceError):
    """语音初始化错误 - 语音系统初始化失败时抛出"""
    pass


class VoiceSpeakError(VoiceError):
    """语音播报错误 - 语音播报失败时抛出"""
    pass


class VoiceRecognitionError(VoiceError):
    """语音识别错误 - 语音识别失败时抛出"""
    pass


# ═══════════════════════════════════════════════════════════════
# 静默失败阻断专用异常（最底层基类）
# ═══════════════════════════════════════════════════════════════

class SilentFailureBlockedError(SiliconBaseException):
    """静默失败已被阻断 - 当系统成功阻断一次静默失败时抛出

    这个异常表示：
    1. 原本可能发生静默失败的代码路径
    2. 已被防御性编程捕获
    3. 并已记录 logger.error("[SILENT_FAILURE_BLOCKED] ...")

    使用场景：当需要明确告知调用方"这里本应静默失败，但已被阻断"
    """
    pass


# ═══════════════════════════════════════════════════════════════
# RLHF反馈系统相关异常
# ═══════════════════════════════════════════════════════════════

class RLHFError(SiliconBaseException):
    """RLHF反馈系统错误基类"""
    pass


class RLHFStorageError(RLHFError):
    """RLHF反馈存储失败 - 保存反馈数据时发生IO错误"""
    pass


class ExperienceNotFoundError(RLHFError):
    """经验不存在错误 - 尝试访问不存在的经验条目"""
    pass


class ExperienceUpdateError(RLHFError):
    """经验更新失败 - 更新经验权重或元数据时发生错误"""
    pass


# ═══════════════════════════════════════════════════════════════
# 幻觉检测相关异常
# ═══════════════════════════════════════════════════════════════

class HallucinationDetectionError(SiliconBaseException):
    """幻觉检测失败或异常 - 禁止静默失败

    当幻觉检测系统本身出现故障、AI响应为空无法检测、
    或检测到严重系统异常时抛出。

    使用场景：
    1. AI响应为空，无法进行幻觉检测
    2. 幻觉检测模块内部错误
    3. 检测结果异常（如置信度计算错误）

    注意：此异常表示"检测失败"，而非"检测到幻觉"
    """
    pass


class HallucinationAIEmptyResponseError(HallucinationDetectionError):
    """幻觉检测场景下的AI空响应错误

    当AI返回None或空字符串，导致幻觉检测无法执行时抛出。
    这是HallucinationDetectionError的子类，用于更精确的错误分类。

    注意：不要与 AIEmptyResponseError(AIError) 混淆。本异常专用于
    幻觉检测子系统，而 AIEmptyResponseError 是通用的AI空响应异常。

    异常处理铁律：
    - 必须记录ERROR级别日志
    - 必须抛出异常，禁止静默返回None
    - 调用方应决定是否重试或返回错误提示
    """
    pass


# ═══════════════════════════════════════════════════════════════
# 道德模块相关异常
# ═══════════════════════════════════════════════════════════════

class MoralCheckError(SiliconBaseException):
    """道德模块检查失败 - 当道德检查过程中发生错误时抛出

    使用场景：
    - 意图为空或无效
    - 规则正则编译错误
    - 检查过程中发生异常

    禁止静默失败，必须ERROR日志+抛错
    """
    pass


class MoralViolationError(SiliconBaseException):
    """违反道德规则 - 当用户意图或AI行动违反道德规则时抛出

    使用场景：
    - 用户输入包含危险意图
    - AI行动被道德规则拦截

    此异常表示意图/行动明确违规，需阻止执行
    """
    pass


# ═══════════════════════════════════════════════════════════════
# 经验记录相关异常
# ═══════════════════════════════════════════════════════════════

class ExperienceRecordError(SiliconBaseException):
    """经验记录失败 - 当工具执行经验值记录失败时抛出

    核心要求（异常处理铁律）：
    1. 禁止经验记录失败时静默
    2. 经验值计算失败 = ERROR日志 + 抛错
    3. 数据库写入失败 = ERROR日志 + 抛错

    使用场景：
    - 经验值计算异常
    - 数据库写入失败
    - 参数验证失败

    禁止静默失败，必须ERROR日志+抛错
    """
    pass


# ═══════════════════════════════════════════════════════════════
# 生命体征/内驱力系统相关异常
# ═══════════════════════════════════════════════════════════════

class LifeStateError(SiliconBaseException):
    """硅基生命状态获取/注入失败 - 禁止静默使用默认值

    使用场景：
    - 获取Consciousness实例失败
    - 获取用户生命状态失败
    - 注入生命体征到prompt失败

    【异常处理铁律】
    - ❌ 禁止静默使用默认值
    - ✅ 必须 logger.error("[Life] 获取生命体征失败") + raise LifeStateError
    - AI必须感知到"自己的身体状态"
    """
    pass


# ═══════════════════════════════════════════════════════════════
# 数据库/连接池相关异常
# ═══════════════════════════════════════════════════════════════

class DatabaseConnectionError(SiliconBaseException):
    """数据库连接失败 - 无法建立数据库连接时抛出

    使用场景：
    - 连接池获取连接失败
    - 数据库服务器不可达
    - 认证失败

    【异常处理铁律】
    - ❌ 禁止静默返回None
    - ✅ 必须 logger.error("[DB] 连接失败") + raise DatabaseConnectionError
    """
    pass


class DatabasePoolError(SiliconBaseException):
    """连接池错误 - 连接池操作失败时抛出

    使用场景：
    - 连接池初始化失败
    - 连接池已满无法获取连接
    - 连接池配置错误

    【异常处理铁律】
    - ❌ 禁止静默失败
    - ✅ 必须 logger.error("[DBPool] 错误") + raise DatabasePoolError
    """
    pass


class DatabaseQueryError(SiliconBaseException):
    """数据库查询错误 - SQL查询执行失败时抛出

    使用场景：
    - SQL语法错误
    - 查询执行超时
    - 结果集处理失败

    【异常处理铁律】
    - ❌ 禁止静默返回空结果
    - ✅ 必须 logger.error("[DB] 查询失败") + raise DatabaseQueryError
    """
    pass


class MigrationError(SiliconBaseException):
    """数据库迁移错误 - 迁移脚本执行失败时抛出

    使用场景：
    - 索引创建失败
    - 表结构变更失败
    - 数据迁移失败

    【零静默失败】
    - ❌ 禁止静默忽略迁移失败
    - ✅ 必须 logger.error("[SILENT_FAILURE_BLOCKED] 迁移失败") + raise MigrationError
    """
    pass


# ═══════════════════════════════════════════════════════════════
# Agent执行相关异常
# ═══════════════════════════════════════════════════════════════

class AgentExecutionError(SiliconBaseException):
    """Agent执行失败 - Agent循环执行过程中发生严重错误时抛出

    使用场景：
    - Agent循环内部异常
    - 任务执行失败
    - 状态转换错误

    【异常处理铁律】
    - ❌ 禁止静默吞异常
    - ✅ 必须 logger.error("[AgentLoop] 执行失败") + raise AgentExecutionError
    """
    pass


class AgentInitializationError(SiliconBaseException):
    """Agent初始化失败 - Agent组件初始化失败时抛出

    使用场景：
    - 核心组件初始化失败
    - 依赖服务不可用
    - 配置加载错误

    【异常处理铁律】
    - ❌ 禁止静默使用默认配置
    - ✅ 必须 logger.error("[Agent] 初始化失败") + raise AgentInitializationError
    """
    pass
