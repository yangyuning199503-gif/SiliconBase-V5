#!/usr/bin/env python3                                  # 指定Python解释器路径，使脚本可执行
# 声明UTF-8编码，支持中文字符
"""
错误码中心 V5.1 - 所有预定义错误码、用户消息、格式化函数集中管理
2026-02-16 修复：添加缺失的 PERMISSION_DENIED 错误码
"""
from dataclasses import dataclass  # 从dataclasses模块导入dataclass装饰器，简化数据类定义


@dataclass                                               # 使用dataclass装饰器自动生成__init__、__repr__等方法
class ErrorCode:                                         # 定义错误码数据类，封装错误相关的所有信息
    """                                                  # ErrorCode类文档字符串开始
    错误码数据类 - 封装错误码标识符、消息模板和日志级别

    Attributes:                                          # 属性说明
        code: 错误码唯一标识符，用于程序识别和处理                        # code属性说明
        message: 面向用户的错误消息模板，支持{placeholder}占位符格式      # message属性说明
        level: 日志级别，用于控制日志输出策略（error/warning/info）       # level属性说明
    """                                                  # ErrorCode类文档字符串结束
    code: str                                            # 错误码标识符，如"PERM_ADMIN_DENIED"，用于程序识别
    message: str                                         # 错误消息模板，支持{placeholder}格式，用于用户展示
    level: str = "error"                                 # 日志级别：error/warning/info，默认为error级别


# ========== 安全与权限 ==========                        # 分隔注释：以下是安全与权限相关的错误码定义
PERM_ADMIN_DENIED = ErrorCode(                           # 定义管理员权限拒绝错误码实例
    "PERM_ADMIN_DENIED",                                 # 错误码标识符：管理员权限被拒绝
    "本软件不支持以管理员身份运行，请以普通用户重新启动。"   # 用户友好的错误消息
)                                                        # PERM_ADMIN_DENIED定义结束
PERM_UAC_FAILED = ErrorCode(                             # 定义UAC提权失败错误码实例
    "PERM_UAC_FAILED",                                   # 错误码标识符：UAC提权操作失败
    "提权操作失败，请手动以管理员身份执行。"               # 提示用户手动提权
)                                                        # PERM_UAC_FAILED定义结束
RISK_BLACKLISTED = ErrorCode(                            # 定义黑名单进程错误码实例
    "RISK_BLACKLISTED",                                  # 错误码标识符：检测到黑名单进程
    "高风险进程已被自动终止，如需使用请以管理员权限运行。" # 安全保护提示
)                                                        # RISK_BLACKLISTED定义结束
# 新增通用权限拒绝错误码                                 # 注释说明：以下错误码是V5.1版本新增的通用权限错误
PERMISSION_DENIED = ErrorCode(                           # 定义通用权限拒绝错误码实例
    "PERMISSION_DENIED",                                 # 错误码标识符：通用权限不足
    "权限不足，无法执行该操作。"                           # 通用权限拒绝消息
)                                                        # PERMISSION_DENIED定义结束

# ========== 感知融合 ==========                         # 分隔注释：以下是感知融合模块相关的错误码定义
PRE_001_WINDOW_TIMEOUT = ErrorCode(                      # 定义窗口启动超时错误码实例
    "PRE_001_WINDOW_TIMEOUT",                            # 错误码标识符：窗口启动超时
    "{software} 启动超时，请手动打开或稍后重试。"          # 带占位符的消息模板，{software}会被替换为具体软件名
)                                                        # PRE_001_WINDOW_TIMEOUT定义结束
PRE_002_STALE_WINDOW = ErrorCode(                        # 定义窗口残留错误码实例
    "PRE_002_STALE_WINDOW",                              # 错误码标识符：检测到残留窗口
    "检测到窗口残留，已自动清理并重试。"                   # 自动恢复提示
)                                                        # PRE_002_STALE_WINDOW定义结束
GV_001_SCAN_NO_PERMISSION = ErrorCode(                   # 定义全局视图扫描权限错误码实例
    "GV_001",                                            # 错误码标识符：GV_001扫描无权限
    "扫描目录无权限，已跳过。"                             # 权限不足跳过提示
)                                                        # GV_001_SCAN_NO_PERMISSION定义结束
GV_002_DB_WRITE_FAILED = ErrorCode(                      # 定义数据库写入失败错误码实例
    "GV_002",                                            # 错误码标识符：GV_002数据库写入失败
    "软件信息库写入失败，请查看日志后重启底座。"           # 数据库故障提示
)                                                        # GV_002_DB_WRITE_FAILED定义结束

# ========== 任务与意图 ==========                       # 分隔注释：以下是任务处理和意图识别相关的错误码定义
NLP_001_NO_INTENT = ErrorCode(                           # 定义意图识别失败错误码实例
    "NLP_001",                                           # 错误码标识符：NLP意图识别失败
    "无法理解您的指令，请换种说法。"                       # 引导用户重新表达
)                                                        # NLP_001_NO_INTENT定义结束
NLP_LOW_CONFIDENCE = ErrorCode(                          # 定义意图置信度低错误码实例
    "NLP_LOW_CONFIDENCE",                                # 错误码标识符：NLP置信度低
    '指令模糊，请补充关键信息（例如"打开微信"）。'          # 引导用户提供更明确指令
)                                                        # NLP_LOW_CONFIDENCE定义结束

# ========== 工具执行 ==========                         # 分隔注释：以下是工具执行相关的错误码定义
TOOL_NOT_FOUND = ErrorCode(                              # 定义工具未找到错误码实例
    "TOOL_NOT_FOUND",                                    # 错误码标识符：无可用工具
    "当前没有可用工具完成此操作。"                         # 工具缺失提示
)                                                        # TOOL_NOT_FOUND定义结束
INVALID_PARAMS = ErrorCode(                              # 定义参数无效错误码实例
    "INVALID_PARAMS",                                    # 错误码标识符：工具参数错误
    "工具参数错误：{detail}"                               # 带详细信息的参数错误消息
)                                                        # INVALID_PARAMS定义结束
TOOL_ELEMENT_NOT_FOUND = ErrorCode(                      # 定义UI元素未找到错误码实例
    "TOOL_ELEMENT_NOT_FOUND",                            # 错误码标识符：界面元素未找到
    "未在屏幕上找到目标元素，请检查窗口是否激活。"         # UI自动化失败提示
)                                                        # TOOL_ELEMENT_NOT_FOUND定义结束
TOOL_TIMEOUT = ErrorCode(                                # 定义工具执行超时错误码实例
    "TOOL_TIMEOUT",                                      # 错误码标识符：工具执行超时
    "工具执行超时，请稍后重试。"                           # 超时提示
)                                                        # TOOL_TIMEOUT定义结束
TOOL_EXECUTION_ERROR = ErrorCode(                        # 定义工具执行异常错误码实例
    "TOOL_EXECUTION_ERROR",                              # 错误码标识符：工具执行异常
    "工具执行异常：{detail}"                               # 带详细信息的执行错误
)                                                        # TOOL_EXECUTION_ERROR定义结束
FILE_NOT_FOUND = ErrorCode(                              # 定义文件未找到错误码实例
    "FILE_NOT_FOUND",                                    # 错误码标识符：文件不存在
    "文件不存在：{detail}"                                 # 带详细信息的文件错误
)                                                        # FILE_NOT_FOUND定义结束
PATH_NOT_FOUND = ErrorCode(                              # 定义路径未找到错误码实例
    "PATH_NOT_FOUND",                                    # 错误码标识符：路径不存在
    "路径不存在：{detail}"                                 # 带详细信息的路径错误
)                                                        # PATH_NOT_FOUND定义结束
READ_ERROR = ErrorCode(                                  # 定义读取错误错误码实例
    "READ_ERROR",                                        # 错误码标识符：文件读取失败
    "文件读取失败：{detail}"                               # 带详细信息的读取错误
)                                                        # READ_ERROR定义结束
WRITE_ERROR = ErrorCode(                                 # 定义写入错误错误码实例
    "WRITE_ERROR",                                       # 错误码标识符：文件写入失败
    "文件写入失败：{detail}"                               # 带详细信息的写入错误
)                                                        # WRITE_ERROR定义结束
DELETE_ERROR = ErrorCode(                                # 定义删除错误错误码实例
    "DELETE_ERROR",                                      # 错误码标识符：删除失败
    "删除失败：{detail}"                                   # 带详细信息的删除错误
)                                                        # DELETE_ERROR定义结束
DEPENDENCY_MISSING = ErrorCode(                          # 定义依赖缺失错误码实例
    "DEPENDENCY_MISSING",                                # 错误码标识符：缺少依赖库
    "缺少依赖库，请安装 {package}"                          # 带包名的依赖提示
)                                                        # DEPENDENCY_MISSING定义结束
CLIPBOARD_ERROR = ErrorCode(                             # 定义剪贴板错误错误码实例
    "CLIPBOARD_ERROR",                                   # 错误码标识符：剪贴板操作失败
    "剪贴板操作失败"                                       # 剪贴板通用错误
)                                                        # CLIPBOARD_ERROR定义结束
VPN_CHECK_FAILED = ErrorCode(                            # 定义VPN检查失败错误码实例
    "VPN_CHECK_FAILED",                                  # 错误码标识符：VPN状态检查失败
    "检查 VPN 状态失败"                                    # VPN检查错误
)                                                        # VPN_CHECK_FAILED定义结束
VPN_CONNECT_FAILED = ErrorCode(                          # 定义VPN连接失败错误码实例
    "VPN_CONNECT_FAILED",                                # 错误码标识符：VPN连接失败
    "VPN 连接失败：{detail}"                               # 带详细信息的VPN连接错误
)                                                        # VPN_CONNECT_FAILED定义结束
NOT_SUPPORTED = ErrorCode(                               # 定义不支持操作错误码实例
    "NOT_SUPPORTED",                                     # 错误码标识符：操作系统不支持
    "当前操作系统不支持此操作"                             # 平台不支持提示
)                                                        # NOT_SUPPORTED定义结束

# ========== AI 调用 ==========                          # 分隔注释：以下是AI调用相关的错误码定义
AI_TIMEOUT = ErrorCode(                                  # 定义AI响应超时错误码实例
    "AI_TIMEOUT",                                        # 错误码标识符：AI响应超时
    "AI 响应超时，请检查 AI 服务状态。请前往前端左侧工具栏 → AI模型选择进行配置"  # 超时+配置引导
)                                                        # AI_TIMEOUT定义结束
AI_PARSE_ERROR = ErrorCode(                              # 定义AI解析错误错误码实例
    "AI_PARSE_ERROR",                                    # 错误码标识符：AI返回格式错误
    "AI 返回格式错误，已使用兜底方案。"                     # 解析失败但已降级处理
)                                                        # AI_PARSE_ERROR定义结束
CODE_GEN_FAILED = ErrorCode(                             # 定义代码生成失败错误码实例
    "CODE_GEN_FAILED",                                   # 错误码标识符：代码生成失败
    "代码生成失败：{detail}"                               # 带详细信息的代码生成错误
)                                                        # CODE_GEN_FAILED定义结束

# ========== 记忆与进化 ==========                       # 分隔注释：以下是记忆管理和系统进化相关的错误码定义
MEM_DB_CORRUPT = ErrorCode(                              # 定义记忆库损坏错误码实例
    "MEM_DB_CORRUPT",                                    # 错误码标识符：记忆数据库损坏
    "记忆库损坏，正在尝试自动修复。"                       # 损坏但自动修复中
)                                                        # MEM_DB_CORRUPT定义结束
EVOLUTION_NEED_APPROVAL = ErrorCode(                     # 定义进化需要确认错误码实例
    "EVOLUTION_NEED_APPROVAL",                           # 错误码标识符：学习新技能需确认
    "底座想学习新技能，请确认。"                           # 系统进化确认提示
)                                                        # EVOLUTION_NEED_APPROVAL定义结束

# ========== 通用 ==========                             # 分隔注释：以下是通用错误码定义
UNKNOWN_ERROR = ErrorCode(                               # 定义未知错误错误码实例
    "UNKNOWN_ERROR",                                     # 错误码标识符：未知错误
    "发生未知错误，请查看日志。"                           # 通用未知错误提示
)                                                        # UNKNOWN_ERROR定义结束
OPERATION_SUCCESS = ErrorCode(                           # 定义操作成功错误码实例
    "SUCCESS",                                           # 错误码标识符：操作成功
    "操作成功",                                           # 成功消息
    level="info"                                         # 日志级别为info，表示非错误
)                                                        # OPERATION_SUCCESS定义结束
OPERATION_CANCELLED = ErrorCode(                         # 定义操作取消错误码实例
    "CANCELLED",                                         # 错误码标识符：操作已取消
    "操作已取消",                                         # 取消消息
    level="info"                                         # 日志级别为info，表示用户主动行为
)                                                        # OPERATION_CANCELLED定义结束


def format_error(error: ErrorCode, detail: str = None, **kwargs) -> dict:    # 定义格式化错误响应函数，接收错误码和可选占位符参数
    """                                                  # 函数文档字符串开始
    生成标准错误响应字典（工具/模块通用）

    Args:                                                # 参数说明
        error: ErrorCode实例，包含错误码和消息模板          # error参数说明
        **kwargs: 用于填充消息模板占位符的关键字参数        # kwargs参数说明

    Returns:                                             # 返回值说明
        dict: 标准格式的错误响应字典，包含success/error_code/user_message/data字段  # 返回字典说明

    Example:                                             # 使用示例
        >>> format_error(FILE_NOT_FOUND, path="/tmp/test.txt")                       # 示例代码
        {                                                # 示例返回值
            'success': False,                            # 失败标志
            'error_code': 'FILE_NOT_FOUND',              # 错误码
            'user_message': '文件不存在：/tmp/test.txt',   # 格式化后的消息
            'data': None                                 # 无数据
        }                                                # 示例结束
    """                                                  # 函数文档字符串结束
    # 合并detail到kwargs中，支持{detail}占位符
    if detail is not None:
        kwargs['detail'] = detail
    msg = error.message.format(**kwargs) if kwargs else error.message  # 如果有占位符参数则格式化消息，否则直接使用
    return {                                             # 返回标准错误响应字典
        "success": False,                                # 操作失败标志，固定为False
        "error_code": error.code,                        # 错误码标识符，来自ErrorCode实例
        "user_message": msg,                             # 格式化后的用户友好错误消息
        "data": None                                     # 数据字段，错误时无数据返回
    }                                                    # 错误响应字典结束


def format_success(data=None, msg: str = None) -> dict:  # 定义格式化成功响应函数，接收可选数据和消息参数
    """                                                  # 函数文档字符串开始
    生成标准成功响应字典

    Args:                                                # 参数说明
        data: 可选的返回数据，可以是任意类型                # data参数说明
        msg: 可选的自定义成功消息，默认"操作成功"           # msg参数说明

    Returns:                                             # 返回值说明
        dict: 标准格式的成功响应字典                        # 返回字典说明

    Example:                                             # 使用示例
        >>> format_success(data={"file": "test.txt"}, msg="文件保存成功")            # 示例代码
        {                                                # 示例返回值
            'success': True,                             # 成功标志
            'error_code': '',                            # 无错误码
            'user_message': '文件保存成功',               # 自定义成功消息
            'data': {'file': 'test.txt'}                 # 返回的数据
        }                                                # 示例结束
    """                                                  # 函数文档字符串结束
    return {                                             # 返回标准成功响应字典
        "success": True,                                 # 操作成功标志，固定为True
        "error_code": "",                                # 错误码为空字符串表示无错误
        "user_message": msg or "操作成功",               # 使用传入消息或默认成功消息
        "data": data                                     # 返回的数据，可为None
    }                                                    # 成功响应字典结束


# ============================================
# 文件总结性注释
# ============================================
#
# 【文件角色】
# error_codes.py 是 SiliconBase V5 系统的"错误码中心"模块。
#
# 核心定位：
# - 集中管理所有预定义的错误码（ErrorCode实例）
# - 提供用户友好的中文错误消息模板（支持占位符）
# - 提供标准化的错误/成功响应格式化函数
#
# 架构位置：
#   工具模块 → ErrorCode → format_error/format_success → API响应 → 前端展示
#                ↓
#           统一错误码字典（便于追踪和分析）
#
# 【关联文件】
#
# | 文件/模块 | 关系类型 | 说明 |
# |-----------|----------|------|
# | tools/*.py | 使用者 | 所有工具模块导入error_codes返回标准化错误 |
# | core/interfaces.py | 关联 | 定义ToolResult等接口，包含error_code字段 |
# | core/api_handlers.py | 关联 | 将错误码转换为HTTP API响应 |
# | core/base_tool.py | 关联 | 工具基类定义统一的return格式（success/error_code/user_message/data） |
# | 前端界面 | 消费者 | 根据error_code显示user_message给用户 |
# | 日志系统 | 消费者 | 根据error.level决定日志级别 |
#
# 【达到的效果】
#
# 1. 错误码集中管理
#    - 所有错误码统一定义在一处，避免散落在各模块
#    - 便于维护和新增错误码
#    - 便于生成错误码文档
#
# 2. 用户友好的错误消息
#    - 所有错误消息使用中文，便于用户理解
#    - 消息模板支持{placeholder}占位符，可动态填充上下文
#    - 消息内容具有指导性，告诉用户如何解决
#
# 3. 标准化的响应格式
#    - 所有模块返回统一格式：{success, error_code, user_message, data}
#    - 前端可以统一处理响应，无需适配各模块差异
#    - 便于错误追踪和分析（通过error_code）
#
# 4. 日志分级支持
#    - ErrorCode包含level字段（error/warning/info）
#    - 可根据级别决定日志记录策略
#    - 区分真正的错误和用户取消等正常行为
#
# 5. 国际化准备
#    - ErrorCode结构支持未来扩展多语言
#    - 只需添加message_en、message_zh等字段即可
#
# 【错误码分类体系】
#
# | 分类前缀 | 说明 | 示例 |
# |----------|------|------|
# | PERM_* | 权限与安全 | PERM_ADMIN_DENIED, PERMISSION_DENIED |
# | PRE_* | 感知融合 | PRE_001_WINDOW_TIMEOUT |
# | GV_* | 全局视图 | GV_001_SCAN_NO_PERMISSION |
# | NLP_* | 自然语言处理 | NLP_001_NO_INTENT |
# | TOOL_* | 工具执行 | TOOL_NOT_FOUND, TOOL_TIMEOUT |
# | AI_* | AI调用 | AI_TIMEOUT, AI_PARSE_ERROR |
# | MEM_* | 记忆管理 | MEM_DB_CORRUPT |
# | EVOLUTION_* | 系统进化 | EVOLUTION_NEED_APPROVAL |
#
# 【使用示例】
#
# ```python
# from core.utils.error_codes import (
#     TOOL_NOT_FOUND, FILE_NOT_FOUND,
#     format_error, format_success
# )
#
# # 1. 简单错误返回
# if not tool:
#     return format_error(TOOL_NOT_FOUND)
#
# # 2. 带占位符的错误返回
# if not os.path.exists(path):
#     return format_error(FILE_NOT_FOUND, path=path)
#
# # 3. 带详细信息的错误返回
# try:
#     result = execute_tool(params)
# except Exception as e:
#     return format_error(TOOL_EXECUTION_ERROR, detail=str(e))
#
# # 4. 成功返回
# return format_success(data=result, msg="操作完成")
#
# # 5. 成功返回（默认消息）
# return format_success(data=result)
# ```
#
# 【版本历史】
#
# - V5.0：初始版本，定义基础错误码
# - V5.1（2026-02-16）：新增 PERMISSION_DENIED 通用权限错误码
#
# ============================================
