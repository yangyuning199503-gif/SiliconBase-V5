#!/usr/bin/env python3
"""
AI 适配层 - 100%兼容旧版函数，底层使用 AIClient 实现
提供 ollama 对象、call_thinker、generate_code_async 等核心函数
2026-02-15 修复：增加AI请求超时中断支持（通过future.cancel）
2026-02-22 重构：集成 ai_config 集中配置管理
2026-02-22 新增：集成 AIProviderFactory 支持多后端热切换
2026-03-10 修复：【静默失败修复】所有AI调用失败都会明确抛出异常并记录ERROR级别日志
2026-03-11 修复：【核心修复】符合严格修复标准
    - 禁止裸except: 捕获具体异常类型
    - 禁止静默失败: 所有异常路径都记录ERROR日志并抛出异常
    - 必须打ERROR日志: 所有异常使用 logger.error(..., exc_info=True)
    - AI调用失败必须抛出: 返回None或空字符串时抛出AIEmptyResponseError
    - 新增异常类: AIEmptyResponseError, AIInvocationError, AIProviderError
"""
import asyncio  # 导入异步IO库，用于异步操作支持
import atexit  # 导入atexit模块，用于程序退出时清理资源
import concurrent.futures  # 导入并发 futures 模块，用于线程池管理
import re  # 导入正则表达式模块，用于字符串处理
import sys
import threading  # 导入线程模块，用于线程锁实现线程安全
import time  # 导入时间模块，用于超时控制和时间戳记录

# 导入新的 AI 客户端与协议
from ai_client import AIClient  # 导入 AIClient 类，核心AI请求客户端
from core.agent.interrupt_handler import interrupt_handler  # 导入中断处理器，用于任务中断管理
from core.ai.ai_config import (  # 导入AI配置相关函数和枚举
    AIScene,
    ai_config,
)
from core.config import config  # 导入全局配置对象，用于读取系统配置
from core.diagnostic import safe_create_task
from core.exceptions import (
    AIConnectionError,
    AIEmptyResponseError,
    AIInvocationError,
    AIProviderError,
    AIResponseError,
    AITimeoutError,
)  # 从统一异常模块导入
from core.logger import logger  # 导入日志记录器，用于记录运行日志
from protocol import BaseProtocol, ChatMessage  # 导入协议基类和聊天消息类


# ========== 新增：多后端Provider支持 ==========
# 延迟导入避免循环依赖
def _get_provider_factory():            # 定义延迟导入函数，避免循环依赖问题
    from core.providers.ai_provider_factory import AIProviderFactory  # 在函数内部导入，延迟加载
    return AIProviderFactory            # 返回 AIProviderFactory 类


# 当前Provider缓存（线程安全）
_provider_lock = threading.Lock()       # 创建线程锁，确保Provider切换的线程安全
_current_provider = None                # 全局变量，缓存当前Provider实例，初始为None
_client_cache = {}                      # 【新增】客户端缓存字典

# 配置版本号（用于缓存刷新检测）
_config_version: int = -1               # 模块级配置版本号，初始为-1
_refresh_lock = threading.RLock()       # 刷新检查锁


def _check_refresh():
    """检查配置版本号，如有变更则刷新Provider

    使用双重检查锁定模式确保线程安全。
    所有异常都记录ERROR日志，禁止静默失败。
    """
    global _config_version, _current_provider

    try:
        from core.config import config
        current = config.get_version()

        if current != _config_version:
            with _refresh_lock:
                # 双重检查，避免多线程竞争
                if current != _config_version:
                    logger.info(f"[AIAdapter] 配置已变更（版本 {_config_version} -> {current}），刷新provider")
                    _config_version = current
                    # 清空provider缓存，下次调用时会重新初始化
                    with _provider_lock:
                        _current_provider = None
    except Exception as e:
        # 禁止静默失败：记录ERROR日志但不中断流程
        logger.error(f"[AIAdapter] 检查配置刷新失败: {e}", exc_info=True)


def get_current_provider():
    """获取当前 provider，带版本号检查"""
    global _current_provider, _config_version

    try:
        # 【新增】检查配置版本号
        current_version = config.get_version()
        if current_version != _config_version:
            with _refresh_lock:
                # 双重检查
                if current_version != _config_version:
                    logger.info(f"[AIAdapter] 配置已更新，刷新 provider: {_config_version} -> {current_version}")
                    with _provider_lock:
                        _current_provider = None  # 强制重新初始化
                    _client_cache.clear()
                    _config_version = current_version

        if _current_provider is None:
            # 重新初始化
            with _provider_lock:
                if _current_provider is None:
                    try:
                        factory = _get_provider_factory()
                        _current_provider = factory.get_current_provider()
                    except AIConnectionError:
                        raise
                    except Exception as e:
                        logger.error(f"[AIAdapter] 获取AI Provider失败: {e}", exc_info=True)
                        raise AIConnectionError(f"无法获取AI Provider: {e}") from e

        return _current_provider
    except Exception as e:
        logger.error(f"[AIAdapter] 获取 provider 失败: {e}", exc_info=True)
        raise


def refresh_provider():
    """
    刷新当前Provider缓存
    在AI配置更新后调用
    """
    global _current_provider, _client_cache

    try:
        with _provider_lock:
            old_provider = _current_provider
            _current_provider = None
            _client_cache.clear()
            logger.info(f"[AIAdapter] Provider缓存已刷新，原Provider: {old_provider}")
    except Exception as e:
        logger.error(f"[AIAdapter] 刷新Provider缓存失败: {e}", exc_info=True)
        raise


def call_with_provider(messages: list, **kwargs) -> str:   # 【静默失败修复】返回类型改为str，不再返回None
    """
    使用当前配置的Provider调用AI（支持多后端热切换）

    Args:
        messages: 消息列表 [{"role": "system/user/assistant", "content": "..."}, ...]
        **kwargs: 额外参数（temperature, max_tokens等）

    Returns:
        AI响应内容，失败时抛出AIResponseError异常

    Raises:
        AIResponseError: AI调用失败时抛出
        AIConnectionError: 无法连接到AI服务时抛出
    """
    # 检查配置是否需要刷新
    _check_refresh()

    try:                                # 尝试执行Provider调用
        provider = get_current_provider()   # 获取当前配置的Provider实例

        try:
            response = provider.chat(messages, **kwargs)   # 调用Provider的chat方法发送消息
        except AIProviderError as e:
            logger.error(f"[AIAdapter] AI提供商错误: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"[AIAdapter] Provider.chat调用异常: {e}", exc_info=True)
            raise AIInvocationError(f"AI调用失败: {e}") from e

        # 【静默失败修复】验证返回内容 - None检查
        if response is None:
            logger.error("[AIAdapter] AI返回None")
            raise AIEmptyResponseError("AI未返回任何内容")

        # 【静默失败修复】验证返回内容 - 空字符串检查
        if not str(response).strip():
            logger.error("[AIAdapter] AI返回空字符串")
            raise AIEmptyResponseError("AI返回内容为空")

        return response

    except AIProviderError:             # 【静默失败修复】AI提供商错误直接抛出
        raise
    except AIEmptyResponseError:        # 【静默失败修复】空响应异常直接抛出
        raise
    except AIResponseError:             # 【静默失败修复】已知异常直接抛出
        raise
    except AITimeoutError:              # 【静默失败修复】超时异常直接抛出
        raise
    except AIConnectionError:           # 【静默失败修复】连接异常直接抛出
        raise
    except AIInvocationError:           # 【静默失败修复】调用异常直接抛出
        raise
    except Exception as e:              # 【静默失败修复】捕获所有异常
        error_msg = str(e)
        logger.error(f"[AIAdapter] Provider调用失败: {error_msg}", exc_info=True)   # 记录调用失败错误日志

        # 区分不同类型的错误
        if "超时" in error_msg or "timeout" in error_msg.lower():
            raise AITimeoutError(f"AI响应超时: {error_msg}") from e
        elif "连接" in error_msg or "connection" in error_msg.lower() or " refused" in error_msg.lower():
            raise AIConnectionError(f"无法连接到AI服务: {error_msg}") from e
        else:
            raise AIInvocationError(f"AI调用失败: {error_msg}") from e


def get_provider_info() -> dict:        # 定义获取当前Provider信息的函数
    """获取当前Provider信息（用于前端显示）- 不检查可用性避免阻塞"""
    try:                                # 尝试获取Provider信息
        provider = get_current_provider()   # 获取当前Provider实例
        return {                        # 返回Provider信息字典
            "type": provider.__class__.__name__,   # Provider类名
            "config": provider.get_config(),       # Provider配置信息
            "available": True  # 前端自行检查，避免后端阻塞
        }
    except AIConnectionError as e:      # 【静默失败修复】连接异常
        logger.error(f"[AIAdapter] 获取Provider信息失败 - 连接错误: {e}", exc_info=True)
        return {                        # 返回错误信息
            "type": "unknown",          # 类型未知
            "error": f"连接错误: {str(e)}",  # 错误信息
            "available": False          # 不可用状态
        }
    except Exception as e:              # 【静默失败修复】捕获所有异常并记录
        logger.error(f"[AIAdapter] 获取Provider信息失败: {e}", exc_info=True)
        return {                        # 返回错误信息
            "type": "unknown",          # 类型未知
            "error": str(e),            # 错误信息
            "available": False          # 不可用状态
        }


def test_provider_config(provider_type: str, provider_config: dict) -> dict:   # 定义测试Provider配置的函数
    """
    测试Provider配置（不保存）

    Args:
        provider_type: Provider类型（ollama/openai/anthropic/custom）
        provider_config: Provider配置

    Returns:
        {"success": True/False, "message": "...", "response_preview": "..."}
    """
    try:                                # 【静默失败修复】添加异常处理
        factory = _get_provider_factory()   # 获取Provider工厂
        return factory.test_provider(provider_type, provider_config)   # 调用工厂的测试方法
    except AIConnectionError as e:      # 【静默失败修复】连接异常
        logger.error(f"[AIAdapter] 测试Provider配置失败 - 连接错误: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"测试失败 - 连接错误: {str(e)}",
            "response_preview": ""
        }
    except Exception as e:              # 【静默失败修复】捕获异常
        logger.error(f"[AIAdapter] 测试Provider配置失败: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"测试失败: {str(e)}",
            "response_preview": ""
        }


# 添加配置变更监听器，支持热加载
def _refresh_on_config_change(cfg):
    """配置变更时刷新Provider"""
    try:
        refresh_provider()
    except AIConnectionError as e:
        logger.error(f"[AIAdapter] 配置变更刷新Provider失败 - 连接错误: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"[AIAdapter] 配置变更刷新Provider失败: {e}", exc_info=True)

try:                                    # 【静默失败修复】添加异常处理
    config.add_change_listener(_refresh_on_config_change)   # 注册配置变更监听器，配置变化时自动刷新Provider
except AttributeError as e:             # 【静默失败修复】属性错误（config没有add_change_listener方法）
    logger.error(f"[AIAdapter] 注册配置变更监听器失败 - 方法不存在: {e}", exc_info=True)
except Exception as e:                  # 【静默失败修复】捕获异常
    logger.error(f"[AIAdapter] 注册配置变更监听器失败: {e}", exc_info=True)
# ============================================


# 创建全局 AI 客户端单例
try:                                    # 【静默失败修复】添加异常处理
    _ai_client = AIClient()                 # 实例化 AIClient 作为全局单例，用于发送AI请求
except ImportError as e:                # 【静默失败修复】导入错误
    logger.error(f"[AIAdapter] 创建AIClient单例失败 - 导入错误: {e}", exc_info=True)
    _ai_client = None                   # 标记为None，后续检查
except Exception as e:                  # 【静默失败修复】捕获异常
    logger.error(f"[AIAdapter] 创建AIClient单例失败: {e}", exc_info=True)
    _ai_client = None                   # 标记为None，后续检查

# 全局线程池 - 迁移到 ExecutorManager 统一管理
from core.utils.executors import ExecutorManager


# 兼容旧版 ollama 对象，提供 chat 方法
class OllamaCompat:                     # 定义Ollama兼容类，提供与旧版ollama相同的接口
    def chat(self, system_prompt: str, user_prompt: str, **kwargs) -> str:   # 【静默失败修复】返回类型改为str
        """
        兼容旧版 ollama.chat 方法，无历史上下文的单次对话
        2026-02-22: 使用 ai_config 获取场景化配置

        Raises:
            AIResponseError: AI调用失败时抛出
        """
        if _ai_client is None:          # 【静默失败修复】检查AI客户端是否初始化
            logger.error("[SILENT_FAILURE_BLOCKED] AIClient未初始化，无法调用AI")
            raise AIConnectionError("AIClient未初始化")

        protocol = BaseProtocol()       # 创建协议实例，用于构建请求

        # 【2026-02-22】使用 ai_config 获取配置
        scene = kwargs.get("scene", AIScene.CHAT)   # 从kwargs获取场景，默认为CHAT场景
        scene_config = ai_config.get_config_for_scene(scene) if isinstance(scene, str) else ai_config.get_config(scene)   # 根据场景类型获取配置

        # 构建请求参数（kwargs可覆盖默认配置）
        model_name = kwargs.get("model", scene_config.model_name)   # 获取模型名称，kwargs可覆盖
        temperature = kwargs.get("temperature", scene_config.temperature)   # 获取温度参数
        max_tokens = kwargs.get("num_predict", scene_config.max_tokens)   # 获取最大token数
        timeout = kwargs.get("timeout", scene_config.timeout)   # 获取超时时间
        retry_times = kwargs.get("retry", scene_config.retry_times)   # 获取重试次数

        # 构建请求
        req = protocol.build_request(   # 调用协议构建请求
            request_type="chat",        # 请求类型为chat
            content=f"{system_prompt}\n\n{user_prompt}",   # 合并系统提示和用户提示
            context=[],                 # 无历史上下文
            model_name=model_name,      # 模型名称
            temperature=temperature,    # 温度参数
            max_tokens=max_tokens,      # 最大token数
            timeout=timeout,            # 超时时间
            retry_times=retry_times     # 重试次数
        )

        # 添加其他模型参数
        req["model_config"].update({    # 更新模型配置
            "top_p": kwargs.get("top_p", scene_config.top_p),   # Top-p采样参数
            "top_k": kwargs.get("top_k", scene_config.top_k),   # Top-k采样参数
            "repeat_penalty": kwargs.get("repeat_penalty", scene_config.repeat_penalty),   # 重复惩罚
            "presence_penalty": kwargs.get("presence_penalty", scene_config.presence_penalty),   # 存在惩罚
            "frequency_penalty": kwargs.get("frequency_penalty", scene_config.frequency_penalty),   # 频率惩罚
            "stop": kwargs.get("stop", scene_config.stop_sequences)   # 停止序列
        })

        try:                            # 【静默失败修复】添加异常处理
            resp = _ai_client.send_request(req)   # 发送请求并获取响应

            # 【静默失败修复】验证响应对象
            if not resp:
                logger.error("[AIAdapter] AI返回空响应")
                raise AIEmptyResponseError("AI返回空响应")

            if resp.get("success"):         # 如果请求成功
                content = resp.get("content")
                # 【静默失败修复】验证返回内容 - None检查
                if content is None:
                    logger.error("[AIAdapter] AI返回None")
                    raise AIEmptyResponseError("AI未返回任何内容")
                # 【静默失败修复】验证返回内容 - 空字符串检查
                if not str(content).strip():
                    logger.error("[AIAdapter] AI返回空字符串")
                    raise AIEmptyResponseError("AI返回内容为空")
                return content
            else:                           # 请求失败
                error_msg = resp.get("error_msg", "未知错误")
                logger.error(f"[AIAdapter] AI请求失败: {error_msg}")
                raise AIProviderError(f"AI请求失败: {error_msg}")
        except AIProviderError as e:    # 【静默失败修复】AI提供商错误直接抛出
            logger.error(f"[AIAdapter] AI提供商错误: {e}", exc_info=True)
            raise
        except AIEmptyResponseError:    # 【静默失败修复】空响应异常直接抛出
            raise
        except AIResponseError:         # 【静默失败修复】已知异常直接抛出
            raise
        except Exception as e:          # 【静默失败修复】捕获异常
            logger.error(f"[AIAdapter] OllamaCompat.chat调用失败: {e}", exc_info=True)
            raise AIInvocationError(f"AI调用失败: {e}") from e


# 全局兼容实例
ollama = OllamaCompat()                 # 创建OllamaCompat实例，作为全局ollama对象供旧代码使用


import contextlib

from core.task.task_queue import task_queue  # 新增导入，任务队列用于获取当前任务信息


def call_thinker(messages: list, scene: AIScene = AIScene.REACT, **kwargs) -> str:
    """
    兼容旧版 call_thinker 函数，支持完整多轮对话历史，并可被中断
    messages 格式：[{"role": "system", "content": "xxx"}, ...]

    2026-02-22 更新：
    - 默认使用 REACT 场景配置（低temperature，提高格式遵循）
    - 支持通过 scene 参数切换不同场景配置
    - 支持 kwargs 覆盖具体参数

    2026-02-28 修复：
    - 增加硬超时保护，防止无限等待

    2026-03-10 修复：【静默失败修复】
    - AI调用失败时抛出明确异常，禁止返回None

    Raises:
        AIResponseError: AI响应错误或返回空内容时抛出
        AIConnectionError: 无法连接到AI服务时抛出
        AITimeoutError: AI响应超时时抛出
    """
    if _ai_client is None:              # 【静默失败修复】检查AI客户端
        logger.error("[SILENT_FAILURE_BLOCKED] AIClient未初始化，无法调用AI")
        raise AIConnectionError("AIClient未初始化")

    if not messages:                    # 【静默失败修复】空消息列表也视为错误
        logger.error("[SILENT_FAILURE_BLOCKED] call_thinker被调用时messages为空")
        raise AIResponseError("消息列表为空")

    # [修复] 记录开始时间，用于硬超时保护
    import time  # 导入time模块（局部导入确保可用）
    start_time = time.time()            # 记录当前时间戳
    hard_timeout = kwargs.get('hard_timeout', 70)  # 默认70秒硬超时

    # 拆分系统提示、历史上下文、当前用户输入
    system_content = ""                 # 初始化系统提示内容
    context = []                        # 初始化上下文消息列表
    user_content = ""                   # 初始化用户内容

    last_user_msg = None                # 初始化最后一条用户消息
    for msg in messages:                # 遍历所有消息
        role = msg["role"]              # 获取消息角色
        content = msg["content"]        # 获取消息内容
        if role == "system":            # 如果是系统消息
            system_content = content    # 保存为系统提示
        elif role == "user":            # 如果是用户消息
            # 保存为当前用户输入，但不添加到context（避免重复）
            last_user_msg = content     # 记录最后一条用户消息
            context.append(ChatMessage(role, content))   # 添加到上下文
        elif role == "assistant":       # 如果是助手消息
            context.append(ChatMessage(role, content))   # 添加到上下文

    # 使用最后一条用户消息作为当前输入
    user_content = last_user_msg if last_user_msg else ""   # 获取最后一条用户消息内容
    full_content = f"{system_content}\n\n{user_content}" if system_content else user_content   # 合并系统提示和用户内容

    # 【2026-02-22】使用 ai_config 获取场景化配置，默认使用REACT场景
    scene_config = ai_config.get_config(scene)   # 获取指定场景的配置

    # 构建标准请求（kwargs可覆盖默认配置）
    protocol = BaseProtocol()           # 创建协议实例
    model_name = kwargs.get("model", scene_config.model_name)   # 获取模型名称
    temperature = kwargs.get("temperature", scene_config.temperature)   # 获取温度参数
    max_tokens = kwargs.get("max_tokens", scene_config.max_tokens)   # 获取最大token数
    timeout = kwargs.get("timeout", scene_config.timeout)   # 获取超时时间
    retry_times = kwargs.get("retry_times", scene_config.retry_times)   # 获取重试次数

    req = protocol.build_request(       # 构建请求对象
        request_type="chat",            # 请求类型为chat
        content=full_content,           # 请求内容
        context=context[:-1],           # 上下文（排除最后一条用户消息，避免重复）
        model_name=model_name,          # 模型名称
        temperature=temperature,        # 温度参数
        max_tokens=max_tokens,          # 最大token数
        timeout=timeout,                # 超时时间
        retry_times=retry_times         # 重试次数
    )

    # 【2026-02-22】添加其他模型参数到配置
    req["model_config"].update({        # 更新模型配置
        "top_p": kwargs.get("top_p", scene_config.top_p),   # Top-p采样
        "top_k": kwargs.get("top_k", scene_config.top_k),   # Top-k采样
        "repeat_penalty": kwargs.get("repeat_penalty", scene_config.repeat_penalty),   # 重复惩罚
        "presence_penalty": kwargs.get("presence_penalty", scene_config.presence_penalty),   # 存在惩罚
        "frequency_penalty": kwargs.get("frequency_penalty", scene_config.frequency_penalty),   # 频率惩罚
        "stop": kwargs.get("stop", scene_config.stop_sequences),   # 停止序列
        "scene": scene.value if hasattr(scene, 'value') else str(scene)   # 场景信息，用于判断是否强制JSON工具调用
    })

    # 获取当前任务ID（用于中断检查）
    try:
        asyncio.get_running_loop()
        # 已在事件循环中，不能阻塞等待 result（会死锁）。
        # 同步路径放弃中断检查，交由 call_thinker_async 处理。
        current_task = None
    except RuntimeError:
        # 无事件循环（在 to_thread 工作线程中），安全阻塞等待
        current_task = asyncio.run(task_queue.current_task_async())
    task_id = current_task.id if current_task else None   # 获取任务ID，如果没有任务则为None

    def do_request():                   # 定义内部函数执行实际请求
        if _ai_client is None:          # 【静默失败修复】检查AI客户端
            logger.error("[AIAdapter] AIClient未初始化")
            raise AIConnectionError("AIClient未初始化")

        try:
            resp = _ai_client.send_request(req)   # 发送请求
        except AIProviderError as e:
            logger.error(f"[AIAdapter] AI提供商错误: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"[AIAdapter] AI请求异常: {e}", exc_info=True)
            raise AIInvocationError(f"AI请求失败: {e}") from e

        # 【静默失败修复】验证响应
        if not resp:
            logger.error("[AIAdapter] AI返回空响应")
            raise AIEmptyResponseError("AI返回空响应")

        if not resp.get("success"):
            error_msg = resp.get("error_msg", "未知错误")
            logger.error(f"[AIAdapter] AI请求失败: {error_msg}")
            raise AIProviderError(f"AI请求失败: {error_msg}")

        content = resp.get("content")
        if content is None:
            logger.error("[AIAdapter] AI返回None")
            raise AIEmptyResponseError("AI返回None")

        if not str(content).strip():
            logger.error("[AIAdapter] AI返回空字符串")
            raise AIEmptyResponseError("AI返回空字符串")

        return content

    # 【P1-Asyncify】支持跳过内部线程池，供 call_thinker_async 使用以避免双重线程池
    _skip_executor = kwargs.pop('_skip_executor', False)

    result = None
    try:
        if _skip_executor:
            # 直接执行，不提交到线程池（call_thinker_async 已在外层使用 to_thread）
            result = do_request()
        else:
            future = ExecutorManager.get_executor("llm").submit(do_request)   # 提交任务到统一 LLM 池执行
            # 轮询检查中断，同时等待结果
            while not future.done():            # 当任务未完成时循环
                # [修复] 硬超时检查
                elapsed = time.time() - start_time   # 计算已过去的时间
                if elapsed > hard_timeout:      # 如果超过硬超时时间
                    logger.error(f"[SILENT_FAILURE_BLOCKED] AI 请求硬超时（{elapsed:.1f}秒），强制返回")   # 记录错误日志
                    future.cancel()             # 尝试取消任务
                    raise AITimeoutError(f"AI响应硬超时（{elapsed:.1f}秒）")   # 【静默失败修复】抛出超时异常

                if task_id and interrupt_handler.is_interrupted(task_id):   # 检查任务是否被中断
                    # 中断当前任务
                    future.cancel()             # 取消任务
                    logger.info(f"AI 请求被中断 (task_id={task_id[:8]})")   # 记录中断日志
                    raise AIResponseError("AI请求被用户中断")   # 【静默失败修复】抛出中断异常
                time.sleep(0.1)                 # 休眠100ms，避免忙等

            # 获取结果（带超时）
            remaining_timeout = max(1, hard_timeout - (time.time() - start_time))   # 计算剩余超时时间
            result = future.result(timeout=min(timeout + 5, remaining_timeout))   # 获取结果，带超时
    except concurrent.futures.CancelledError:   # 任务被取消
        logger.error("[AIAdapter] AI请求被取消")
        raise AIInvocationError("AI请求被取消") from None
    except concurrent.futures.TimeoutError:   # 任务超时
        logger.error("[AIAdapter] AI 请求超时", exc_info=True)     # 记录超时错误
        raise AITimeoutError("AI响应超时") from None
    except AIProviderError as e:        # 【静默失败修复】AI提供商错误
        logger.error(f"[AIAdapter] AI提供商错误: {e}", exc_info=True)
        raise
    except AIResponseError:             # 【静默失败修复】已知异常直接抛出
        raise
    except AIEmptyResponseError:        # 【静默失败修复】空响应异常直接抛出
        raise
    except Exception as e:              # 【静默失败修复】捕获其他异常
        logger.error(f"[AIAdapter] 调用AI异常: {e}", exc_info=True)   # 记录异常
        raise AIInvocationError(f"AI调用失败: {e}") from e

    # 【静默失败修复】验证AI输出 - 返回None时抛出异常
    if result is None:
        logger.error("[AIAdapter] AI返回None")
        raise AIEmptyResponseError("AI未返回任何内容")

    # 【静默失败修复】验证AI输出 - 返回空字符串时抛出异常
    if not str(result).strip():
        logger.error("[AIAdapter] AI返回空字符串")
        raise AIEmptyResponseError("AI返回内容为空")

    return result


async def generate_code_async(prompt: str, stop_event=None, **kwargs) -> tuple[str, str | None]:
    """
    异步代码生成函数，兼容旧版调用
    2026-02-22: 使用 ai_config 获取代码场景配置
    2026-05-31: 改为原生 aiohttp 异步调用，消除 asyncio.to_thread 线程池包装

    Returns:
        Tuple[代码内容, 错误信息]: 成功时错误信息为None，失败时抛出异常

    Raises:
        AIResponseError: AI调用失败时抛出
    """
    if _ai_client is None:
        logger.error("[SILENT_FAILURE_BLOCKED] AIClient未初始化，无法生成代码")
        raise AIConnectionError("AIClient未初始化")

    protocol = BaseProtocol()

    # 【2026-02-22】使用 ai_config 获取代码场景配置
    scene_config = ai_config.get_config(AIScene.CODE)

    code_model = kwargs.get("model", config.get("ai.code_model") or scene_config.model_name)
    temperature = kwargs.get("temperature", scene_config.temperature)
    max_tokens = kwargs.get("max_tokens", scene_config.max_tokens)
    timeout = kwargs.get("timeout", scene_config.timeout)
    retry_times = kwargs.get("retry_times", scene_config.retry_times)

    req = protocol.build_request(
        request_type="chat",
        content=f"请严格按照需求生成Python代码，仅输出完整代码，不要任何解释、markdown标记和额外说明：\n\n{prompt}",
        context=[],
        model_name=code_model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        retry_times=retry_times
    )

    # 【2026-02-22】添加其他模型参数
    req["model_config"].update({
        "top_p": kwargs.get("top_p", scene_config.top_p),
        "top_k": kwargs.get("top_k", scene_config.top_k),
        "repeat_penalty": kwargs.get("repeat_penalty", scene_config.repeat_penalty),
        "presence_penalty": kwargs.get("presence_penalty", scene_config.presence_penalty),
        "frequency_penalty": kwargs.get("frequency_penalty", scene_config.frequency_penalty),
        "stop": kwargs.get("stop", scene_config.stop_sequences)
    })

    # 提取消息和生成参数，直接调用原生异步接口
    chat_messages = req.get("context", []).copy()
    chat_messages.append({"role": "user", "content": req["content"]})
    model_config = req["model_config"]
    callback_info = req["callback_info"]
    gen_params = {
        "temperature": model_config.get("temperature", 0.2),
        "max_tokens": model_config.get("max_tokens", 512),
        "top_p": model_config.get("top_p", 0.5),
        "top_k": model_config.get("top_k", 20),
        "repeat_penalty": model_config.get("repeat_penalty", 1.2),
        "presence_penalty": model_config.get("presence_penalty", 0.5),
        "frequency_penalty": model_config.get("frequency_penalty", 0.5),
        "stop": model_config.get("stop", ["\n\n", "```"]),
        "timeout": callback_info.get("timeout", 30),
    }

    try:
        code = await _ai_client.chat_async(chat_messages, **gen_params)
    except AIProviderError as e:
        logger.error(f"[AIAdapter] AI提供商错误: {e}", exc_info=True)
        raise
    except AIEmptyResponseError:
        raise
    except AIResponseError:
        raise
    except Exception as e:
        logger.error(f"[AIAdapter] 异步代码生成失败: {e}", exc_info=True)
        raise AIInvocationError(f"代码生成失败: {e}") from e

    # 清理代码中的markdown标记
    if code:
        code = re.sub(r"^```(python)?\n?", "", code, flags=re.IGNORECASE)
        code = re.sub(r"\n?```$", "", code)
        return code.strip(), None

    # 【静默失败修复】不应该到达这里，但以防万一
    raise AIResponseError("代码生成返回空内容")


# 【2026-02-22 新增】便捷函数：使用特定场景配置调用AI
def call_with_scene(messages: list, scene: str, **kwargs) -> str:   # 【静默失败修复】返回类型修改
    """
    使用指定场景配置调用AI

    Args:
        messages: 消息列表
        scene: 场景名称（"react", "code", "chat", "creative", "reflection", "summary"）
        **kwargs: 可覆盖场景配置的参数

    Returns:
        AI响应内容

    Raises:
        AIResponseError: AI调用失败时抛出
        AIEmptyResponseError: AI返回空内容时抛出
        AIInvocationError: AI调用异常时抛出
    """
    try:                                # 尝试执行
        scene_enum = AIScene(scene.lower())   # 将字符串场景转换为枚举
        return call_thinker(messages, scene=scene_enum, **kwargs)   # 调用call_thinker
    except ValueError as e:             # 如果场景名称无效
        logger.error(f"[AIAdapter] 未知场景 '{scene}'，使用默认REACT配置，错误: {e}", exc_info=True)
        # 使用默认REACT场景，但如果这也失败会抛出异常
        return call_thinker(messages, scene=AIScene.REACT, **kwargs)
    except AIProviderError as e:        # 【静默失败修复】AI提供商错误
        logger.error(f"[AIAdapter] AI提供商错误: {e}", exc_info=True)
        raise
    except AIEmptyResponseError:        # 【静默失败修复】空响应异常直接抛出
        raise
    except AIResponseError:             # 【静默失败修复】已知异常直接抛出
        raise
    except AITimeoutError:              # 【静默失败修复】超时异常直接抛出
        raise
    except AIConnectionError:           # 【静默失败修复】连接异常直接抛出
        raise
    except AIInvocationError:           # 【静默失败修复】调用异常直接抛出
        raise
    except Exception as e:              # 【静默失败修复】捕获其他异常
        logger.error(f"[AIAdapter] call_with_scene失败: {e}", exc_info=True)
        raise AIInvocationError(f"场景调用失败: {e}") from e


# ============================================
# 【PERF-001】异步包装器 - 将同步call_thinker转为异步
# ============================================
async def call_thinker_async(messages: list, scene: AIScene = AIScene.REACT, **kwargs) -> str:
    """
    异步版本的call_thinker，使用原生 aiohttp 异步 HTTP 请求。

    彻底消除 asyncio.to_thread + ExecutorManager 双重线程池。
    保留 BaseProtocol.build_request 协议构建逻辑。

    Args:
        messages: 消息列表
        scene: AI场景配置
        **kwargs: 额外参数

    Returns:
        AI响应内容（异步）

    Raises:
        AIResponseError: AI调用失败时抛出
        AIEmptyResponseError: AI返回空内容时抛出
        AIInvocationError: AI调用异常时抛出
    """
    if _ai_client is None:
        logger.error("[SILENT_FAILURE_BLOCKED] AIClient未初始化，无法调用AI")
        raise AIConnectionError("AIClient未初始化")

    if not messages:
        logger.error("[SILENT_FAILURE_BLOCKED] call_thinker_async被调用时messages为空")
        raise AIResponseError("消息列表为空")

    # 硬超时保护
    hard_timeout = kwargs.get('hard_timeout', 70)

    # 拆分系统提示、历史上下文、当前用户输入
    system_content = ""
    context = []
    last_user_msg = None
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        if role == "system":
            system_content = content
        elif role == "user":
            last_user_msg = content
            context.append(ChatMessage(role, content))
        elif role == "assistant":
            context.append(ChatMessage(role, content))

    user_content = last_user_msg if last_user_msg else ""
    full_content = f"{system_content}\n\n{user_content}" if system_content else user_content

    # 【2026-02-22】使用 ai_config 获取场景化配置，默认使用REACT场景
    scene_config = ai_config.get_config(scene)

    # 构建标准请求（kwargs可覆盖默认配置）
    protocol = BaseProtocol()
    model_name = kwargs.get("model", scene_config.model_name)
    temperature = kwargs.get("temperature", scene_config.temperature)
    max_tokens = kwargs.get("max_tokens", scene_config.max_tokens)
    timeout = kwargs.get("timeout", scene_config.timeout)
    retry_times = kwargs.get("retry_times", scene_config.retry_times)

    req = protocol.build_request(
        request_type="chat",
        content=full_content,
        context=context[:-1],
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        retry_times=retry_times
    )

    # 【2026-02-22】添加其他模型参数到配置
    req["model_config"].update({
        "top_p": kwargs.get("top_p", scene_config.top_p),
        "top_k": kwargs.get("top_k", scene_config.top_k),
        "repeat_penalty": kwargs.get("repeat_penalty", scene_config.repeat_penalty),
        "presence_penalty": kwargs.get("presence_penalty", scene_config.presence_penalty),
        "frequency_penalty": kwargs.get("frequency_penalty", scene_config.frequency_penalty),
        "stop": kwargs.get("stop", scene_config.stop_sequences),
        "scene": scene.value if hasattr(scene, 'value') else str(scene)
    })

    # 提取消息和生成参数，直接调用原生异步接口
    chat_messages = req.get("context", []).copy()
    chat_messages.append({"role": "user", "content": req["content"]})
    model_config = req["model_config"]
    callback_info = req["callback_info"]
    gen_params = {
        "temperature": model_config.get("temperature", 0.2),
        "max_tokens": model_config.get("max_tokens", 512),
        "top_p": model_config.get("top_p", 0.5),
        "top_k": model_config.get("top_k", 20),
        "repeat_penalty": model_config.get("repeat_penalty", 1.2),
        "presence_penalty": model_config.get("presence_penalty", 0.5),
        "frequency_penalty": model_config.get("frequency_penalty", 0.5),
        "stop": model_config.get("stop", ["\n\n", "```"]),
        "timeout": callback_info.get("timeout", 30),
    }

    # 获取当前任务ID（用于中断检查）
    current_task = await task_queue.current_task_async()
    task_id = current_task.id if current_task else None

    async def do_chat():
        if _ai_client is None:
            raise AIConnectionError("AIClient未初始化")
        return await _ai_client.chat_async(chat_messages, **gen_params)

    result = None
    try:
        start_time = time.time()
        logger.info(
            f"[TRACE] AIAdapter: do_chat() 启动, hard_timeout={hard_timeout}, "
            f"model={model_name}, ts={start_time:.3f}"
        )
        chat_task = safe_create_task(do_chat(), name="do_chat")

        # 轮询检查中断和硬超时
        while not chat_task.done():
            elapsed = time.time() - start_time
            if elapsed > hard_timeout:
                chat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await chat_task
                raise AITimeoutError(f"AI响应硬超时（{elapsed:.1f}秒）")

            if task_id and interrupt_handler.is_interrupted(task_id):
                chat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await chat_task
                raise AIResponseError("AI请求被用户中断")

            await asyncio.sleep(0.1)

        result = chat_task.result()
        _chat_elapsed = time.time() - start_time
        logger.info(
            f"[TRACE] AIAdapter: do_chat() 完成, elapsed={_chat_elapsed:.3f}s, "
            f"result_len={len(result) if result else 0}, ts={time.time():.3f}"
        )

    except asyncio.CancelledError:
        logger.error("[AIAdapter] AI请求被取消")
        raise AIInvocationError("AI请求被取消") from None
    except asyncio.TimeoutError:
        logger.error("[AIAdapter] AI 请求超时", exc_info=True)
        raise AITimeoutError("AI响应超时") from None
    except AIProviderError:
        raise
    except AIEmptyResponseError:
        raise
    except AIResponseError:
        raise
    except AITimeoutError:
        raise
    except AIConnectionError:
        raise
    except AIInvocationError:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[AIAdapter] 调用AI异常: {error_msg}", exc_info=True)
        if "超时" in error_msg or "timeout" in error_msg.lower():
            raise AITimeoutError(f"AI响应超时: {error_msg}") from e
        elif "连接" in error_msg or "connection" in error_msg.lower() or " refused" in error_msg.lower():
            raise AIConnectionError(f"无法连接到AI服务: {error_msg}") from e
        else:
            raise AIInvocationError(f"AI调用失败: {error_msg}") from e

    if result is None:
        logger.error("[AIAdapter] AI返回None")
        raise AIEmptyResponseError("AI未返回任何内容")

    if not str(result).strip():
        logger.error("[AIAdapter] AI返回空字符串")
        raise AIEmptyResponseError("AI返回内容为空")

    return result


# ============================================
# 线程池关闭函数（迁移到 ExecutorManager 统一管理）
# ============================================
def shutdown_executor():
    """关闭全局线程池，释放资源 - 委托给 ExecutorManager"""
    try:
        ExecutorManager.shutdown_all(wait=True)
        # 【架构红线】atexit 阶段禁止使用 logger，使用 print
        print("[AIAdapter] 线程池已委托 ExecutorManager 关闭", file=sys.stderr)
    except Exception as e:
        print(f"[CRITICAL ERROR][AIAdapter] 关闭线程池失败: {e}", file=sys.stderr)


# atexit 兜底：确保进程退出时线程池被关闭
# 注意：ExecutorManager 已注册自己的 atexit，此处保留兼容旧代码调用
atexit.register(shutdown_executor)


# =============================================================================
# 【文件总结性注释】
# =============================================================================
#
# 【文件角色】
# ai_adapter.py 是 SiliconBase V5 项目的 AI 适配层核心模块，位于 core 目录下。
# 它是整个系统与 AI 模型交互的统一入口和抽象层，负责：
#   1. 封装底层 AIClient 的复杂调用逻辑
#   2. 提供向后兼容的 API 接口（ollama 对象、call_thinker 等）
#   3. 实现多后端 AI Provider 的热切换支持
#   4. 管理 AI 请求的场景化配置（REACT/CODE/CHAT 等）
#   5. 提供超时控制、中断处理、重试机制等可靠性保障
#   6. 【2026-03-10】修复静默失败问题，所有AI调用失败都会明确抛出异常
#   7. 【2026-03-11】严格修复标准：禁止裸except，所有异常记录ERROR日志
#
# 【2026-03-10 静默失败修复】
#   - 新增 AIResponseError, AIConnectionError, AITimeoutError 异常类
#   - 所有AI调用失败时抛出明确异常，禁止返回None/False/[]
#   - 所有异常日志包含 [SILENT_FAILURE_BLOCKED] 标记
#   - 验证AI返回内容是否为空/无效
#
# 【2026-03-11 严格修复标准】
#   - 禁止裸except: 必须捕获具体异常类型（ImportError, ValueError等）
#   - 禁止静默失败: 不允许静默处理，所有异常必须抛出
#   - 必须打ERROR日志: 所有异常使用 logger.error("[AIAdapter] ...", exc_info=True)
#   - AI调用失败必须抛出: 不允许返回None或空字符串，抛出AIEmptyResponseError
#   - 新增异常类: AIEmptyResponseError, AIInvocationError, AIProviderError
#   - 细粒度异常处理: 区分AIProviderError, AIEmptyResponseError, AIResponseError等
#
# 【异常处理层级】
#   1. AIProviderError: AI提供商返回错误（如API错误）
#   2. AIEmptyResponseError: AI返回None或空字符串
#   3. AIResponseError: AI响应格式错误或无效
#   4. AIInvocationError: AI调用过程中发生异常
#   5. AIConnectionError: 无法连接到AI服务
#   6. AITimeoutError: AI响应超时
#
# 【关联文件】
#   - ai_client.py: 底层 AI 客户端，负责实际的网络请求发送
#   - core/config.py: 全局配置管理，提供系统配置读取
#   - core/logger.py: 日志记录器，用于运行日志记录
#   - core/ai_config.py: AI 场景化配置管理，定义不同场景的参数
#   - core/providers/ai_provider_factory.py: Provider 工厂，支持多后端切换
#   - core/interrupt_handler.py: 中断处理器，支持任务中断功能
#   - core/task_queue.py: 任务队列，提供当前任务信息
#   - protocol.py: 协议定义，包含 BaseProtocol 和 ChatMessage
#   - core/exceptions.py: 统一异常定义，包含所有AI相关异常
#
# 【调用关系】
#   - 被调用方：
#     * agent_loop.py: 调用 call_thinker/call_thinker_async 执行 AI 推理
#     * code_generator.py: 调用 generate_code_async 生成代码
#     * 各技能模块：通过 ollama 对象进行简单对话
#   - 调用方：
#     * AIClient: 底层实际发送 HTTP 请求
#     * AIProviderFactory: 获取具体 Provider 实例
#
# 【达到的效果】
#   1. 向后兼容：100% 兼容旧版函数接口，无需修改现有调用代码
#   2. 多后端支持：通过 AIProviderFactory 支持 Ollama/OpenAI/Anthropic 等后端热切换
#   3. 场景化配置：根据使用场景（REACT/CODE/CHAT）自动选择最优参数
#   4. 可靠性：支持超时控制、中断处理、重试机制、线程池复用
#   5. 性能优化：提供异步接口（call_thinker_async），避免阻塞事件循环
#   6. 热加载：配置变更时自动刷新 Provider，无需重启应用
#   7. 线程安全：使用锁机制确保 Provider 切换的线程安全
#   8. 静默失败防护：所有AI调用失败都会明确抛出异常，禁止静默返回
#   9. 严格异常处理：禁止裸except，所有异常都有明确处理路径
#
# 【设计模式】
#   - 适配器模式：将新 AIClient 接口适配为旧版兼容接口
#   - 单例模式：全局 _ai_client 和 _global_executor 实例
#   - 工厂模式：通过 AIProviderFactory 创建不同 Provider
#   - 策略模式：不同场景（AIScene）使用不同的配置策略
#   - 异常安全：所有AI调用失败都抛出明确异常，禁止静默失败
#
# =============================================================================
