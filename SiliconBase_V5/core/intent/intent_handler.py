#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
意图处理器 - 分发处理各种意图类型  # 模块功能概述
新增：安全守卫 + 全语音播报 + 精准抓取集成  # 新增特性说明
"""  # 多行文档字符串结束

import asyncio  # Phase 4: 支持原生 async/await
import contextlib
import time  # 导入时间模块
from typing import Any  # 从typing导入类型注解工具

from core.agent.phase_context import PhaseContext
from core.agent.phase_registry import register_phase
from core.diagnostic import safe_create_task
from core.exceptions import MoralCheckError, MoralViolationError  # 【Agent-2】导入道德模块异常
from core.intent.nlp_intent_parser import (  # 从core.nlp_intent_parser导入NLP解析相关
    AICodeMarker,  # 导入AI标记类型和解析输出类
    IntentType,  # 导入意图类型和解析结果类
    ParsedAIOutput,
    ParsedIntent,
    get_announcer,
    get_precision_parser,  # 导入获取解析器和播报器的函数
)
from core.interfaces import HandlerResult  # 从core.interfaces导入结果类型
from core.logger import logger  # 从core.logger导入日志记录器
from core.memory.memory_service import get_memory_service  # 【P1-迁移】异步记忆服务入口
from core.memory.memory_source import MemorySource  # Agent-4: 导入MemorySource枚举
from core.memory.memory_trigger import on_tool_execution_async  # 【P1-迁移】异步工具执行记忆存储
from core.memory.working_memory import WorkingMemory  # 从core.working_memory导入工作记忆
from core.safety.confirmation_manager import confirmation_manager  # 从core.confirmation_manager导入确认管理器
from core.safety.moral_module import get_moral_module  # 【Agent-3】导入道德模块
from core.safety.safety_guard import RiskLevel, assess_operation_risk  # 从core.safety_guard导入风险评估
from core.sync.event_bus import event_bus  # 【ExperienceBus】事件总线
from core.sync.realtime_sync import get_realtime_sync_manager  # 从core.realtime_sync导入同步管理器
from core.tool.tool_manager import tool_manager  # 从core.tool_manager导入工具管理器
from voice.voice_prompts import TOOL_NAME_MAP, DialogueAnnouncements, SystemAnnouncements


class IntentHandler:  # 定义意图处理器类
    """意图处理分发器 - 集成精准抓取"""  # 类文档字符串

    def __init__(self):  # 初始化方法
        self._precision_parser = None  # 初始化精准抓取解析器为None
        self._announcer = None  # 初始化播报器为None

    def _get_precision_parser(self,  # 定义获取精准抓取解析器的私有方法
                              voice_instance=None  # 参数：语音实例
                              ):  # 返回：解析器实例
        """获取精准抓取解析器"""  # 方法文档字符串
        if self._precision_parser is None:  # 如果解析器未创建
            self._precision_parser = get_precision_parser(voice_instance)  # 创建解析器
        elif voice_instance is not None:  # 如果提供了语音实例
            self._precision_parser.update_voice_instance(voice_instance)  # 更新解析器的语音实例
        return self._precision_parser  # 返回解析器实例

    def _get_announcer(self,  # 定义获取播报器的私有方法
                       voice_instance=None  # 参数：语音实例
                       ):  # 返回：播报器实例
        """获取播报器"""  # 方法文档字符串
        if self._announcer is None:  # 如果播报器未创建
            self._announcer = get_announcer(voice_instance)  # 创建播报器
        elif voice_instance is not None:  # 如果提供了语音实例
            self._announcer.set_voice(voice_instance)  # 设置播报器的语音实例
        return self._announcer  # 返回播报器实例

    @staticmethod  # 定义静态方法装饰器
    def _speak(message: str,  # 定义语音播报静态方法
               fallback_to_text: bool = True  # 参数：失败时是否降级到文本，默认True
               ) -> bool:  # 返回：是否成功
        """
        语音播报 - 修复：使用线程避免阻塞主流程，添加详细调试

        【P0-003修复】新增降级机制：语音异常时自动降级到文本输出

        Args:  # 参数说明
            message: 要播报的消息  # 参数1
            fallback_to_text: 语音失败时是否降级到文本  # 参数2

        Returns:  # 返回值说明
            bool: 语音播报是否成功  # 返回类型
        """  # 方法文档字符串
        import threading  # 导入线程模块

        speak_success = False  # 初始化成功标志为False

        def do_speak():  # 定义内部播报函数
            nonlocal speak_success  # 声明使用外部变量
            try:  # 开始异常处理
                from core.dialog.dialogue_manager import dialogue_manager  # 导入对话管理器
                print(f"[_speak] 尝试播报: {message}")  # 打印调试信息
                print(f"[_speak] dialogue_manager.voice = {dialogue_manager.voice}")  # 打印语音实例

                if dialogue_manager.voice:  # 如果有语音实例
                    logger.info(f"[语音播报] {message}")  # 记录日志
                    print(f"[_speak] 调用 voice.speak({message}, wait=False)")  # 打印调试
                    # 使用非阻塞模式
                    dialogue_manager.voice.speak(message, wait=False)  # 播报消息
                    print("[_speak] voice.speak 调用完成")  # 打印完成调试
                    speak_success = True  # 设置成功标志
                else:  # 如果没有语音实例
                    logger.warning("[语音播报] voice未设置")  # 记录警告
                    print("[_speak] 警告: dialogue_manager.voice 未设置")  # 打印警告
                    # 【P0-003】voice未设置时尝试降级
                    if fallback_to_text:  # 如果允许降级
                        IntentHandler._fallback_to_text(message, "voice_not_set")  # 降级到文本
            except Exception as e:  # 捕获异常
                logger.error(f"[语音播报] 失败: {e}")  # 记录错误
                print(f"[_speak] 错误: {e}")  # 打印错误
                import traceback  # 导入追踪模块
                traceback.print_exc()  # 打印异常堆栈
                # 【P0-003】语音异常时降级到文本
                if fallback_to_text:  # 如果允许降级
                    IntentHandler._fallback_to_text(message, f"exception: {e}")  # 降级到文本

        # 启动后台线程执行语音播报，不阻塞主流程
        print(f"[_speak] 启动语音线程: {message}")  # 打印启动信息
        threading.Thread(target=do_speak, daemon=True).start()  # 创建并启动守护线程
        return speak_success  # 返回成功标志

    @staticmethod  # 定义静态方法装饰器
    def _fallback_to_text(message: str,  # 定义语音降级到文本的静态方法
                          reason: str  # 参数：降级原因
                          ):  # 返回：无
        """
        【P0-003新增】语音降级到文本处理

        当语音播报失败时，通过以下方式通知用户：
        1. 记录详细的降级日志
        2. 通过realtime_sync发送文本通知（前端可显示Toast等）
        3. 保存到工作记忆中供后续查询

        Args:  # 参数说明
            message: 原始语音消息  # 参数1
            reason: 降级原因  # 参数2
        """  # 方法文档字符串
        logger.warning(f"[语音降级] 原因: {reason}, 消息: {message[:50]}...")  # 记录警告

        try:  # 开始异常处理
            from core.sync.realtime_sync import get_realtime_sync_manager  # 导入同步管理器

            # 发送降级通知到前端
            sync = get_realtime_sync_manager()  # 获取同步管理器实例
            sync.emit_event("voice_fallback", "system", {  # 发送降级事件
                "original_message": message,  # 原始消息
                "fallback_reason": reason,  # 降级原因
                "timestamp": time.time(),  # 时间戳
                "notification": "语音播报失败，已切换到文本模式"  # 通知文本
            })

            logger.info("[语音降级] 已发送降级通知到前端")  # 记录信息
        except (ConnectionError, RuntimeError) as e:
            logger.error(f"[IntentHandler] 发送语音降级通知失败: {e}", exc_info=True)

    @staticmethod  # 定义静态方法装饰器
    def notify_voice_degraded(session_id: str,  # 定义通知语音降级的静态方法
                              user_id: str = "default"  # 参数：用户ID，默认default
                              ):  # 返回：无
        """
        【P0-003新增】通知用户语音模式已降级到文本模式

        Args:  # 参数说明
            session_id: 会话ID  # 参数1
            user_id: 用户ID  # 参数2
        """  # 方法文档字符串
        notification = "语音处理遇到问题，已自动切换到文本模式，您可以通过文字继续操作。"  # 通知消息

        logger.info(f"[语音降级通知] session_id={session_id}, user_id={user_id}")  # 记录日志

        try:  # 开始异常处理
            from core.sync.realtime_sync import get_realtime_sync_manager  # 导入同步管理器
            sync = get_realtime_sync_manager()  # 获取同步管理器实例
            sync.emit_event("mode_switched", session_id, {  # 发送模式切换事件
                "from_mode": "voice",  # 从语音模式
                "to_mode": "text",  # 切换到文本模式
                "reason": "voice_processing_error",  # 原因
                "message": notification,  # 通知消息
                "timestamp": time.time()  # 时间戳
            })
        except (ConnectionError, RuntimeError) as e:
            logger.error(f"[IntentHandler] 语音降级通知发送失败: {e}", exc_info=True)

    @staticmethod  # 定义静态方法装饰器
    def _is_tool_familiar(tool_id: str,  # 定义检查AI是否熟悉工具的静态方法
                          params: dict  # 参数：工具参数
                          ) -> bool:  # 返回：是否熟悉
        """
        检查AI是否可以执行该工具

        【2026-03-11 修复】完全放行，让AI从执行结果中学习
        不再因为参数问题阻止AI执行，而是让工具执行后返回错误信息
        这样AI可以从错误中学习正确的参数用法
        """  # 方法文档字符串
        try:  # 开始异常处理
            # 只检查工具是否存在（只要存在就允许尝试）
            tool = tool_manager.get_tool(tool_id)  # 获取工具
            if not tool:  # 如果工具不存在
                logger.info(f"[IntentHandler] 工具 {tool_id} 不存在")  # 记录日志
                return False  # 返回不熟悉（工具不存在无法执行）

            # 【修复】完全放行，不再检查参数是否齐全
            # AI即使参数不全也应该尝试执行，从错误中学习
            # 工具会在执行时检查参数并返回错误信息
            # 这比强制进入L3学习模式更符合自然学习过程

            return True  # 工具存在就允许执行

        except (AttributeError, RuntimeError) as e:
            logger.error(f"[IntentHandler] 检查工具失败: {e}", exc_info=True)
            return True  # 异常时也允许尝试执行，避免阻塞

    @staticmethod  # 定义静态方法装饰器
    async def handle_tool_call(parsed: ParsedIntent,  # 定义处理工具调用意图的静态方法
                         working_memory: WorkingMemory,  # 参数：工作记忆
                         session_id: str,  # 参数：会话ID
                         task_id: str  # 参数：任务ID
                         ) -> HandlerResult:  # 返回：处理结果
        """
        处理工具调用意图

        新增：
        1. 【主动分层导航】不熟悉工具时自动进L3学习
        2. 动态风险评估
        3. 所有操作语音播报
        4. 高风险操作等待确认（10秒×2次）

        Returns:  # 返回值说明
            HandlerResult: 处理结果字典，包含:  # 返回类型
                - result: ToolResult 工具执行结果  # 字段1
                - should_continue: bool 是否继续循环  # 字段2
                - working_memory: WorkingMemory 更新后的工作记忆  # 字段3
                - natural_language: str AI的自然语言回复（新增）  # 字段4
        """  # 方法文档字符串
        tool_id = parsed.target_tool  # 获取目标工具ID
        params = parsed.params  # 获取工具参数

        logger.info(f"[IntentHandler] 请求执行工具: {tool_id}, 参数: {params}")  # 记录日志
        print(f"[DEBUG][IntentHandler] 请求工具: {tool_id}, 参数: {params}")

        # 【步骤1】获取工具（ToolManager自动处理别名纠正）
        original_tool_id = tool_id  # 保存原始工具ID
        tool = tool_manager.get_tool(tool_id)  # 获取工具

        # 【DEBUG】检查工具是否存在
        print(f"[DEBUG][IntentHandler] 工具是否存在: {tool is not None}")
        if tool:
            print(f"[DEBUG][IntentHandler] 实际工具ID: {tool.tool_id}")
        else:
            # 列出所有可用工具供调试
            all_tools = list(tool_manager._tools.keys())[:20]  # 只显示前20个
            print(f"[DEBUG][IntentHandler] 可用工具: {all_tools}")

        # 如果ToolManager进行了纠正，tool_id会是正确的工具ID
        if not tool:  # 如果工具真的不存在
            error_msg = f"抱歉，'{original_tool_id}'工具不存在。请使用正确的工具ID如: launch_app(启动应用)、mouse_click(点击)、keyboard_input(输入)。"  # 错误消息
            logger.info(f"[IntentHandler] 工具 {original_tool_id} 不存在")  # 记录日志

            sync = get_realtime_sync_manager()  # 获取同步管理器
            sync.emit_event("tool_result", session_id, {  # 发送工具结果事件
                "tool": original_tool_id, "success": False, "message": error_msg  # 事件数据
            })
            IntentHandler._speak(SystemAnnouncements.TOOL_NOT_FOUND)  # 播报错误消息

            return {  # 返回错误结果
                "result": {"success": False, "user_message": error_msg, "error": "工具不存在"},  # 结果
                "should_continue": False,  # 不继续
                "working_memory": working_memory,  # 工作记忆
                "natural_language": getattr(parsed, 'natural_language', '')  # 新增：返回AI的自然语言回复
            }

        # 如果发生了别名纠正，更新tool_id为正确的ID
        if tool.tool_id != original_tool_id:  # 如果工具ID被纠正
            logger.info(f"[IntentHandler] 工具名已纠正: {original_tool_id} -> {tool.tool_id}")  # 记录日志
            tool_id = tool.tool_id  # 更新工具ID

        # 【步骤2】检查AI是否可以执行该工具
        # 【2026-03-11 修复】只有工具不存在时才进入L3学习，参数问题让AI从错误中学习
        if not IntentHandler._is_tool_familiar(tool_id, params):  # 如果工具不存在
            # 工具不存在，建议AI查看工具手册
            logger.info(f"[IntentHandler] 工具 {tool_id} 不存在，建议查看手册")  # 记录日志

            # 【优化】不再强制进入L3学习模式，而是返回友好错误让AI调整
            error_msg = f"工具 '{tool_id}' 不存在。可用的工具有: launch_app(启动应用)、mouse_click(点击)、keyboard_input(输入)等。输入'手册'查看所有工具。"

            sync = get_realtime_sync_manager()  # 获取同步管理器
            sync.emit_event("tool_result", session_id, {  # 发送工具结果事件
                "tool": tool_id,  # 工具ID
                "success": False,  # 失败
                "message": error_msg,  # 错误消息
                "suggestion": "输入'手册'查看可用工具列表"  # 建议
            })
            IntentHandler._speak(SystemAnnouncements.TOOL_NOT_FOUND)  # 播报

            return {  # 返回错误结果
                "result": {  # 结果
                    "success": False,  # 失败
                    "user_message": error_msg,  # 用户消息
                    "error": "TOOL_NOT_FOUND",  # 错误代码
                    "suggestion": "输入'手册'查看可用工具列表"  # 建议
                },
                "should_continue": True,  # 继续对话
                "working_memory": working_memory,  # 工作记忆
                "natural_language": getattr(parsed, 'natural_language', '')  # 新增：返回AI的自然语言回复
            }

        # 【新增】工具存在，直接执行，让AI从执行结果中学习
        # 即使参数不全，工具也会返回错误信息，AI可以根据错误调整参数
        logger.info(f"[IntentHandler] AI尝试执行 {tool_id}，参数: {params}")  # 记录日志

        # 【Agent-3】道德检查：在执行前检查AI行动是否合乎道德
        # 【Agent-2】强化异常处理：禁止静默失败
        try:
            moral_module = await get_moral_module()
            moral_passed, moral_reason = await moral_module.check_action(tool_id, params)

            if not moral_passed:
                # 道德检查未通过，阻止执行
                logger.error(f"[IntentHandler] 道德拦截: {moral_reason}")
                raise MoralViolationError(moral_reason)

        except MoralCheckError as e:
            # 【Agent-2】异常处理铁律：道德检查失败必须ERROR日志+抛错
            logger.error(f"[IntentHandler] 道德检查失败: {e}", exc_info=True)
            error_msg = f"操作 '{tool_id}' 道德检查失败: {str(e)}"
            sync = get_realtime_sync_manager()
            sync.emit_event("tool_result", session_id, {
                "tool": tool_id, "success": False, "message": error_msg,
                "blocked_by": "moral_check_error",
                "error_type": "MoralCheckError"
            })

            return {
                "result": {
                    "success": False,
                    "user_message": error_msg,
                    "error": "MORAL_CHECK_ERROR",
                    "moral_error": str(e)
                },
                "should_continue": False,
                "working_memory": working_memory,
                "natural_language": getattr(parsed, 'natural_language', '')
            }
        except MoralViolationError as e:
            # 【Agent-2】违反道德规则处理
            moral_reason = str(e)
            logger.error(f"[IntentHandler] 道德拦截: {moral_reason}", exc_info=True)
            IntentHandler._speak(DialogueAnnouncements.MORAL_REJECTED.format(reason=moral_reason))

            error_msg = f"操作 '{tool_id}' 未通过道德审查: {moral_reason}"
            sync = get_realtime_sync_manager()
            sync.emit_event("tool_result", session_id, {
                "tool": tool_id, "success": False, "message": error_msg,
                "blocked_by": "moral_check",
                "error_type": "MoralViolationError"
            })

            return {
                "result": {
                    "success": False,
                    "user_message": error_msg,
                    "error": "MORAL_VIOLATION",
                    "moral_reason": moral_reason
                },
                "should_continue": False,
                "working_memory": working_memory,
                "natural_language": getattr(parsed, 'natural_language', '')
            }

        # 1. 评估风险等级
        risk = await assess_operation_risk(tool_id, params, session_id)  # 评估操作风险

        # 2. 所有操作都语音播报（让用户知道在做什么）
        if risk.level == RiskLevel.CONFIRM:  # 如果需要确认
            IntentHandler._speak(DialogueAnnouncements.RISK_CONFIRM.format(reason=risk.reason))  # 播报确认请求
        elif risk.level == RiskLevel.NOTICE:  # 如果只是通知
            IntentHandler._speak(risk.reason)  # 播报原因

        # 3. 高风险操作：等待确认
        if risk.level == RiskLevel.CONFIRM:  # 如果需要确认
            sync = get_realtime_sync_manager()  # 获取同步管理器

            # 发送确认请求到前端
            sync.emit_event("confirm_required", session_id, {  # 发送确认请求事件
                "tool_id": tool_id,  # 工具ID
                "params": params,  # 参数
                "reason": risk.reason,  # 原因
                "wait_seconds": risk.wait_seconds  # 等待秒数
            })

            # 等待10秒
            confirmed = IntentHandler._wait_for_confirmation(  # 等待确认
                session_id, tool_id, risk.reason, risk.wait_seconds  # 传入参数
            )

            if not confirmed:  # 如果第一次未确认
                # 第一次等待超时，再播报一次
                IntentHandler._speak(DialogueAnnouncements.RISK_FINAL_WARNING.format(reason=risk.reason))  # 再次播报
                confirmed = IntentHandler._wait_for_confirmation(  # 再次等待
                    session_id, tool_id, risk.reason, 10  # 再等待10秒
                )

                if not confirmed:  # 如果两次都没确认
                    # 两次都没确认，中止并记录
                    logger.info(f"[IntentHandler] {tool_id} 等待确认超时，中止执行")  # 记录日志
                    IntentHandler._speak(SystemAnnouncements.OPERATION_CANCELLED)  # 播报中止

                    # 存入记忆：这次被中止了（以后更谨慎）
                    loop = asyncio.get_event_loop()
                    asyncio.run_coroutine_threadsafe(
                        IntentHandler._store_cancelled_memory_async(tool_id), loop
                    ).result()

                    return {  # 返回超时结果
                        "result": {  # 结果
                            "success": False,  # 失败
                            "user_message": f"操作已取消：等待确认超时（{tool_id}）",  # 消息
                            "cancelled": True  # 取消标志
                        },
                        "should_continue": False,  # 不继续
                        "working_memory": working_memory,  # 工作记忆
                        "natural_language": getattr(parsed, 'natural_language', '')  # 新增：返回AI的自然语言回复
                    }

        # 4. 执行工具
        logger.info(f"[IntentHandler] 执行 {tool_id}")  # 记录日志
        print(f"[DEBUG] 即将调用 tool_manager.call_tool: {tool_id}")  # 打印调试

        # 【Phase 4 顺手修复 04-条目27】工具执行前检查中断信号
        try:
            from core.agent.interrupt_handler import interrupt_handler
            if interrupt_handler and interrupt_handler.is_interrupted(task_id):
                logger.warning(f"[IntentHandler] 工具 {tool_id} 执行前检测到中断信号，中止执行")
                return {
                    "result": {
                        "success": False,
                        "error_code": "INTERRUPTED",
                        "user_message": f"工具 {tool_id} 执行被用户中断"
                    },
                    "should_continue": False,
                    "working_memory": working_memory,
                    "natural_language": getattr(parsed, 'natural_language', '')
                }
        except Exception as e:
            logger.debug(f"[IntentHandler] 中断检查失败（非阻塞）: {e}")

        try:  # 开始异常处理
            # 【游戏化修复】传递 user_id 用于经验值记录
            user_id_for_gamification = session_id if session_id != "console" else "default_user"
            result = await tool_manager.call_tool(tool_id, params, source="user", user_id=user_id_for_gamification)  # 调用工具
            print(f"[DEBUG] tool_manager.call_tool 返回: success={result.get('success')}, error_code={result.get('error_code')}")  # 打印结果

            # 【Stop Hooks】记录工具执行历史
            try:
                from core.task.task_orchestrator import task_orchestrator
                from core.task.task_queue import task_queue
                current_task = task_queue.current_task()
                if current_task:
                    task_orchestrator.record_tool_execution(
                        current_task.id, tool_id, params, result
                    )
            except (ImportError, AttributeError, RuntimeError) as e:
                logger.error(f"[IntentHandler] [Stop Hooks] 记录工具执行失败: {e}", exc_info=True)

        except Exception as e:  # 捕获异常
            print(f"[DEBUG] tool_manager.call_tool 异常: {e}")  # 打印异常
            import traceback  # 导入追踪模块
            traceback.print_exc()  # 打印异常堆栈
            result = {"success": False, "error_code": "EXCEPTION", "user_message": str(e)}  # 构建错误结果


        # 【SILENT_FAILURE_BLOCKED】防御性检查：确保result不为None
        if result is None:
            logger.error("[SILENT_FAILURE_BLOCKED] tool_manager.call_tool 返回None，强制转换为错误结果")
            result = {"success": False, "error_code": "NULL_RESULT", "user_message": "工具执行返回空结果"}

        # 【Phase 4 顺手修复 04-条目27】工具执行后检查中断信号
        try:
            from core.agent.interrupt_handler import interrupt_handler
            if interrupt_handler and interrupt_handler.is_interrupted(task_id):
                logger.warning(f"[IntentHandler] 工具 {tool_id} 执行后检测到中断信号，丢弃结果")
                result = {
                    "success": False,
                    "error_code": "INTERRUPTED",
                    "user_message": f"工具 {tool_id} 执行被用户中断"
                }
        except Exception as e:
            logger.debug(f"[IntentHandler] 执行后中断检查失败（非阻塞）: {e}")

        # 5. 执行后播报结果
        # 获取工具友好名称（P1修复：语音播报机械化问题）
        friendly_name = TOOL_NAME_MAP.get(tool_id, tool_id)
        if result.get("success"):  # 如果执行成功
            IntentHandler._speak(DialogueAnnouncements.TOOL_EXEC_SUCCESS.format(friendly_name=friendly_name))  # 播报成功
        else:  # 如果执行失败
            error_msg = result.get("user_message", "执行失败")  # 获取错误消息（仅用于日志记录，不播报）
            IntentHandler._speak(DialogueAnnouncements.TOOL_EXEC_FAILED.format(friendly_name=friendly_name))  # 播报失败（不播报具体英文错误信息）

            # 记录事故（以后更谨慎）
            from core.safety.safety_guard import safety_guard  # 导入安全守卫
            user_id = session_id if session_id != "console" else "default"  # 确定用户ID
            await safety_guard.record_accident(user_id, tool_id, error_msg)  # 记录事故

        # ========== 游戏化经验值记录 ==========
        if result.get("success"):
            try:
                from api.gamification_api import _calculate_level, _load_gamification_data, _save_gamification_data

                # 标准化用户ID
                user_id_for_gamification = session_id if session_id and session_id != "console" else "default_user"

                # 加载数据
                data = _load_gamification_data()
                if user_id_for_gamification not in data:
                    data[user_id_for_gamification] = {
                        "level": 1, "xp": 0, "total_xp_earned": 0,
                        "tools_used": {}, "categories_unlocked": [],
                        "achievements": [], "created_at": time.time(),
                        "last_active": time.time()
                    }

                user_data = data[user_id_for_gamification]

                # 记录工具使用
                if tool_id not in user_data["tools_used"]:
                    user_data["tools_used"][tool_id] = 0
                user_data["tools_used"][tool_id] += 1

                # 计算经验值
                xp_earned = 10
                is_first_use = user_data["tools_used"][tool_id] == 1
                if is_first_use:
                    xp_earned += 50

                # 更新经验值
                old_level = _calculate_level(user_data["xp"])
                user_data["xp"] += xp_earned
                user_data["total_xp_earned"] += xp_earned
                user_data["last_active"] = time.time()
                new_level = _calculate_level(user_data["xp"])

                # 保存数据
                _save_gamification_data(data)

                # 发送WebSocket事件
                sync = get_realtime_sync_manager()
                sync.emit_event("xp_earned", session_id or user_id_for_gamification, {
                    "xp_earned": xp_earned,
                    "tool_id": tool_id,
                    "total_xp": user_data["xp"],
                    "level_up": new_level > old_level,
                    "new_level": new_level if new_level > old_level else None
                })

                # 如果升级，额外发送level_up事件
                if new_level > old_level:
                    sync.emit_event("level_up", session_id or user_id_for_gamification, {
                        "old_level": old_level,
                        "new_level": new_level,
                        "message": f"恭喜！你升级到等级 {new_level}！"
                    })

                logger.info(f"[Gamification] 工具 {tool_id} 使用记录，用户 {user_id_for_gamification} 获得 {xp_earned} XP")

            except Exception as e:
                logger.error(f"[SILENT_FAILURE_BLOCKED] [Gamification] 记录工具使用经验值失败: {e}")
                # 不抛出异常，不影响主流程

        # 6. 更新工作记忆
        result_summary = result.get("user_message", "")[:30]  # 获取结果摘要（截断）
        working_memory.update_after_tool(  # 更新工作记忆
            tool_id,  # 工具ID
            result.get("success", False),  # 是否成功
            result_summary  # 结果摘要
        )

        # 【Phase1-Week1集成】MemoryAutoTrigger: 异步存储工具执行
        async def _trigger_tool_execution_storage():
            try:
                from core.memory.memory_auto_trigger import MemoryAutoTrigger
                user_id = session_id if session_id != "console" else "default_user"
                session_id_safe = session_id if session_id else f"session_{user_id}"

                await MemoryAutoTrigger.on_tool_execution(
                    user_id=user_id,
                    session_id=session_id_safe,
                    tool_name=tool_id,
                    params=params,
                    result=result,
                    execution_time_ms=0,  # 工具执行时间可由tool_manager补充
                    metadata={
                        "source": "intent_handler",
                        "task_id": task_id,
                        "execution_status": "success" if result.get("success") else "failed"
                    }
                )
                logger.info(f"[MemoryAutoTrigger] 工具执行存储成功: user={user_id}, tool={tool_id}")
            except Exception as e:
                logger.error(f"[MemoryAutoTrigger] 工具执行存储失败: {e}", exc_info=True)

        safe_create_task(_trigger_tool_execution_storage(), name="_trigger_tool_execution_storage")

        return {  # 返回处理结果
            "result": result,  # 工具执行结果
            "should_continue": True,  # 继续
            "working_memory": working_memory,  # 工作记忆
            "natural_language": getattr(parsed, 'natural_language', '')  # 新增：返回AI的自然语言回复
        }

    @staticmethod
    async def _store_cancelled_memory_async(tool_id: str):
        """存储操作被取消的记忆"""
        try:
            ms = await get_memory_service()
            await ms.add_memory(
                user_id="default",
                content=f"准备执行{tool_id}时等待确认超时，用户未回应",
                memory_type="experience",
                layer="short",
                scene="operation_cancelled",
                rating=3,
                source=MemorySource.SYSTEM
            )
        except Exception as e:
            logger.error(f"[IntentHandler] 存储取消记忆失败: {e}")

    @staticmethod
    async def handle_tool_call_async(
        parsed: ParsedIntent,
        working_memory: WorkingMemory,
        session_id: str,
        task_id: str
    ) -> HandlerResult:
        """
        异步处理工具调用意图（Phase 4 重写为原生 async/await 调用链）。

        改造策略：
        - 工具执行核心链路改为 `await tool_manager.execute_tool_async()`，
          充分利用已 async 化的高频工具。
        - 道德检查、风险评估、事故记录等安全模块调用已改为原生 `await`。
        - `_speak` 本身已使用后台线程，无需额外包装。
        """

        tool_id = parsed.target_tool
        params = parsed.params

        logger.info(f"[IntentHandler-Async] 请求执行工具: {tool_id}, 参数: {params}")
        print(f"[DEBUG][IntentHandler-Async] 请求工具: {tool_id}, 参数: {params}")

        # 【步骤1】获取工具（纯内存操作，无需 to_thread）
        original_tool_id = tool_id
        tool = tool_manager.get_tool(tool_id)
        print(f"[DEBUG][IntentHandler-Async] 工具是否存在: {tool is not None}")
        if tool:
            print(f"[DEBUG][IntentHandler-Async] 实际工具ID: {tool.tool_id}")
        else:
            all_tools = list(tool_manager._tools.keys())[:20]
            print(f"[DEBUG][IntentHandler-Async] 可用工具: {all_tools}")

        if not tool:
            error_msg = f"抱歉，'{original_tool_id}'工具不存在。请使用正确的工具ID如: launch_app(启动应用)、mouse_click(点击)、keyboard_input(输入)。"
            logger.info(f"[IntentHandler-Async] 工具 {original_tool_id} 不存在")
            sync = get_realtime_sync_manager()
            sync.emit_event("tool_result", session_id, {
                "tool": original_tool_id, "success": False, "message": error_msg
            })
            IntentHandler._speak(error_msg)
            return {
                "result": {"success": False, "user_message": error_msg, "error": "工具不存在"},
                "should_continue": False,
                "working_memory": working_memory,
                "natural_language": getattr(parsed, 'natural_language', '')
            }

        if tool.tool_id != original_tool_id:
            logger.info(f"[IntentHandler-Async] 工具名已纠正: {original_tool_id} -> {tool.tool_id}")
            tool_id = tool.tool_id

        # 【步骤2】检查AI是否可以执行该工具
        if not IntentHandler._is_tool_familiar(tool_id, params):
            error_msg = f"工具 '{tool_id}' 不存在。可用的工具有: launch_app(启动应用)、mouse_click(点击)、keyboard_input(输入)等。输入'手册'查看所有工具。"
            sync = get_realtime_sync_manager()
            sync.emit_event("tool_result", session_id, {
                "tool": tool_id, "success": False, "message": error_msg,
                "suggestion": "输入'手册'查看可用工具列表"
            })
            IntentHandler._speak(SystemAnnouncements.TOOL_NOT_FOUND)
            return {
                "result": {
                    "success": False, "user_message": error_msg,
                    "error": "TOOL_NOT_FOUND", "suggestion": "输入'手册'查看可用工具列表"
                },
                "should_continue": True,
                "working_memory": working_memory,
                "natural_language": getattr(parsed, 'natural_language', '')
            }

        logger.info(f"[IntentHandler-Async] AI尝试执行 {tool_id}，参数: {params}")

        # 【Agent-3】道德检查（原生 await）
        try:
            moral_module = await get_moral_module()
            moral_passed, moral_reason = await moral_module.check_action(tool_id, params)
            if not moral_passed:
                logger.error(f"[IntentHandler-Async] 道德拦截: {moral_reason}")
                raise MoralViolationError(moral_reason)
        except MoralCheckError as e:
            logger.error(f"[IntentHandler-Async] 道德检查失败: {e}", exc_info=True)
            error_msg = f"操作 '{tool_id}' 道德检查失败: {str(e)}"
            sync = get_realtime_sync_manager()
            sync.emit_event("tool_result", session_id, {
                "tool": tool_id, "success": False, "message": error_msg,
                "blocked_by": "moral_check_error", "error_type": "MoralCheckError"
            })
            return {
                "result": {
                    "success": False, "user_message": error_msg,
                    "error": "MORAL_CHECK_ERROR", "moral_error": str(e)
                },
                "should_continue": False,
                "working_memory": working_memory,
                "natural_language": getattr(parsed, 'natural_language', '')
            }
        except MoralViolationError as e:
            moral_reason = str(e)
            logger.error(f"[IntentHandler-Async] 道德拦截: {moral_reason}", exc_info=True)
            IntentHandler._speak(DialogueAnnouncements.MORAL_REJECTED.format(reason=moral_reason))
            error_msg = f"操作 '{tool_id}' 未通过道德审查: {moral_reason}"
            # 【ExperienceBus】道德拦截事件
            with contextlib.suppress(Exception):
                event_bus.emit("intent:moral_blocked", {
                    "session_id": session_id,
                    "tool_id": tool_id,
                    "moral_reason": moral_reason,
                    "timestamp": time.time(),
                })
            sync = get_realtime_sync_manager()
            sync.emit_event("tool_result", session_id, {
                "tool": tool_id, "success": False, "message": error_msg,
                "blocked_by": "moral_check", "error_type": "MoralViolationError"
            })
            return {
                "result": {
                    "success": False, "user_message": error_msg,
                    "error": "MORAL_VIOLATION", "moral_reason": moral_reason
                },
                "should_continue": False,
                "working_memory": working_memory,
                "natural_language": getattr(parsed, 'natural_language', '')
            }

        # 1. 评估风险等级（原生 await）
        risk = await assess_operation_risk(tool_id, params, session_id)

        # 2. 语音播报
        if risk.level == RiskLevel.CONFIRM:
            IntentHandler._speak(DialogueAnnouncements.RISK_CONFIRM.format(reason=risk.reason))
        elif risk.level == RiskLevel.NOTICE:
            IntentHandler._speak(risk.reason)

        # 3. 高风险操作：等待确认（to_thread 包装，避免阻塞事件循环）
        if risk.level == RiskLevel.CONFIRM:
            sync = get_realtime_sync_manager()
            sync.emit_event("confirm_required", session_id, {
                "tool_id": tool_id, "params": params,
                "reason": risk.reason, "wait_seconds": risk.wait_seconds
            })

            confirmed = await asyncio.to_thread(
                IntentHandler._wait_for_confirmation,
                session_id, tool_id, risk.reason, risk.wait_seconds
            )

            if not confirmed:
                IntentHandler._speak(DialogueAnnouncements.RISK_FINAL_WARNING.format(reason=risk.reason))
                confirmed = await asyncio.to_thread(
                    IntentHandler._wait_for_confirmation,
                    session_id, tool_id, risk.reason, 10
                )

                if not confirmed:
                    logger.info(f"[IntentHandler-Async] {tool_id} 等待确认超时，中止执行")
                    IntentHandler._speak(SystemAnnouncements.OPERATION_CANCELLED)
                    # 【P1修复】使用新 MemoryManager.add()，移除 to_thread 桥接
                    from core.memory.memory_manager import MemoryManager
                    mm = MemoryManager()
                    await mm.add(
                        user_id="default",
                        layer="short",
                        content={"text": f"准备执行{tool_id}时等待确认超时，用户未回应"},
                        mem_type="experience",
                        scene="operation_cancelled",
                        rating=3,
                        source="system"
                    )
                    return {
                        "result": {
                            "success": False,
                            "user_message": f"操作已取消：等待确认超时（{tool_id}）",
                            "cancelled": True
                        },
                        "should_continue": False,
                        "working_memory": working_memory,
                        "natural_language": getattr(parsed, 'natural_language', '')
                    }

        # 4. 执行工具
        logger.info(f"[IntentHandler-Async] 执行 {tool_id}")
        print(f"[DEBUG] 即将调用 tool_manager.execute_tool_async: {tool_id}")

        # 【Phase 4 顺手修复 04-条目27】工具执行前检查中断信号
        try:
            from core.agent.interrupt_handler import interrupt_handler
            if interrupt_handler and interrupt_handler.is_interrupted(task_id):
                logger.warning(f"[IntentHandler-Async] 工具 {tool_id} 执行前检测到中断信号，中止执行")
                return {
                    "result": {
                        "success": False, "error_code": "INTERRUPTED",
                        "user_message": f"工具 {tool_id} 执行被用户中断"
                    },
                    "should_continue": False,
                    "working_memory": working_memory,
                    "natural_language": getattr(parsed, 'natural_language', '')
                }
        except Exception as e:
            logger.debug(f"[IntentHandler-Async] 中断检查失败（非阻塞）: {e}")

        try:
            user_id_for_gamification = session_id if session_id != "console" else "default_user"
            # ★★★ Phase 4 核心改造：走原生 async 工具执行链路 ★★★
            result = await tool_manager.execute_tool_async(
                tool_id=tool_id,
                params=params,
                source="user",
                task_id=task_id,
                user_id=user_id_for_gamification
            )
            print(f"[DEBUG] tool_manager.execute_tool_async 返回: success={result.get('success')}, error_code={result.get('error_code')}")

            # 【Stop Hooks】记录工具执行历史
            try:
                from core.task.task_orchestrator import task_orchestrator
                from core.task.task_queue import task_queue
                current_task = task_queue.current_task()
                if current_task:
                    task_orchestrator.record_tool_execution(
                        current_task.id, tool_id, params, result
                    )
            except (ImportError, AttributeError, RuntimeError) as e:
                logger.error(f"[IntentHandler-Async] [Stop Hooks] 记录工具执行失败: {e}", exc_info=True)

        except Exception as e:
            print(f"[DEBUG] tool_manager.execute_tool_async 异常: {e}")
            import traceback
            traceback.print_exc()
            result = {"success": False, "error_code": "EXCEPTION", "user_message": str(e)}

        if result is None:
            logger.error("[SILENT_FAILURE_BLOCKED] tool_manager.execute_tool_async 返回None，强制转换为错误结果")
            result = {"success": False, "error_code": "NULL_RESULT", "user_message": "工具执行返回空结果"}

        # 【Phase 4 顺手修复 04-条目27】工具执行后检查中断信号
        try:
            from core.agent.interrupt_handler import interrupt_handler
            if interrupt_handler and interrupt_handler.is_interrupted(task_id):
                logger.warning(f"[IntentHandler-Async] 工具 {tool_id} 执行后检测到中断信号，丢弃结果")
                result = {
                    "success": False, "error_code": "INTERRUPTED",
                    "user_message": f"工具 {tool_id} 执行被用户中断"
                }
        except Exception as e:
            logger.debug(f"[IntentHandler-Async] 执行后中断检查失败（非阻塞）: {e}")

        # 5. 执行后播报结果
        friendly_name = TOOL_NAME_MAP.get(tool_id, tool_id)
        if result.get("success"):
            IntentHandler._speak(DialogueAnnouncements.TOOL_EXEC_SUCCESS.format(friendly_name=friendly_name))
        else:
            error_msg = result.get("user_message", "执行失败")  # 获取错误消息（仅用于日志记录，不播报）
            IntentHandler._speak(DialogueAnnouncements.TOOL_EXEC_FAILED.format(friendly_name=friendly_name))
            from core.safety.safety_guard import safety_guard
            user_id = session_id if session_id != "console" else "default"
            await safety_guard.record_accident(user_id, tool_id, error_msg)

        # ========== 游戏化经验值记录 ==========
        if result.get("success"):
            try:
                from api.gamification_api import (
                    _calculate_level,
                    _load_gamification_data_async,
                    _save_gamification_data_async,
                )

                user_id_for_gamification = session_id if session_id and session_id != "console" else "default_user"

                data = await _load_gamification_data_async()
                if user_id_for_gamification not in data:
                    data[user_id_for_gamification] = {
                        "level": 1, "xp": 0, "total_xp_earned": 0,
                        "tools_used": {}, "categories_unlocked": [],
                        "achievements": [], "created_at": time.time(),
                        "last_active": time.time()
                    }
                user_data = data[user_id_for_gamification]
                if tool_id not in user_data["tools_used"]:
                    user_data["tools_used"][tool_id] = 0
                user_data["tools_used"][tool_id] += 1
                xp_earned = 10
                is_first_use = user_data["tools_used"][tool_id] == 1
                if is_first_use:
                    xp_earned += 50
                old_level = _calculate_level(user_data["xp"])
                user_data["xp"] += xp_earned
                user_data["total_xp_earned"] += xp_earned
                user_data["last_active"] = time.time()
                new_level = _calculate_level(user_data["xp"])
                await _save_gamification_data_async(data)

                sync = get_realtime_sync_manager()
                sync.emit_event("xp_earned", session_id or user_id_for_gamification, {
                    "xp_earned": xp_earned, "tool_id": tool_id,
                    "total_xp": user_data["xp"],
                    "level_up": new_level > old_level,
                    "new_level": new_level if new_level > old_level else None
                })
                if new_level > old_level:
                    sync.emit_event("level_up", session_id or user_id_for_gamification, {
                        "old_level": old_level, "new_level": new_level,
                        "message": f"恭喜！你升级到等级 {new_level}！"
                    })
                logger.info(f"[Gamification] 工具 {tool_id} 使用记录，用户 {user_id_for_gamification} 获得 {xp_earned} XP")
            except Exception as e:
                logger.error(f"[SILENT_FAILURE_BLOCKED] [Gamification] 记录工具使用经验值失败: {e}")

        # 【ExperienceBus】工具执行结果
        with contextlib.suppress(Exception):
            event_bus.emit("intent:tool_executed", {
                "session_id": session_id,
                "tool_id": tool_id,
                "success": result.get("success", False),
                "error_code": result.get("error_code", ""),
                "timestamp": time.time(),
            })

        # 6. 更新工作记忆（纯内存操作，无需 to_thread）
        result_summary = result.get("user_message", "")[:30]
        working_memory.update_after_tool(
            tool_id, result.get("success", False), result_summary
        )

        # 【Phase1-Week1集成】MemoryTrigger: 异步存储工具执行（直接 await，已切至 MemoryService）
        async def _trigger_tool_execution_storage_async():
            try:
                user_id = session_id if session_id != "console" else "default_user"
                session_id_safe = session_id if session_id else f"session_{user_id}"
                result_store = await on_tool_execution_async(
                    user_id=user_id,
                    session_id=session_id_safe,
                    tool_name=tool_id,
                    params=params,
                    result=result,
                    execution_time_ms=0,
                    metadata={
                        "source": "intent_handler",
                        "task_id": task_id,
                        "execution_status": "success" if result.get("success") else "failed"
                    }
                )
                if result_store == "stored":
                    logger.info(f"[MemoryTrigger] 工具执行存储成功: user={user_id}, tool={tool_id}")
                else:
                    logger.warning(f"[MemoryTrigger] 工具执行存储返回非成功状态: {result_store}")
            except Exception as e:
                logger.error(f"[MemoryTrigger] 工具执行存储失败: {e}", exc_info=True)

        # 启动后台任务，不 await（fire-and-forget）
        safe_create_task(_trigger_tool_execution_storage_async(), name="_trigger_tool_execution_storage_async")

        return {
            "result": result,
            "should_continue": True,
            "working_memory": working_memory,
            "natural_language": getattr(parsed, 'natural_language', '')
        }

    @staticmethod  # 定义静态方法装饰器
    def _wait_for_confirmation(session_id: str,  # 定义等待用户确认的静态方法
                               tool_id: str,  # 参数：工具ID
                               reason: str,  # 参数：原因
                               seconds: int  # 参数：超时秒数
                               ) -> bool:  # 返回：是否确认
        """
        等待用户确认（P0-011 修复：真正实现异步确认）

        流程：
        1. 创建确认请求
        2. 通过WebSocket发送确认请求到前端
        3. 异步等待用户响应（确认/拒绝/超时）
        4. 返回结果：确认=True, 拒绝/超时=False

        Args:  # 参数说明
            session_id: 会话ID  # 参数1
            tool_id: 工具ID  # 参数2
            reason: 确认原因（显示给用户）  # 参数3
            seconds: 超时时间（秒）  # 参数4

        Returns:  # 返回值说明
            bool: True=用户确认, False=拒绝或超时  # 返回类型
        """  # 方法文档字符串
        from core.sync.realtime_sync import get_realtime_sync_manager  # 导入同步管理器

        sync = get_realtime_sync_manager()  # 获取同步管理器实例

        # 创建确认请求
        request_id = confirmation_manager.create_request(  # 创建确认请求
            session_id=session_id,  # 会话ID
            tool_id=tool_id,  # 工具ID
            reason=reason,  # 原因
            timeout_seconds=seconds  # 超时秒数
        )

        # 发送确认请求到前端（通过realtime_sync广播）
        sync.emit_event("confirm_request", session_id, {  # 发送确认请求事件
            "request_id": request_id,  # 请求ID
            "tool_id": tool_id,  # 工具ID
            "reason": reason,  # 原因
            "timeout_seconds": seconds,  # 超时秒数
            "timestamp": time.time()  # 时间戳
        })

        logger.info(f"[_wait_for_confirmation] 等待确认: request_id={request_id}, timeout={seconds}s")  # 记录日志

        # 等待用户响应
        result = confirmation_manager.wait_for_response(request_id)  # 等待响应

        # 获取最终结果状态
        request = confirmation_manager.get_request(request_id)  # 获取请求
        status = request.status.value if request else "unknown"  # 获取状态

        logger.info(f"[_wait_for_confirmation] 确认结果: request_id={request_id}, result={result}, status={status}")  # 记录日志

        # 广播确认结果（供前端更新UI）
        sync.emit_event("confirm_result", session_id, {  # 发送确认结果事件
            "request_id": request_id,  # 请求ID
            "tool_id": tool_id,  # 工具ID
            "confirmed": result,  # 是否确认
            "status": status  # 状态
        })

        return result  # 返回确认结果

    @staticmethod  # 定义静态方法装饰器
    def handle_final_answer(parsed: ParsedIntent,  # 定义处理最终答案意图的静态方法
                           working_memory: WorkingMemory  # 参数：工作记忆
                           ) -> HandlerResult:  # 返回：处理结果
        """
        处理最终答案意图

        Returns:  # 返回值说明
            HandlerResult: 处理结果字典，包含:  # 返回类型
                - answer: str AI的回答  # 字段1
                - should_continue: bool 是否继续循环  # 字段2
                - working_memory: WorkingMemory 更新后的工作记忆  # 字段3
        """  # 方法文档字符串
        answer = parsed.raw_instruction  # 获取原始指令作为答案

        # 自然语言回复也播报
        if answer:  # 如果有答案
            # 清理后播报（去掉JSON等）
            clean_answer = IntentHandler._extract_natural_language(answer)  # 提取自然语言
            if clean_answer and len(clean_answer) > 5:  # 如果清理后有内容且长度>5
                IntentHandler._speak(clean_answer[:100])  # 播报前100字

        return {  # 返回结果
            "answer": answer,  # 答案
            "should_continue": False,  # 不继续
            "working_memory": working_memory  # 工作记忆
        }

    @staticmethod  # 定义静态方法装饰器
    def _extract_natural_language(text: str) -> str:  # 定义提取自然语言的静态方法
        """从响应中提取自然语言（简化版）"""  # 方法文档字符串
        import re  # 导入正则模块
        # 去掉JSON代码块
        text = re.sub(r'```[\s\S]*?```', '', text)  # 替换代码块为空
        # 去掉行内代码
        text = re.sub(r'`[^`]*`', '', text)  # 替换行内代码为空
        # 去掉URL
        text = re.sub(r'https?://\S+', '', text)  # 替换URL为空
        # 【修复】过滤内部控制标记，避免语音播报把系统标记念给用户
        text = re.sub(r'\[TASK_COMPLETE\]', '', text)
        text = re.sub(r'\[TOOL\]', '', text)
        return text.strip()[:150]  # 返回截断后的文本

    @staticmethod  # 定义静态方法装饰器
    def handle_plan(parsed: ParsedIntent,  # 定义处理计划意图的静态方法
                    working_memory: WorkingMemory,  # 参数：工作记忆
                    session_id: str,  # 参数：会话ID
                    task_id: str,  # 参数：任务ID
                    priority: int  # 参数：优先级
                    ) -> HandlerResult:  # 返回：处理结果
        """
        处理计划意图 - 存储AI设计的计划到working_memory

        Returns:  # 返回值说明
            HandlerResult: 处理结果字典，包含:  # 返回类型
                - answer: str 计划确认消息  # 字段1
                - should_continue: bool 是否继续循环  # 字段2
                - working_memory: WorkingMemory 更新后的工作记忆  # 字段3
        """  # 方法文档字符串
        # 转换步骤数据
        steps_data = []  # 初始化步骤数据列表
        for step in parsed.steps:  # 遍历步骤
            if hasattr(step, '__dict__'):  # 如果步骤有__dict__属性
                steps_data.append(step.__dict__)  # 添加字典形式
            elif isinstance(step, dict):  # 如果步骤是字典
                steps_data.append(step)  # 直接添加
            else:  # 其他类型
                steps_data.append({"step": str(step)})  # 转为字符串后添加

        # [连接修复] 存储计划到 working_memory，供后续步骤使用
        working_memory.ai_plan = {  # 设置AI计划
            "task_id": task_id,  # 任务ID
            "steps": steps_data,  # 步骤列表
            "current_step": 0,  # 从第1步开始（索引0）
            "total_steps": len(steps_data)  # 总步骤数
        }

        # [Planner] 任务5：存储计划ID到 working_memory 用于后续步骤更新
        working_memory.ai_plan_id = task_id  # 设置计划ID
        working_memory.current_step_index = 0  # 设置当前步骤索引

        # 播报计划
        IntentHandler._speak(f"收到计划，共{len(steps_data)}个步骤")  # 播报步骤数

        return {  # 返回结果
            "answer": f"收到计划，共{len(steps_data)}个步骤。请开始执行第1步。",  # 答案消息
            "should_continue": True,  # 继续循环，执行计划
            "working_memory": working_memory  # 工作记忆
        }

    @staticmethod  # 定义静态方法装饰器
    def handle_query_tool_list(parsed: ParsedIntent,  # 定义处理查询工具列表的静态方法
                              working_memory: WorkingMemory  # 参数：工作记忆
                              ) -> HandlerResult:  # 返回：处理结果
        """
        处理查询工具列表命令 - 进入 Layer 2

        Returns:  # 返回值说明
            HandlerResult: 处理结果字典，包含:  # 返回类型
                - should_continue: bool 是否继续循环  # 字段1
                - working_memory: WorkingMemory 更新后的工作记忆  # 字段2
        """  # 方法文档字符串
        category = parsed.params.get("category")  # 获取分类参数

        if not category:  # 如果没有分类
            logger.warning("[IntentHandler] 查询工具列表命令缺少 category 参数")  # 记录警告
            return {"should_continue": True, "working_memory": working_memory}  # 返回继续

        logger.info(f"[IntentHandler] 进入Layer 2: 分类={category}")  # 记录日志

        # 【P0-2修复】统一层级切换语音播报
        IntentHandler._speak(SystemAnnouncements.QUERYING)

        working_memory.query_stage = "layer2"  # 设置查询阶段为L2
        working_memory.current_category = category  # 设置当前分类
        working_memory.current_tool = None  # 清空当前工具

        return {"should_continue": True, "working_memory": working_memory}  # 返回继续

    @staticmethod  # 定义静态方法装饰器
    def handle_query_tool_detail(parsed: ParsedIntent,  # 定义处理查询工具详情的静态方法
                                working_memory: WorkingMemory  # 参数：工作记忆
                                ) -> HandlerResult:  # 返回：处理结果
        """
        处理查询工具详情命令 - 进入 Layer 3

        Returns:  # 返回值说明
            HandlerResult: 处理结果字典，包含:  # 返回类型
                - should_continue: bool 是否继续循环  # 字段1
                - working_memory: WorkingMemory 更新后的工作记忆  # 字段2
        """  # 方法文档字符串
        tool_id = parsed.params.get("tool_id")  # 获取工具ID参数

        if not tool_id:  # 如果没有工具ID
            logger.warning("[IntentHandler] 查询工具详情命令缺少 tool_id 参数")  # 记录警告
            return {"should_continue": True, "working_memory": working_memory}  # 返回继续

        logger.info(f"[IntentHandler] 进入Layer 3: 工具={tool_id}")  # 记录日志

        # 【P0-2修复】统一层级切换语音播报
        IntentHandler._speak(SystemAnnouncements.QUERYING)

        working_memory.query_stage = "layer3"  # 设置查询阶段为L3
        working_memory.current_tool = tool_id  # 设置当前工具

        return {"should_continue": True, "working_memory": working_memory}  # 返回继续

    @staticmethod  # 定义静态方法装饰器
    def handle_back(parsed: ParsedIntent,  # 定义处理返回命令的静态方法
                    working_memory: WorkingMemory  # 参数：工作记忆
                    ) -> HandlerResult:  # 返回：处理结果
        """
        处理返回命令 - 支持 L3→L2 或 L3→L1

        Returns:  # 返回值说明
            HandlerResult: 处理结果字典，包含:  # 返回类型
                - should_continue: bool 是否继续循环  # 字段1
                - working_memory: WorkingMemory 更新后的工作记忆  # 字段2
        """  # 方法文档字符串
        current_stage = working_memory.query_stage  # 获取当前阶段
        target = parsed.params.get("target", "prev")  # 获取目标参数，默认prev

        if current_stage == "layer3":  # 如果在L3
            if target == "home":  # 如果目标是首页
                # L3 直接返回 L1（首页）
                # 【P0-2修复】统一层级切换语音播报
                IntentHandler._speak(SystemAnnouncements.QUERYING)
                working_memory.query_stage = "layer1"  # 设置阶段为L1
                working_memory.current_category = None  # 清空分类
                working_memory.current_tool = None  # 清空工具
                logger.info("[IntentHandler] 从Layer 3直接返回Layer 1(首页)")  # 记录日志
            else:  # 否则返回上一层
                # L3 返回 L2
                # 【P0-2修复】统一层级切换语音播报
                IntentHandler._speak(SystemAnnouncements.QUERYING)
                working_memory.query_stage = "layer2"  # 设置阶段为L2
                working_memory.current_tool = None  # 清空工具
                logger.info("[IntentHandler] 从Layer 3返回Layer 2")  # 记录日志

        elif current_stage == "layer2":  # 如果在L2
            # L2 返回 L1
            # 【P0-2修复】统一层级切换语音播报
            IntentHandler._speak(SystemAnnouncements.QUERYING)
            working_memory.query_stage = "layer1"  # 设置阶段为L1
            working_memory.current_category = None  # 清空分类
            logger.info("[IntentHandler] 从Layer 2返回Layer 1")  # 记录日志

        # Layer 1 时不再回退

        return {"should_continue": True, "working_memory": working_memory}  # 返回继续

    # =============================================================================  # 分隔线：精准抓取集成区域开始
    # 【精准抓取集成】处理AI输出并播报
    # =============================================================================  # 分隔线结束

    async def handle_ai_output_with_precision(  # 定义使用精准抓取处理AI输出的方法
        self,
        ai_output: str,  # 参数：AI原始输出
        voice_instance=None,  # 参数：语音实例
        session_id: str = "default"  # 参数：会话ID，默认default
    ) -> ParsedAIOutput:  # 返回：解析结果
        """
        使用精准抓取处理AI输出

        功能：
        1. 解析AI输出，分离自然语言和计算机语言
        2. 播报自然语言部分给用户
        3. 返回解析结果供后续处理

        Args:  # 参数说明
            ai_output: AI的原始输出  # 参数1
            voice_instance: 语音实例  # 参数2
            session_id: 会话ID  # 参数3

        Returns:  # 返回值说明
            ParsedAIOutput: 解析结果  # 返回类型
        """  # 方法文档字符串
        # 获取精准抓取解析器
        parser = self._get_precision_parser(voice_instance)  # 获取解析器

        # 解析并播报
        parsed = await parser.process_and_announce(ai_output, auto_speak=True)  # 处理并自动播报

        logger.info(  # 记录日志
            f"[Precision] 解析AI输出: type={parsed.marker_type.value}, "  # 类型
            f"speak={parsed.should_speak}, lang_len={len(parsed.natural_language)}"  # 是否播报和自然语言长度
        )

        # 发送事件到前端
        sync = get_realtime_sync_manager()  # 获取同步管理器
        sync.emit_event("ai_output_parsed", session_id, {  # 发送解析事件
            "marker_type": parsed.marker_type.value,  # 标记类型
            "natural_language": parsed.natural_language,  # 自然语言
            "should_speak": parsed.should_speak,  # 是否播报
            "parsed_data": parsed.parsed_data  # 解析数据
        })

        return parsed  # 返回解析结果

    def handle_tool_result_announce(  # 定义处理工具执行结果并播报的方法
        self,
        tool_name: str,  # 参数：工具名称
        result: dict[str, Any],  # 参数：执行结果
        voice_instance=None  # 参数：语音实例
    ) -> str:  # 返回：格式化后的结果文本
        """
        处理工具执行结果并播报

        Args:  # 参数说明
            tool_name: 工具名称  # 参数1
            result: 执行结果  # 参数2
            voice_instance: 语音实例  # 参数3

        Returns:  # 返回值说明
            str: 格式化后的结果文本  # 返回类型
        """  # 方法文档字符串
        # 获取播报器
        announcer = self._get_announcer(voice_instance)  # 获取播报器

        # 播报结果
        success = result.get("success", False)  # 获取成功标志
        message = result.get("user_message", "")  # 获取用户消息

        announcer.announce_result(success, message)  # 播报结果

        # 格式化结果文本供AI使用
        parser = self._get_precision_parser()  # 获取解析器
        return parser.extract_tool_result_for_ai(tool_name, result)  # 提取并返回结果文本

    async def handle_precision_marker(  # 定义处理精准抓取标记的方法
        self,
        parsed: ParsedAIOutput,  # 参数：解析结果
        working_memory: WorkingMemory,  # 参数：工作记忆
        voice_instance=None,  # 参数：语音实例
        session_id: str = "default"  # 参数：会话ID
    ) -> dict[str, Any]:  # 返回：处理结果
        """
        处理精准抓取标记

        根据标记类型执行相应操作：
        - TOOL_CALL: 执行工具
        - FINAL_ANSWER: 返回最终结果
        - CALL_USER: 呼叫用户
        - EVOLVE_REFLECT: 触发进化反思
        - WORLD_MODEL: 更新世界模型
        - VISION_ANALYSIS: 处理视觉分析

        Args:  # 参数说明
            parsed: 精准抓取解析结果  # 参数1
            working_memory: 工作记忆  # 参数2
            voice_instance: 语音实例  # 参数3
            session_id: 会话ID  # 参数4

        Returns:  # 返回值说明
            Dict: 处理结果  # 返回类型
        """  # 方法文档字符串
        marker_type = parsed.marker_type  # 获取标记类型

        result = {  # 初始化结果字典
            "handled": False,  # 是否已处理
            "should_continue": True,  # 是否继续
            "response": None,  # 响应
            "working_memory": working_memory  # 工作记忆
        }

        if marker_type == AICodeMarker.TOOL_CALL:  # 如果是工具调用标记
            # 工具调用 - 转发到 handle_tool_call
            tool_data = parsed.parsed_data  # 获取工具数据
            tool_name = tool_data.get("tool", "")  # 获取工具名称
            params = tool_data.get("params", {})  # 获取参数

            # 播报工具调用
            announcer = self._get_announcer(voice_instance)  # 获取播报器
            announcer.announce_tool_call(tool_name, params)  # 播报工具调用

            # 创建临时ParsedIntent
            temp_parsed = ParsedIntent(  # 创建意图对象
                intent_type=IntentType.TOOL_CALL,  # 意图类型为工具调用
                raw_instruction=parsed.raw_content,  # 原始内容
                target_tool=tool_name,  # 目标工具
                params=params,  # 参数
                confidence=0.95  # 置信度
            )

            # 调用工具处理
            tool_result = await self.handle_tool_call(  # 处理工具调用
                temp_parsed, working_memory, session_id,
                getattr(working_memory, 'current_task_id', 'default')  # 获取任务ID或默认
            )

            result["handled"] = True  # 标记已处理
            result["tool_result"] = tool_result  # 保存工具结果
            result["should_continue"] = tool_result.get("should_continue", True)  # 设置是否继续

        elif marker_type == AICodeMarker.FINAL_ANSWER:  # 如果是最终答案标记
            # 最终答案 - 播报并返回
            natural_lang = parsed.natural_language  # 获取自然语言
            if natural_lang and voice_instance:  # 如果有自然语言和语音实例
                voice_instance.speak(natural_lang, is_system=False)  # 播报

            result["handled"] = True  # 标记已处理
            result["should_continue"] = False  # 不继续
            result["response"] = parsed.parsed_data.get("content", natural_lang)  # 设置响应

        elif marker_type == AICodeMarker.CALL_USER:  # 如果是呼叫用户标记
            # 呼叫用户
            reason = parsed.parsed_data.get("reason", "")  # 获取原因
            if voice_instance and reason:  # 如果有语音实例和原因
                voice_instance.speak(f"需要您协助: {reason}", is_system=True)  # 播报

            result["handled"] = True  # 标记已处理
            result["call_user"] = True  # 标记呼叫用户
            result["reason"] = reason  # 保存原因

        elif marker_type == AICodeMarker.EVOLVE_REFLECT:  # 如果是进化反思标记
            # 触发进化反思
            announcer = self._get_announcer(voice_instance)  # 获取播报器
            announcer.announce_evolution("reflect")  # 播报进化

            result["handled"] = True  # 标记已处理
            result["trigger_evolution"] = True  # 标记触发进化

        elif marker_type == AICodeMarker.WORLD_MODEL:  # 如果是世界模型标记
            # 世界模型更新
            announcer = self._get_announcer(voice_instance)  # 获取播报器
            announcer.announce_query("world_model")  # 播报查询

            result["handled"] = True  # 标记已处理
            result["update_world_model"] = True  # 标记更新世界模型

        elif marker_type == AICodeMarker.VISION_ANALYSIS:  # 如果是视觉分析标记
            # 视觉分析
            announcer = self._get_announcer(voice_instance)  # 获取播报器
            announcer.announce_query("vision")  # 播报查询

            result["handled"] = True  # 标记已处理
            result["vision_analysis"] = True  # 标记视觉分析

        elif marker_type == AICodeMarker.LAYER_SWITCH:  # 如果是层级切换标记
            # 层级切换
            target_layer = parsed.parsed_data.get("target_layer", "")  # 获取目标层级
            if voice_instance:  # 如果有语音实例
                voice_instance.speak(f"切换到{target_layer}层级", is_system=True)  # 播报

            result["handled"] = True  # 标记已处理
            result["layer_switch"] = True  # 标记层级切换
            result["target_layer"] = target_layer  # 保存目标层级

        else:  # 其他标记类型
            # 未处理的标记类型，作为自然语言处理
            natural_lang = parsed.natural_language  # 获取自然语言
            if natural_lang and voice_instance:  # 如果有自然语言和语音实例
                voice_instance.speak(natural_lang, is_system=False)  # 播报

            result["handled"] = False  # 标记未处理
            result["response"] = natural_lang  # 设置响应

        return result  # 返回结果


# 全局实例
intent_handler = IntentHandler()  # 创建意图处理器全局单例


async def tool_call_phase(ctx: PhaseContext):
    """阶段包装：从 phase_ctx 取参，调用原有 handle_tool_call_async"""
    parsed = ctx.get("parsed_intent")
    working_memory = ctx.working_memory
    session_id = ctx.session_id
    task_id = ctx.task.id if hasattr(ctx.task, "id") else None
    return await intent_handler.handle_tool_call_async(parsed, working_memory, session_id, task_id)


register_phase("tool_call", tool_call_phase, order=3)


# =============================================================================
# 总结性注释：文件角色、关联关系与核心效果
# =============================================================================
#
# 【文件角色】
# 本文件（intent_handler.py）是 SiliconBase V5 系统的"意图处理器"核心模块。
# 负责分发处理各种意图类型，是NLP解析结果与系统执行之间的桥梁。
# 集成安全守卫、全语音播报和精准抓取三大特性。
#
# 【核心职责】
# 1. 意图分发：根据ParsedIntent类型分发到不同的处理方法
# 2. 工具调用处理：执行工具调用，包含风险评估和确认机制
# 3. 层级导航：支持L1/L2/L3三层查询层级的切换
# 4. 语音播报：所有操作都通过语音播报给用户
# 5. 安全守卫：高风险操作需要用户确认（10秒×2次）
# 6. 精准抓取：集成精准抓取解析AI输出并播报
# 7. 降级机制：语音失败时自动降级到文本输出
#
# 【处理方法分类】
# 1. 工具调用类:
#    - handle_tool_call(): 处理工具调用意图，包含完整的安全流程
#    - _is_tool_familiar(): 检查AI是否熟悉工具
#    - _wait_for_confirmation(): 异步等待用户确认
#
# 2. 自然语言类:
#    - handle_final_answer(): 处理最终答案意图
#    - _extract_natural_language(): 从响应中提取自然语言
#
# 3. 计划类:
#    - handle_plan(): 处理计划意图，存储到working_memory
#
# 4. 层级导航类:
#    - handle_query_tool_list(): 进入Layer 2
#    - handle_query_tool_detail(): 进入Layer 3
#    - handle_back(): 返回上一层级
#
# 5. 精准抓取类:
#    - handle_ai_output_with_precision(): 解析AI输出并播报
#    - handle_tool_result_announce(): 播报工具执行结果
#    - handle_precision_marker(): 处理精准抓取标记
#
# 6. 辅助方法类:
#    - _speak(): 语音播报（线程化，支持降级）
#    - _fallback_to_text(): 语音降级到文本
#    - notify_voice_degraded(): 通知用户语音已降级
#
# 【安全流程】
# 1. 工具存在检查 → 2. AI熟悉度检查 → 3. 风险评估 → 4. 语音播报
# 5. 高风险确认（10秒×2次） → 6. 执行工具 → 7. 结果播报 → 8. 事故记录
#
# 【关联文件】
# 1. core/tool_manager.py          - 工具管理器
#    * 关系：被handle_tool_call使用
#    * 交互：获取工具、执行工具调用
#
# 2. core/safety_guard.py          - 安全守卫
#    * 关系：风险评估和事故记录
#    * 交互：assess_operation_risk(), record_accident()
#
# 3. core/working_memory.py        - 工作记忆
#    * 关系：状态更新和存储
#    * 交互：update_after_tool(), ai_plan存储
#
# 4. core/confirmation_manager.py  - 确认管理器
#    * 关系：异步确认流程
#    * 交互：create_request(), wait_for_response()
#
# 5. core/realtime_sync.py         - 实时同步
#    * 关系：事件通知前端
#    * 交互：emit_event()发送各种事件
#
# 6. core/memory.py                - 记忆系统
#    * 关系：记录操作历史
#    * 交互：add()存储经验
#
# 7. core/nlp_intent_parser.py     - NLP意图解析器
#    * 关系：输入来源
#    * 交互：ParsedIntent, AICodeMarker等类型
#
# 8. core/dialogue_manager.py      - 对话管理器
#    * 关系：语音播报
#    * 交互：获取voice实例
#
# 9. core/task_orchestrator.py     - 任务编排器
#    * 关系：Stop Hooks记录
#    * 交互：record_tool_execution()
#
# 【达到的效果】
# 1. 安全执行：高风险操作必须用户确认，避免误操作
# 2. 全语音播报：用户始终知道系统在做什么
# 3. 自动学习：AI不熟悉工具时自动进入L3学习
# 4. 降级容错：语音失败自动降级到文本，保证可用性
# 5. 精准抓取：分离自然语言和计算机语言，优化播报
# 6. 层级导航：支持L1/L2/L3三层查询架构
# 7. 事故记录：失败操作被记录，系统从中学习
#
# 【使用场景】
# - 用户请求执行工具时：完整的工具调用安全流程
# - AI输出自然语言时：播报并显示给用户
# - AI需要确认时：异步等待用户响应
# - 查询工具信息时：层级导航到L2/L3
# - AI输出计算机语言时：精准抓取解析并执行
#
# =============================================================================
