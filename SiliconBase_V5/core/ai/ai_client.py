#!/usr/bin/env python3                          # 指定Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文字符
"""
AI 客户端 - 兼容性包装器模块

⚠️ 重要说明：
此模块是兼容性包装器，用于保持向后兼容。
实际实现已移至根目录的 ai_client.py（Provider Factory架构）。

导入路径映射：
- 旧导入: from core.ai.ai_client import AIClient
- 新导入: from ai_client import AIClient

建议新项目直接使用根目录的 ai_client.py。

历史：
- 2026-03-01: 创建包装器，将实际实现移至根目录
"""

# 从根目录的 ai_client 导入所有类和函数         # 注释说明导入来源
# 使用 sys.path 确保能够正确导入根目录模块       # 解释导入技术方案
import os  # 导入os模块，用于文件路径处理
import sys  # 导入sys模块，用于系统路径操作

# 获取项目根目录（SiliconBase_V5/SiliconBase_V5 的父目录）  # 注释：路径计算逻辑
_current_dir = os.path.dirname(os.path.abspath(__file__))   # 获取当前文件所在目录的绝对路径
_project_root = os.path.dirname(_current_dir)               # 获取父目录（即项目根目录）

# 临时添加项目根目录到路径（如果尚未存在）       # 注释：路径配置说明
if _project_root not in sys.path:               # 检查项目根目录是否已在sys.path中
    sys.path.insert(0, _project_root)           # 将项目根目录插入到路径列表开头（优先级最高）

try:                                            # 开始try块，用于异常处理和确保路径恢复
    # 从根目录导入所有公开API                   # 注释：实际导入操作
    from ai_client import (  # 从根目录的ai_client模块导入以下组件
        # 主客户端类                             # 分类注释：主客户端类
        AIClient,  # 导入AIClient主类，核心功能实现
        # 异常类                                 # 分类注释：异常类
        AIClientError,  # 导入AI客户端错误异常类
        # 数据类                                 # 分类注释：数据类
        AIResponse,  # 导入AI响应数据类，封装AI返回结果
        # 向后兼容的别名                         # 分类注释：兼容性别名
        OllamaClient,  # 导入OllamaClient别名（兼容旧代码）
        _check_ollama_service,  # 导入检查Ollama服务状态函数
        # 便捷函数                               # 分类注释：便捷函数
        create_ai_client,  # 导入创建AI客户端函数
        get_default_client,  # 导入获取默认客户端函数（单例）
        # 智能路由支持                         # 分类注释：智能路由
        # 注意: chat_with_smart_route 是 AIClient 类的方法，不是模块级函数
        # evaluate_task_complexity,                # 需要检查是否存在
        # check_network_status,                    # 需要检查是否存在
        # get_routing_recommendation,              # 需要检查是否存在
        # 向后兼容的API函数                      # 分类注释：兼容性函数
        get_ollama_base_url,  # 导入获取Ollama基础URL函数
    )  # 导入列表结束
finally:                                        # finally块：无论是否异常都会执行
    # 清理：移除临时添加的路径                   # 注释：清理操作说明
    if sys.path[0] == _project_root:            # 检查项目根目录是否在路径列表开头
        sys.path.pop(0)                         # 移除临时添加的路径，恢复原始状态

# 定义 __all__ 以明确公开的API                   # 注释：__all__的作用
__all__ = [                                     # 定义模块的公开接口列表（控制from module import *的行为）
    # 数据类                                   # 分类注释：数据类
    "AIResponse",                              # AI响应数据类，包含content/model/usage等字段

    # 异常类                                   # 分类注释：异常类
    "AIClientError",                           # AI客户端异常基类

    # 主客户端类                               # 分类注释：主类
    "AIClient",                                # AI客户端主类，提供chat/send_request等方法

    # 向后兼容的别名                           # 分类注释：兼容性别名
    "OllamaClient",                            # OllamaClient别名（指向AIClient）

    # 向后兼容的API函数                        # 分类注释：兼容性函数
    "get_ollama_base_url",                     # 获取Ollama服务基础URL
    "_check_ollama_service",                   # 内部函数：检查Ollama服务健康状态

    # 便捷函数                                 # 分类注释：便捷函数
    "create_ai_client",                        # 工厂函数：创建指定类型的AI客户端
    "get_default_client",                      # 单例函数：获取默认AI客户端实例

    # 智能路由支持                           # 分类注释：智能路由
    # 注意: 这些函数需要从根目录 ai_client 模块导入，如果不存在则注释掉
    # "chat_with_smart_route",                   # 智能路由聊天函数（AIClient方法）
    # "evaluate_task_complexity",                # 任务复杂度评估函数
    # "check_network_status",                    # 网络状态检查函数
    # "get_routing_recommendation",              # 路由推荐函数
]                                               # __all__列表结束


# 可选：包装函数添加兼容性提示日志               # 注释：弃用警告功能（可选）
import functools  # 导入functools模块，用于函数装饰器工具
import warnings  # 导入warnings模块，用于发出弃用警告


def _deprecated_import_warning(func):           # 定义弃用警告装饰器函数
    """装饰器：添加弃用警告（可选，用于提醒迁移）"""   # 装饰器文档字符串
    @functools.wraps(func)                      # 使用wraps保留原函数的元信息（名称、文档等）
    def wrapper(*args, **kwargs):               # 定义包装函数，接收任意位置参数和关键字参数
        # 只在首次调用时警告                     # 注释：警告频率控制
        if not hasattr(wrapper, '_warned'):     # 检查包装函数是否已有_warned属性
            warnings.warn(                       # 发出弃用警告
                f"从 core.ai_client 导入 {func.__name__} 已弃用，"   # 警告消息第一部分
                f"建议直接从 ai_client 导入",                          # 警告消息第二部分（建议）
                DeprecationWarning,              # 警告类型：弃用警告
                stacklevel=2                     # 堆栈级别，指向调用者而非本函数
            )                                    # warnings.warn调用结束
            wrapper._warned = True              # 设置标志，标记已发出过警告
        return func(*args, **kwargs)            # 调用被装饰的原函数并返回结果
    return wrapper                              # 返回包装函数


# 标记模块已加载                                 # 注释：模块标记用途
_is_wrapper = True                              # 设置包装器标志，可用于外部检测本模块是包装器


# =============================================================================
# 【文件总结性注释】
# =============================================================================
#
# 【文件角色】
# core/ai_client.py 是 SiliconBase V5 项目的"兼容性包装器模块"，位于 core 目录下。
#
# 核心职责：
#   1. 向后兼容：允许旧代码继续使用 from core.ai.ai_client import AIClient 导入方式
#   2. 路径转发：通过临时修改 sys.path 将导入请求转发到根目录的实际实现
#   3. 透明代理：本模块不包含任何业务逻辑，仅作为导入转发层
#
# 重要说明：
#   - 此文件不包含实际的 AIClient 实现代码
#   - 实际的 AIClient 实现在项目根目录的 ai_client.py 文件中
#   - 本文件仅作为桥接层，确保旧代码无需修改即可继续工作
#
# -----------------------------------------------------------------------------
#
# 【关联文件】
#
# 1. 实际实现（核心依赖）：
#    - ai_client.py（项目根目录）
#      * 包含 AIClient 类的完整实现
#      * 包含 AIResponse 数据类定义
#      * 包含 AIClientError 异常类
#      * 包含 OllamaClient 等兼容性别名
#      * 包含 create_ai_client/get_default_client 等便捷函数
#      * 采用 Provider Factory 架构，支持多后端（Ollama/OpenAI/Anthropic等）
#
# 2. 调用方（被以下文件依赖）：
#    - core/ai_adapter.py
#      * 调用本模块的 AIClient 进行 AI 请求
#      * 是更上层的适配层，封装了场景化配置
#    - 其他旧代码模块
#      * 使用 from core.ai.ai_client import XXX 的代码
#
# 3. 相关 Provider 文件：
#    - core/providers/ai_provider_factory.py
#      * Provider 工厂，被根目录 ai_client.py 使用
#    - core/providers/base.py
#      * Provider 基类定义
#    - core/providers/ollama_provider.py
#      * Ollama Provider 实现
#    - core/providers/openai_provider.py
#      * OpenAI Provider 实现
#
# -----------------------------------------------------------------------------
#
# 【导入路径映射】
#
# 旧路径（仍支持）：
#   from core.ai.ai_client import AIClient, AIResponse
#
# 新路径（推荐）：
#   from ai_client import AIClient, AIResponse
#
# 两种导入方式最终都指向同一实现（根目录 ai_client.py）
#
# -----------------------------------------------------------------------------
#
# 【达到的效果】
#
# 1. 平滑迁移：
#    - 旧代码无需修改即可继续工作
#    - 新代码可以使用更简洁的导入路径
#    - 避免了一次性的全项目重构
#
# 2. 零业务逻辑：
#    - 本文件不包含任何 AI 调用逻辑
#    - 所有功能都委托给根目录的实际实现
#    - 避免代码重复和维护困难
#
# 3. 透明转发：
#    - 通过 sys.path 操作实现无缝转发
#    - 使用 try/finally 确保路径恢复
#    - 对调用者完全透明
#
# 4. 可选的弃用提醒：
#    - 提供 _deprecated_import_warning 装饰器
#    - 可在需要时启用，提醒开发者迁移到新路径
#    - 默认不启用，避免干扰现有功能
#
# -----------------------------------------------------------------------------
#
# 【技术细节】
#
# 1. 路径处理：
#    - 使用 os.path.dirname(os.path.abspath(__file__)) 获取当前目录
#    - 再取父目录得到项目根目录
#    - 使用 sys.path.insert(0, ...) 临时添加路径
#    - 使用 try/finally 确保路径被恢复
#
# 2. 导入机制：
#    - 使用 from ai_client import (...) 导入实际实现
#    - 使用 __all__ 明确控制公开 API
#    - 使用 functools.wraps 保留原函数元信息
#
# 3. 线程安全：
#    - 本模块的代码都是模块加载时执行，线程安全
#    - 实际的线程安全由根目录 ai_client.py 保证
#
# -----------------------------------------------------------------------------
#
# 【维护建议】
#
# 1. 不要在本文件添加业务逻辑：
#    - 任何 AI 相关逻辑都应添加到根目录 ai_client.py
#    - 本文件仅作为导入转发层
#
# 2. 保持 __all__ 更新：
#    - 当根目录 ai_client.py 新增公开 API 时
#    - 同步更新本文件的 __all__ 列表
#
# 3. 逐步迁移：
#    - 新代码优先使用 from ai_client import XXX
#    - 旧代码可在重构时逐步迁移
#    - 最终可能完全移除本文件
#
# 4. 启用弃用警告（可选）：
#    - 在适当时机可以启用 _deprecated_import_warning
#    - 提醒开发者使用新导入路径
#    - 为最终移除本文件做准备
#
# =============================================================================
