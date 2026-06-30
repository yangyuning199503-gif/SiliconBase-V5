#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
底座功能触发器 - 统一管理计算机语言触发和AI行为识别

这是一个核心模块，负责统一管理AI计算机语言的触发处理。
所有AI计算机语言标记（如"呼叫用户"、"查找工具"等）都通过此模块进行处理。

使用方法:
    from core.function_trigger import get_function_trigger, TriggerType

    trigger = get_function_trigger()
    result = trigger.trigger(TriggerType.CALL_USER, {
        "voice_instance": voice,
        "session_id": session_id
    })
"""

import asyncio
import logging  # 导入日志模块
from collections.abc import Callable  # 从typing导入类型注解工具
from dataclasses import dataclass  # 从dataclasses导入数据类装饰器
from enum import Enum  # 从enum导入枚举类基类
from typing import Any

from core.memory.memory_source import MemorySource  # Agent-4: 导入MemorySource枚举
from voice.voice_prompts import DialogueManagerAnnouncements, SystemAnnouncements

logger = logging.getLogger(__name__)  # 获取本模块的日志记录器


class TriggerType(Enum):  # 定义触发类型枚举类
    """底座功能触发类型 - AI计算机语言标记  # 枚举类文档字符串标题

    共19个计算机语言标记，覆盖核心交互场景：  # 标记数量说明
    - 用户交互层: 呼叫、询问、等待确认、通知  # 第1层功能
    - 工具查询层: 查找工具、查询工具列表、查询工具详情  # 第2层功能
    - 记忆认知层: 查询记忆、记录记忆、删除记忆  # 第3层功能
    - 学习进化层: 进入学习、执行计划、反思、进化  # 第4层功能
    - 预测感知层: 世界模型预测、视觉识别、行为分析  # 第5层功能
    - 系统控制层: 暂停执行、恢复执行、终止任务  # 第6层功能
    """  # 枚举类文档字符串结束
    # 用户交互层
    CALL_USER = "呼叫用户"           # 呼叫用户触发
    ASK_USER = "询问用户"            # 询问用户触发
    WAIT_CONFIRM = "等待确认"        # 等待确认触发
    NOTIFY_USER = "通知用户"         # 通知用户触发（新增）

    # 工具查询层
    FIND_TOOL = "查找工具"           # 查找工具触发
    QUERY_TOOL_LIST = "查询工具列表"  # 查询工具列表触发（新增）
    QUERY_TOOL_DETAIL = "查询工具详情"  # 查询工具详情触发（新增）

    # 记忆认知层
    QUERY_MEMORY = "查询记忆"        # 查询记忆触发
    RECORD_MEMORY = "记录记忆"       # 记录记忆触发（新增）
    DELETE_MEMORY = "删除记忆"       # 删除记忆触发（新增）

    # 学习进化层
    ENTER_LEARNING = "进入学习"      # 进入学习模式触发
    EXECUTE_PLAN = "执行计划"        # 执行计划触发
    REFLECT = "反思"                # 触发反思
    EVOLVE = "进化"                 # 触发进化

    # 预测感知层
    WORLD_MODEL_PREDICT = "世界模型预测"  # 世界模型预测触发
    VISION_ANALYZE = "视觉识别"      # 视觉识别触发
    BEHAVIOR_ANALYZE = "行为分析"    # 行为分析触发（新增）

    # 系统控制层
    PAUSE_EXECUTION = "暂停执行"           # 暂停执行触发（新增）
    RESUME_EXECUTION = "恢复执行"          # 恢复执行触发（新增）
    TERMINATE_TASK = "终止任务"            # 终止任务触发（新增）
    SUBMIT_UNDERSTANDING = "提交理解摘要"   # 提交理解摘要触发（新增，用于暂停确认流程）


@dataclass  # 使用数据类装饰器
class TriggerResult:  # 定义触发结果数据类
    """触发结果"""  # 类文档字符串
    success: bool  # 是否成功标志
    message: str  # 结果消息
    data: dict[str, Any] = None  # 附加数据字典
    should_continue: bool = True  # 是否继续循环标志，默认为True

    def __post_init__(self):  # 定义初始化后处理方法
        if self.data is None:  # 如果数据为None
            self.data = {}  # 设置为空字典


class FunctionTrigger:  # 定义功能触发器类
    """
    底座功能触发器  # 类文档字符串标题

    统一管理所有AI计算机语言触发，提供统一的触发接口。  # 统一管理触发
    每个触发器都是独立的处理方法，便于维护和扩展。  # 模块化设计
    """  # 类文档字符串结束

    def __init__(self):  # 定义初始化方法
        self._triggers: dict[TriggerType, Callable] = {}  # 初始化触发器函数字典
        self._register_default_triggers()  # 调用方法注册默认触发器

    def _register_default_triggers(self):  # 定义注册默认触发器的私有方法
        """注册默认触发器 - 共19个计算机语言标记"""  # 方法文档字符串
        # 用户交互层
        self._triggers[TriggerType.CALL_USER] = self._trigger_call_user  # 注册呼叫用户触发器
        self._triggers[TriggerType.ASK_USER] = self._trigger_ask_user  # 注册询问用户触发器
        self._triggers[TriggerType.WAIT_CONFIRM] = self._trigger_wait_confirm  # 注册等待确认触发器
        self._triggers[TriggerType.NOTIFY_USER] = self._trigger_notify_user  # 注册通知用户触发器

        # 工具查询层
        self._triggers[TriggerType.FIND_TOOL] = self._trigger_find_tool  # 注册查找工具触发器
        self._triggers[TriggerType.QUERY_TOOL_LIST] = self._trigger_query_tool_list  # 注册查询工具列表触发器
        self._triggers[TriggerType.QUERY_TOOL_DETAIL] = self._trigger_query_tool_detail  # 注册查询工具详情触发器

        # 记忆认知层
        self._triggers[TriggerType.QUERY_MEMORY] = self._trigger_query_memory  # 注册查询记忆触发器
        # RECORD_MEMORY 已迁移至 async 内联调用，不再注册到 sync 触发器字典
        self._triggers[TriggerType.DELETE_MEMORY] = self._trigger_delete_memory  # 注册删除记忆触发器

        # 学习进化层
        self._triggers[TriggerType.ENTER_LEARNING] = self._trigger_enter_learning  # 注册进入学习触发器
        self._triggers[TriggerType.EXECUTE_PLAN] = self._trigger_execute_plan  # 注册执行计划触发器
        self._triggers[TriggerType.REFLECT] = self._trigger_reflect  # 注册反思触发器
        self._triggers[TriggerType.EVOLVE] = self._trigger_evolve  # 注册进化触发器

        # 预测感知层
        self._triggers[TriggerType.WORLD_MODEL_PREDICT] = self._trigger_world_model_predict  # 注册世界模型预测触发器
        self._triggers[TriggerType.VISION_ANALYZE] = self._trigger_vision_analyze  # 注册视觉识别触发器
        self._triggers[TriggerType.BEHAVIOR_ANALYZE] = self._trigger_behavior_analyze  # 注册行为分析触发器

        # 系统控制层
        self._triggers[TriggerType.PAUSE_EXECUTION] = self._trigger_pause_execution  # 注册暂停执行触发器
        self._triggers[TriggerType.RESUME_EXECUTION] = self._trigger_resume_execution  # 注册恢复执行触发器
        self._triggers[TriggerType.TERMINATE_TASK] = self._trigger_terminate_task  # 注册终止任务触发器
        self._triggers[TriggerType.SUBMIT_UNDERSTANDING] = self._trigger_submit_understanding  # 注册提交理解摘要触发器

        logger.info(f"[FunctionTrigger] 已注册 {len(self._triggers)} 个触发器（20个计算机语言标记）")  # 记录注册信息

    async def trigger(self,  # 定义触发功能的主方法
                trigger_type: TriggerType,  # 参数：触发类型枚举
                context: dict[str, Any]  # 参数：上下文信息字典
                ) -> TriggerResult:  # 返回：触发结果对象
        """
        触发底座功能  # 方法文档字符串标题

        Args:  # 参数说明
            trigger_type: 触发类型  # TriggerType枚举值
            context: 上下文信息，包含voice_instance, session_id, working_memory等  # 上下文字典

        Returns:  # 返回值说明
            TriggerResult: 触发结果  # 包含success/message/data/should_continue
        """  # 方法文档字符串结束
        if trigger_type not in self._triggers:  # 如果触发类型未注册
            logger.error(f"[FunctionTrigger] 未注册的触发器: {trigger_type}")  # 记录错误日志
            return TriggerResult(  # 返回错误结果
                success=False,  # 失败标志
                message=f"未注册的触发器: {trigger_type}",  # 错误消息
                should_continue=True  # 继续循环
            )

        try:  # 开始异常捕获
            logger.info(f"[FunctionTrigger] 触发: {trigger_type.value}")  # 记录触发信息
            handler = self._triggers[trigger_type]
            if asyncio.iscoroutinefunction(handler):
                result = await handler(context)
            elif trigger_type == TriggerType.RECORD_MEMORY:
                result = await self._trigger_record_memory_async(context)
            else:
                result = await asyncio.to_thread(handler, context)  # 调用对应的触发器方法
            return result
        except Exception as e:  # 捕获异常
            logger.error(f"[FunctionTrigger] 触发失败 {trigger_type.value}: {e}")  # 记录错误日志
            return TriggerResult(  # 返回错误结果
                success=False,  # 失败标志
                message=f"触发失败: {str(e)}",  # 错误消息
                should_continue=True  # 继续循环
            )

    def _get_voice_instance(self,  # 定义从上下文获取语音实例的私有方法
                            context: dict[str, Any]  # 参数：上下文字典
                            ) -> Any | None:  # 返回：语音实例或None
        """从上下文中获取语音实例"""  # 方法文档字符串
        voice = context.get("voice_instance")  # 尝试从上下文获取语音实例
        if voice is not None:  # 如果获取成功
            return voice  # 返回语音实例

        # 尝试从dialogue_manager获取
        try:  # 开始异常处理
            from core.dialog.dialogue_manager import dialogue_manager  # 导入对话管理器
            if dialogue_manager.voice is not None:  # 如果有语音实例
                return dialogue_manager.voice  # 返回语音实例
        except Exception:  # 捕获异常
            pass  # 忽略异常，继续尝试其他来源

        # 尝试从global_state获取
        try:  # 开始异常处理
            from core.global_state import get_voice_interface  # 导入全局状态
            voice = get_voice_interface()  # 获取语音接口
            if voice is not None:  # 如果获取成功
                return voice  # 返回语音实例
        except Exception:  # 捕获异常
            pass  # 忽略异常

        return None  # 返回None表示未找到语音实例

    def _get_sync_manager(self):  # 定义获取实时同步管理器的私有方法
        """获取实时同步管理器"""  # 方法文档字符串
        try:  # 开始异常处理
            from core.sync.realtime_sync import get_realtime_sync_manager  # 导入同步管理器
            return get_realtime_sync_manager()  # 返回同步管理器实例
        except Exception:  # 捕获异常
            return None  # 返回None

    def _trigger_call_user(self,  # 定义触发呼叫用户的私有方法
                           context: dict[str, Any]  # 参数：上下文字典
                           ) -> TriggerResult:  # 返回：触发结果
        """触发呼叫用户"""  # 方法文档字符串
        session_id = context.get("session_id", "console")  # 获取会话ID，默认为console
        voice = self._get_voice_instance(context)  # 获取语音实例

        message = "正在呼叫用户，请接听..."  # 消息内容
        logger.info(f"[FunctionTrigger] {message}")  # 记录日志

        # 语音播报
        if voice:  # 如果有语音实例
            try:  # 开始异常处理
                voice.speak(message, is_system=True, wait=False)  # 播报消息
            except Exception as e:  # 捕获异常
                logger.debug(f"[FunctionTrigger] 语音播报失败: {e}")  # 记录调试日志

        # 发送事件
        sync = self._get_sync_manager()  # 获取同步管理器
        if sync:  # 如果获取成功
            sync.emit_event("call_user", session_id, {  # 发送事件
                "action": "call_user",  # 动作类型
                "message": message  # 消息内容
            })

        return TriggerResult(  # 返回结果
            success=True,  # 成功标志
            message=message,  # 消息内容
            should_continue=True  # 继续循环
        )

    def _trigger_find_tool(self,  # 定义触发查找工具的私有方法
                           context: dict[str, Any]  # 参数：上下文字典
                           ) -> TriggerResult:  # 返回：触发结果
        """触发查找工具 - 进入L2"""  # 方法文档字符串
        working_memory = context.get("working_memory")  # 获取工作记忆
        params = context.get("params", {})  # 获取参数字典
        voice = self._get_voice_instance(context)  # 获取语音实例

        # 【P0-2修复】统一层级切换语音播报
        if voice:  # 如果有语音实例
            try:  # 开始异常处理
                voice.speak(SystemAnnouncements.QUERYING, is_system=True, wait=False)  # 播报
            except Exception as e:  # 捕获异常
                logger.debug(f"语音播报失败，静默降级: {e}")
                # 降级逻辑：已静默处理，无需额外操作

        logger.info("[FunctionTrigger] AI计算机语言：查找工具")  # 记录日志

        # 进入L2
        if working_memory:  # 如果有工作记忆
            old_stage = working_memory.query_stage  # 保存旧阶段
            working_memory.query_stage = "layer2"  # 切换到L2
            category = params.get("category") if params else None  # 获取分类参数
            working_memory.current_category = category if category else "general"  # 设置当前分类
            working_memory.current_tool = None  # 清空当前工具

            # 记录层级切换
            if hasattr(working_memory, 'record_layer_switch') and not working_memory.record_layer_switch(old_stage, "layer2", "FIND_TOOL"):  # 如果有记录方法且记录切换失败
                return TriggerResult(  # 如果超过限制
                    success=False,  # 失败标志
                    message="层级切换次数超过限制",  # 错误消息
                    should_continue=False  # 不继续循环
                )

            # 添加系统消息
            working_memory.append({  # 添加系统消息到工作记忆
                "role": "system",  # 角色为系统
                "content": "【工具查询】已进入工具查询模式(L2)，请根据用户需求查询并列出相关工具。"  # 消息内容
            })

        logger.info("[FunctionTrigger] AI计算机语言：查找工具 → 已进入L2")  # 记录日志

        return TriggerResult(  # 返回结果
            success=True,  # 成功标志
            message="已进入工具查询模式(L2)",  # 消息内容
            should_continue=True  # 继续循环
        )

    def _trigger_query_memory(self,  # 定义触发查询记忆的私有方法
                              context: dict[str, Any]  # 参数：上下文字典
                              ) -> TriggerResult:  # 返回：触发结果
        """触发查询记忆"""  # 方法文档字符串
        working_memory = context.get("working_memory")  # 获取工作记忆

        logger.info("[FunctionTrigger] AI计算机语言：查询记忆")  # 记录日志

        if working_memory:  # 如果有工作记忆
            working_memory.append({  # 添加系统消息到工作记忆
                "role": "system",  # 角色为系统
                "content": "【记忆查询】已完成记忆检索，请基于检索到的记忆继续任务。"  # 消息内容
            })

        return TriggerResult(  # 返回结果
            success=True,  # 成功标志
            message="记忆查询完成",  # 消息内容
            should_continue=True  # 继续循环
        )

    def _trigger_ask_user(self,  # 定义触发询问用户的私有方法
                          context: dict[str, Any]  # 参数：上下文字典
                          ) -> TriggerResult:  # 返回：触发结果
        """触发询问用户"""  # 方法文档字符串
        session_id = context.get("session_id", "console")  # 获取会话ID，默认为console
        working_memory = context.get("working_memory")  # 获取工作记忆
        voice = self._get_voice_instance(context)  # 获取语音实例

        message = "需要您的确认，请问您同意继续吗？"  # 消息内容
        logger.info("[FunctionTrigger] AI计算机语言：询问用户")  # 记录日志

        # 语音播报
        if voice:  # 如果有语音实例
            try:  # 开始异常处理
                voice.speak(message, is_system=True, wait=False)  # 播报
            except Exception as e:  # 捕获异常
                logger.debug(f"语音播报失败，静默降级: {e}")
                # 降级逻辑：已静默处理，无需额外操作

        # 发送事件
        sync = self._get_sync_manager()  # 获取同步管理器
        if sync:  # 如果获取成功
            sync.emit_event("ask_user", session_id, {  # 发送事件
                "action": "ask_user",  # 动作类型
                "message": message  # 消息内容
            })

        # 添加提示
        if working_memory:  # 如果有工作记忆
            working_memory.append({  # 添加系统消息到工作记忆
                "role": "system",  # 角色为系统
                "content": "【等待用户】已询问用户确认，请等待用户回应后继续。"  # 消息内容
            })

        return TriggerResult(  # 返回结果
            success=True,  # 成功标志
            message=message,  # 消息内容
            should_continue=True  # 继续循环
        )

    def _trigger_wait_confirm(self,  # 定义触发等待确认的私有方法
                              context: dict[str, Any]  # 参数：上下文字典
                              ) -> TriggerResult:  # 返回：触发结果
        """触发等待确认"""  # 方法文档字符串
        session_id = context.get("session_id", "console")  # 获取会话ID，默认为console
        working_memory = context.get("working_memory")  # 获取工作记忆
        voice = self._get_voice_instance(context)  # 获取语音实例

        message = "正在等待您的确认，请按任意键继续..."  # 消息内容
        logger.info("[FunctionTrigger] AI计算机语言：等待确认")  # 记录日志

        # 语音播报
        if voice:  # 如果有语音实例
            try:  # 开始异常处理
                voice.speak(message, is_system=True, wait=False)  # 播报
            except Exception as e:  # 捕获异常
                logger.debug(f"语音播报失败，静默降级: {e}")
                # 降级逻辑：已静默处理，无需额外操作

        # 发送事件
        sync = self._get_sync_manager()  # 获取同步管理器
        if sync:  # 如果获取成功
            sync.emit_event("wait_confirm", session_id, {  # 发送事件
                "action": "wait_confirm",  # 动作类型
                "message": message  # 消息内容
            })

        # 添加提示
        if working_memory:  # 如果有工作记忆
            working_memory.append({  # 添加系统消息到工作记忆
                "role": "system",  # 角色为系统
                "content": "【等待确认】已暂停等待用户确认，用户确认后方可继续。"  # 消息内容
            })

        return TriggerResult(  # 返回结果
            success=True,  # 成功标志
            message=message,  # 消息内容
            should_continue=True  # 继续循环
        )

    def _trigger_enter_learning(self,  # 定义触发进入学习模式的私有方法
                                context: dict[str, Any]  # 参数：上下文字典
                                ) -> TriggerResult:  # 返回：触发结果
        """触发进入学习模式"""  # 方法文档字符串
        session_id = context.get("session_id", "console")  # 获取会话ID，默认为console
        working_memory = context.get("working_memory")  # 获取工作记忆
        voice = self._get_voice_instance(context)  # 获取语音实例

        message = "正在进入L3学习模式..."  # 消息内容
        logger.info("[FunctionTrigger] AI计算机语言：进入学习")  # 记录日志

        # 语音播报
        if voice:  # 如果有语音实例
            try:  # 开始异常处理
                voice.speak(message, is_system=True, wait=False)  # 播报
            except Exception as e:  # 捕获异常
                logger.debug(f"语音播报失败，静默降级: {e}")
                # 降级逻辑：已静默处理，无需额外操作

        # 发送事件
        sync = self._get_sync_manager()  # 获取同步管理器
        if sync:  # 如果获取成功
            sync.emit_event("enter_learning", session_id, {  # 发送事件
                "action": "enter_learning",  # 动作类型
                "message": message  # 消息内容
            })

        # 调用学习系统
        try:  # 开始异常处理
            from core.learning_system import get_learning_system  # 导入学习系统
            learning_system = get_learning_system()  # 获取学习系统实例
            learning_system.enter_l3_mode()  # 进入L3模式
            logger.info("[FunctionTrigger] 已进入L3学习模式")  # 记录日志
        except Exception as e:  # 捕获异常
            logger.debug(f"[FunctionTrigger] 进入L3学习模式失败: {e}")  # 记录调试日志

        # 添加提示
        if working_memory:  # 如果有工作记忆
            working_memory.append({  # 添加系统消息到工作记忆
                "role": "system",  # 角色为系统
                "content": "【L3学习模式】已进入L3深度学习模式，请专注于学习和知识构建。"  # 消息内容
            })

        return TriggerResult(  # 返回结果
            success=True,  # 成功标志
            message=message,  # 消息内容
            should_continue=True  # 继续循环
        )

    def _trigger_execute_plan(self,  # 定义触发执行计划的私有方法
                              context: dict[str, Any]  # 参数：上下文字典
                              ) -> TriggerResult:  # 返回：触发结果
        """触发执行计划"""  # 方法文档字符串
        session_id = context.get("session_id", "console")  # 获取会话ID，默认为console
        working_memory = context.get("working_memory")  # 获取工作记忆
        user_instruction = context.get("user_instruction", "")  # 获取用户指令
        voice = self._get_voice_instance(context)  # 获取语音实例

        message = "正在触发计划执行..."  # 消息内容
        logger.info("[FunctionTrigger] AI计算机语言：执行计划")  # 记录日志

        # 语音播报
        if voice:  # 如果有语音实例
            try:  # 开始异常处理
                voice.speak(message, is_system=True, wait=False)  # 播报
            except Exception as e:  # 捕获异常
                logger.debug(f"语音播报失败，静默降级: {e}")
                # 降级逻辑：已静默处理，无需额外操作

        # 发送事件
        sync = self._get_sync_manager()  # 获取同步管理器
        if sync:  # 如果获取成功
            sync.emit_event("execute_plan", session_id, {  # 发送事件
                "action": "execute_plan",  # 动作类型
                "message": message  # 消息内容
            })

        # 调用计划系统
        try:  # 开始异常处理
            from core.task.planner import get_planner  # 导入规划器
            planner = get_planner()  # 获取规划器实例
            plan_id = planner.create_plan(user_instruction)  # 创建计划

            if working_memory:  # 如果有工作记忆
                working_memory.ai_plan_id = plan_id  # 保存计划ID到工作记忆
                plan_summary = planner.get_plan_summary(plan_id)  # 获取计划摘要
                if plan_summary:  # 如果有摘要
                    working_memory.append({  # 添加系统消息到工作记忆
                        "role": "system",  # 角色为系统
                        "content": f"【计划创建】已创建计划，共{plan_summary.get('total_steps', 0)}步，开始执行。"  # 消息内容
                    })
                    logger.info(f"[FunctionTrigger] 创建计划: {plan_summary.get('goal', '')}")  # 记录日志
        except Exception as e:  # 捕获异常
            logger.debug(f"[FunctionTrigger] 执行计划失败: {e}")  # 记录调试日志

        return TriggerResult(  # 返回结果
            success=True,  # 成功标志
            message=message,  # 消息内容
            should_continue=True  # 继续循环
        )

    def _trigger_reflect(self,  # 定义触发反思系统的私有方法
                         context: dict[str, Any]  # 参数：上下文字典
                         ) -> TriggerResult:  # 返回：触发结果
        """触发反思系统"""  # 方法文档字符串
        session_id = context.get("session_id", "console")  # 获取会话ID，默认为console
        working_memory = context.get("working_memory")  # 获取工作记忆
        user_instruction = context.get("user_instruction", "")  # 获取用户指令
        execution_history = context.get("execution_history", [])  # 获取执行历史
        voice = self._get_voice_instance(context)  # 获取语音实例

        message = "正在启动反思系统..."  # 消息内容
        logger.info("[FunctionTrigger] AI计算机语言：反思")  # 记录日志

        # 语音播报
        if voice:  # 如果有语音实例
            try:  # 开始异常处理
                voice.speak(message, is_system=True, wait=False)  # 播报
            except Exception as e:  # 捕获异常
                logger.debug(f"语音播报失败，静默降级: {e}")
                # 降级逻辑：已静默处理，无需额外操作

        # 发送事件
        sync = self._get_sync_manager()  # 获取同步管理器
        if sync:  # 如果获取成功
            sync.emit_event("reflect", session_id, {  # 发送事件
                "action": "reflect",  # 动作类型
                "message": message  # 消息内容
            })

        # 调用反思系统
        try:  # 开始异常处理
            from core.reflector import reflector  # 导入反思器
            reflection = reflector.deep_reflect(  # 执行深度反思
                context={"instruction": user_instruction, "history": execution_history}  # 传入上下文
            )
            if reflection and working_memory:  # 如果有反思结果和工作记忆
                reflection_content = getattr(reflection, 'insights', '正在进行深度反思')  # 获取洞察内容
                working_memory.append({  # 添加系统消息到工作记忆
                    "role": "system",  # 角色为系统
                    "content": f"【深度反思】{reflection_content}"  # 消息内容
                })
                logger.info(f"[FunctionTrigger] 反思结果: {reflection_content}")  # 记录日志
        except Exception as e:  # 捕获异常
            logger.debug(f"[FunctionTrigger] 反思系统调用失败: {e}")  # 记录调试日志

        return TriggerResult(  # 返回结果
            success=True,  # 成功标志
            message=message,  # 消息内容
            should_continue=True  # 继续循环
        )

    def _trigger_evolve(self,  # 定义触发进化引擎的私有方法
                        context: dict[str, Any]  # 参数：上下文字典
                        ) -> TriggerResult:  # 返回：触发结果
        """触发进化引擎"""  # 方法文档字符串
        session_id = context.get("session_id", "console")  # 获取会话ID，默认为console
        working_memory = context.get("working_memory")  # 获取工作记忆
        user_instruction = context.get("user_instruction", "")  # 获取用户指令
        execution_history = context.get("execution_history", [])  # 获取执行历史
        voice = self._get_voice_instance(context)  # 获取语音实例

        message = "正在触发进化引擎..."  # 消息内容
        logger.info("[FunctionTrigger] AI计算机语言：进化")  # 记录日志

        # 语音播报
        if voice:  # 如果有语音实例
            try:  # 开始异常处理
                voice.speak(message, is_system=True, wait=False)  # 播报
            except Exception as e:  # 捕获异常
                logger.debug(f"语音播报失败，静默降级: {e}")
                # 降级逻辑：已静默处理，无需额外操作

        # 发送事件
        sync = self._get_sync_manager()  # 获取同步管理器
        if sync:  # 如果获取成功
            sync.emit_event("evolve", session_id, {  # 发送事件
                "action": "evolve",  # 动作类型
                "message": message  # 消息内容
            })

        # 调用进化引擎
        try:  # 开始异常处理
            from core.evolution.evolution import get_evolution_engine  # 导入进化引擎
            evolution = get_evolution_engine()  # 获取进化引擎实例
            evolution_result = evolution.trigger_evolution(  # 触发进化
                task=user_instruction,  # 传入任务
                history=execution_history  # 传入历史
            )
            if evolution_result and working_memory:  # 如果有结果和工作记忆
                working_memory.append({  # 添加系统消息到工作记忆
                    "role": "system",  # 角色为系统
                    "content": "【进化完成】已触发进化引擎，能力得到提升。"  # 消息内容
                })
                logger.info("[FunctionTrigger] 进化引擎执行完成")  # 记录日志
        except Exception as e:  # 捕获异常
            logger.debug(f"[FunctionTrigger] 进化引擎调用失败: {e}")  # 记录调试日志

        return TriggerResult(  # 返回结果
            success=True,  # 成功标志
            message=message,  # 消息内容
            should_continue=True  # 继续循环
        )

    def _trigger_world_model_predict(self,  # 定义触发世界模型预测的私有方法
                                     context: dict[str, Any]  # 参数：上下文字典
                                     ) -> TriggerResult:  # 返回：触发结果
        """触发世界模型预测"""  # 方法文档字符串
        session_id = context.get("session_id", "console")  # 获取会话ID，默认为console
        working_memory = context.get("working_memory")  # 获取工作记忆
        user_instruction = context.get("user_instruction", "")  # 获取用户指令
        execution_history = context.get("execution_history", [])  # 获取执行历史
        voice = self._get_voice_instance(context)  # 获取语音实例

        message = "正在进行世界模型预测..."  # 消息内容
        logger.info("[FunctionTrigger] AI计算机语言：世界模型预测")  # 记录日志

        # 语音播报
        if voice:  # 如果有语音实例
            try:  # 开始异常处理
                voice.speak(message, is_system=True, wait=False)  # 播报
            except Exception as e:  # 捕获异常
                logger.debug(f"语音播报失败，静默降级: {e}")
                # 降级逻辑：已静默处理，无需额外操作

        # 发送事件
        sync = self._get_sync_manager()  # 获取同步管理器
        if sync:  # 如果获取成功
            sync.emit_event("world_model_predict", session_id, {  # 发送事件
                "action": "world_model_predict",  # 动作类型
                "message": message  # 消息内容
            })

        # 调用世界模型
        try:  # 开始异常处理
            from core.world_model.world_model import get_world_model  # 导入世界模型
            world_model = get_world_model()  # 获取世界模型实例
            current_perception = {"task": user_instruction}  # 构建当前感知
            prediction = world_model.predict(  # 执行预测
                perception=current_perception,  # 传入感知
                action="analyze",  # 动作
                context={"history": execution_history}  # 传入上下文
            )
            if prediction and working_memory:  # 如果有预测结果和工作记忆
                prediction_text = prediction.get("prediction", "预测完成")  # 获取预测文本
                working_memory.append({  # 添加系统消息到工作记忆
                    "role": "system",  # 角色为系统
                    "content": f"【世界模型预测】{prediction_text}"  # 消息内容
                })
                logger.info(f"[FunctionTrigger] 世界模型预测: {prediction_text}")  # 记录日志
        except Exception as e:  # 捕获异常
            logger.debug(f"[FunctionTrigger] 世界模型预测失败: {e}")  # 记录调试日志

        return TriggerResult(  # 返回结果
            success=True,  # 成功标志
            message=message,  # 消息内容
            should_continue=True  # 继续循环
        )

    def _trigger_vision_analyze(self,  # 定义触发视觉识别分析的私有方法
                                context: dict[str, Any]  # 参数：上下文字典
                                ) -> TriggerResult:  # 返回：触发结果
        """触发视觉识别分析"""  # 方法文档字符串
        session_id = context.get("session_id", "console")  # 获取会话ID，默认为console
        working_memory = context.get("working_memory")  # 获取工作记忆
        voice = self._get_voice_instance(context)  # 获取语音实例

        message = "正在进行视觉识别分析..."  # 消息内容
        logger.info("[FunctionTrigger] AI计算机语言：视觉识别")  # 记录日志

        # 语音播报
        if voice:  # 如果有语音实例
            try:  # 开始异常处理
                voice.speak(message, is_system=True, wait=False)  # 播报
            except Exception as e:  # 捕获异常
                logger.debug(f"语音播报失败，静默降级: {e}")
                # 降级逻辑：已静默处理，无需额外操作

        # 发送事件
        sync = self._get_sync_manager()  # 获取同步管理器
        if sync:  # 如果获取成功
            sync.emit_event("vision_analyze", session_id, {  # 发送事件
                "action": "vision_analyze",  # 动作类型
                "message": message  # 消息内容
            })

        # 调用视觉模型
        try:  # 开始异常处理
            from core.vision_model import get_vision_model  # 导入视觉模型
            vision_model = get_vision_model()  # 获取视觉模型实例
            visual_perception = vision_model.capture_and_analyze()  # 捕获并分析
            if visual_perception and working_memory:  # 如果有结果和工作记忆
                analysis_result = visual_perception.get("analysis", "视觉分析完成")  # 获取分析结果
                working_memory.append({  # 添加系统消息到工作记忆
                    "role": "system",  # 角色为系统
                    "content": f"【视觉分析结果】{analysis_result}"  # 消息内容
                })
                logger.info(f"[FunctionTrigger] 视觉分析: {analysis_result}")  # 记录日志
        except Exception as e:  # 捕获异常
            logger.debug(f"[FunctionTrigger] 视觉模型分析失败: {e}")  # 记录调试日志

        return TriggerResult(  # 返回结果
            success=True,  # 成功标志
            message=message,  # 消息内容
            should_continue=True  # 继续循环
        )

    # ============== 新增的触发器方法 ==============

    def _trigger_notify_user(self,  # 定义触发通知用户的私有方法（新增）
                             context: dict[str, Any]  # 参数：上下文字典
                             ) -> TriggerResult:  # 返回：触发结果
        """触发通知用户（新增）"""  # 方法文档字符串
        session_id = context.get("session_id", "console")  # 获取会话ID，默认为console
        working_memory = context.get("working_memory")  # 获取工作记忆
        voice = self._get_voice_instance(context)  # 获取语音实例
        params = context.get("params", {})  # 获取参数字典

        message = params.get("message", "有新消息通知您")  # 获取消息内容，默认消息
        logger.info(f"[FunctionTrigger] AI计算机语言：通知用户 - {message}")  # 记录日志

        # 语音播报
        if voice:  # 如果有语音实例
            try:  # 开始异常处理
                voice.speak(message, is_system=True, wait=False)  # 播报
            except Exception as e:  # 捕获异常
                logger.debug(f"语音播报失败，静默降级: {e}")
                # 降级逻辑：已静默处理，无需额外操作

        # 发送事件
        sync = self._get_sync_manager()  # 获取同步管理器
        if sync:  # 如果获取成功
            sync.emit_event("notify_user", session_id, {  # 发送事件
                "action": "notify_user",  # 动作类型
                "message": message  # 消息内容
            })

        if working_memory:  # 如果有工作记忆
            working_memory.append({  # 添加系统消息到工作记忆
                "role": "system",  # 角色为系统
                "content": f"【系统通知】{message}"  # 消息内容
            })

        return TriggerResult(  # 返回结果
            success=True,  # 成功标志
            message=f"已通知用户: {message}",  # 消息内容
            should_continue=True  # 继续循环
        )

    def _trigger_query_tool_list(self,  # 定义触发查询工具列表的私有方法（新增）
                                 context: dict[str, Any]  # 参数：上下文字典
                                 ) -> TriggerResult:  # 返回：触发结果
        """触发查询工具列表 - 进入L2（新增）"""  # 方法文档字符串
        working_memory = context.get("working_memory")  # 获取工作记忆
        params = context.get("params", {})  # 获取参数字典

        category = params.get("category", "general")  # 获取分类，默认general

        logger.info(f"[FunctionTrigger] AI计算机语言：查询工具列表 - 分类={category}")  # 记录日志

        # 【P0-2修复】统一层级切换语音播报
        voice = self._get_voice_instance(context)  # 获取语音实例
        if voice:  # 如果有语音实例
            try:  # 开始异常处理
                voice.speak(SystemAnnouncements.QUERYING, is_system=True, wait=False)  # 播报
            except Exception as e:  # 捕获异常
                logger.debug(f"语音播报失败，静默降级: {e}")
                # 降级逻辑：已静默处理，无需额外操作

        if working_memory:  # 如果有工作记忆
            old_stage = working_memory.query_stage  # 保存旧阶段
            working_memory.query_stage = "layer2"  # 切换到L2
            working_memory.current_category = category  # 设置当前分类
            working_memory.current_tool = None  # 清空当前工具

            # 记录层级切换
            if hasattr(working_memory, 'record_layer_switch'):  # 如果有记录方法
                working_memory.record_layer_switch(old_stage, "layer2", "QUERY_TOOL_LIST")  # 记录切换

            working_memory.append({  # 添加系统消息到工作记忆
                "role": "system",  # 角色为系统
                "content": f"【工具列表查询】已切换到L2，查看分类: {category}"  # 消息内容
            })

        return TriggerResult(  # 返回结果
            success=True,  # 成功标志
            message=f"已进入工具列表查询模式 (分类: {category})",  # 消息内容
            should_continue=True  # 继续循环
        )

    def _trigger_query_tool_detail(self,  # 定义触发查询工具详情的私有方法（新增）
                                   context: dict[str, Any]  # 参数：上下文字典
                                   ) -> TriggerResult:  # 返回：触发结果
        """触发查询工具详情 - 进入L3（新增）"""  # 方法文档字符串
        working_memory = context.get("working_memory")  # 获取工作记忆
        params = context.get("params", {})  # 获取参数字典

        tool_id = params.get("tool_id")  # 获取工具ID
        if not tool_id:  # 如果没有工具ID
            return TriggerResult(  # 返回错误结果
                success=False,  # 失败标志
                message="缺少tool_id参数",  # 错误消息
                should_continue=True  # 继续循环
            )

        logger.info(f"[FunctionTrigger] AI计算机语言：查询工具详情 - 工具={tool_id}")  # 记录日志

        # 【P0-2修复】统一层级切换语音播报
        voice = self._get_voice_instance(context)  # 获取语音实例
        if voice:  # 如果有语音实例
            try:  # 开始异常处理
                voice.speak(SystemAnnouncements.QUERYING, is_system=True, wait=False)  # 播报
            except Exception as e:  # 捕获异常
                logger.debug(f"语音播报失败，静默降级: {e}")
                # 降级逻辑：已静默处理，无需额外操作

        if working_memory:  # 如果有工作记忆
            old_stage = working_memory.query_stage  # 保存旧阶段
            working_memory.query_stage = "layer3"  # 切换到L3
            working_memory.current_tool = tool_id  # 设置当前工具

            # 记录层级切换
            if hasattr(working_memory, 'record_layer_switch'):  # 如果有记录方法
                working_memory.record_layer_switch(old_stage, "layer3", "QUERY_TOOL_DETAIL")  # 记录切换

            working_memory.append({  # 添加系统消息到工作记忆
                "role": "system",  # 角色为系统
                "content": f"【工具详情查询】已切换到L3，查看工具: {tool_id}"  # 消息内容
            })

        return TriggerResult(  # 返回结果
            success=True,  # 成功标志
            message=f"已进入工具详情查询模式 (工具: {tool_id})",  # 消息内容
            should_continue=True  # 继续循环
        )

    async def _trigger_record_memory_async(self,  # 定义触发记录记忆的异步私有方法（已迁移）
                                            context: dict[str, Any]  # 参数：上下文字典
                                            ) -> TriggerResult:  # 返回：触发结果
        """触发记录记忆（异步迁移版）"""  # 方法文档字符串
        session_id = context.get("session_id", "console")  # 获取会话ID，默认为console
        working_memory = context.get("working_memory")  # 获取工作记忆
        params = context.get("params", {})  # 获取参数字典

        content = params.get("content", "")  # 获取内容
        memory_type = params.get("type", "experience")  # 获取类型，默认experience

        logger.info(f"[FunctionTrigger] AI计算机语言：记录记忆 - 类型={memory_type}")  # 记录日志

        # 调用记忆系统
        try:  # 开始异常处理
            from core.memory.memory_service import get_memory_service  # 导入新 MemoryService
            ms = await get_memory_service()
            await ms.add_memory(
                user_id=session_id if session_id != "console" else "default_user",
                content=content,
                memory_type=memory_type,
                layer="short",
                scene="ai_recorded",
                tags=["ai_computer_language"],
                source=MemorySource.AI
            )
            logger.info(f"[FunctionTrigger] 记忆已记录: {content[:50]}...")  # 记录日志
        except Exception as e:  # 捕获异常
            logger.debug(f"[FunctionTrigger] 记录记忆失败: {e}")  # 记录调试日志

        if working_memory:  # 如果有工作记忆
            working_memory.append({  # 添加系统消息到工作记忆
                "role": "system",  # 角色为系统
                "content": f"【记忆已记录】{content[:100]}"  # 消息内容
            })

        return TriggerResult(  # 返回结果
            success=True,  # 成功标志
            message="记忆已记录",  # 消息内容
            should_continue=True  # 继续循环
        )

    def _trigger_delete_memory(self,  # 定义触发删除记忆的私有方法（新增）
                               context: dict[str, Any]  # 参数：上下文字典
                               ) -> TriggerResult:  # 返回：触发结果
        """触发删除记忆（新增）"""  # 方法文档字符串
        working_memory = context.get("working_memory")  # 获取工作记忆
        params = context.get("params", {})  # 获取参数字典

        memory_id = params.get("memory_id")  # 获取记忆ID
        logger.info(f"[FunctionTrigger] AI计算机语言：删除记忆 - ID={memory_id}")  # 记录日志

        # 这里可以实现实际的记忆删除逻辑
        # 目前仅记录意图

        if working_memory:  # 如果有工作记忆
            working_memory.append({  # 添加系统消息到工作记忆
                "role": "system",  # 角色为系统
                "content": f"【记忆删除请求】ID: {memory_id}"  # 消息内容
            })

        return TriggerResult(  # 返回结果
            success=True,  # 成功标志
            message=f"记忆删除请求已处理 (ID: {memory_id})",  # 消息内容
            should_continue=True  # 继续循环
        )

    def _trigger_behavior_analyze(self,  # 定义触发行为分析的私有方法（新增）
                                  context: dict[str, Any]  # 参数：上下文字典
                                  ) -> TriggerResult:  # 返回：触发结果
        """触发行为分析（新增）"""  # 方法文档字符串
        working_memory = context.get("working_memory")  # 获取工作记忆
        execution_history = context.get("execution_history", [])  # 获取执行历史

        logger.info("[FunctionTrigger] AI计算机语言：行为分析")  # 记录日志

        # 调用行为分析器
        try:  # 开始异常处理
            from core.behavior_analyzer import get_behavior_analyzer  # 导入行为分析器
            analyzer = get_behavior_analyzer()  # 获取分析器实例

            # 执行工具使用分析
            analysis = analyzer.analyze_tool_usage(execution_history, detailed=True)  # 分析

            if working_memory:  # 如果有工作记忆
                working_memory.append({  # 添加系统消息到工作记忆
                    "role": "system",  # 角色为系统
                    "content": f"【行为分析】{analysis.summary}"  # 消息内容
                })

                # 添加建议
                if analysis.recommendations:  # 如果有建议
                    rec_text = "; ".join(analysis.recommendations[:3])  # 取前3条建议
                    working_memory.append({  # 添加系统消息到工作记忆
                        "role": "system",  # 角色为系统
                        "content": f"【分析建议】{rec_text}"  # 消息内容
                    })

            logger.info(f"[FunctionTrigger] 行为分析完成: {analysis.summary}")  # 记录日志

            return TriggerResult(  # 返回结果
                success=True,  # 成功标志
                message=analysis.summary,  # 消息内容
                data={"analysis": analysis.details},  # 附加数据
                should_continue=True  # 继续循环
            )

        except Exception as e:  # 捕获异常
            logger.debug(f"[FunctionTrigger] 行为分析失败: {e}")  # 记录调试日志
            return TriggerResult(  # 返回错误结果
                success=False,  # 失败标志
                message=f"行为分析失败: {e}",  # 错误消息
                should_continue=True  # 继续循环
            )

    async def _trigger_pause_execution(self,  # 定义触发暂停执行的私有方法
                                  context: dict[str, Any]  # 参数：上下文字典
                                  ) -> TriggerResult:  # 返回：触发结果
        """
        触发暂停执行（增强版 - 集成暂停确认状态机）

        启动强制确认流程：
        1. 记录暂停状态和原因
        2. 等待AI输出理解摘要
        3. 等待用户确认理解正确
        4. 确认后才能恢复
        """  # 方法文档字符串
        session_id = context.get("session_id", "console")  # 获取会话ID，默认为console
        working_memory = context.get("working_memory")  # 获取工作记忆
        voice = self._get_voice_instance(context)  # 获取语音实例
        params = context.get("params", {})  # 获取参数字典

        # 获取暂停原因
        reason = params.get("reason", "用户请求暂停")  # 获取原因，默认"用户请求暂停"

        logger.info(f"[FunctionTrigger] AI计算机语言：暂停执行，原因: {reason}")  # 记录日志

        # 【集成暂停确认状态机】
        try:  # 开始异常处理
            from core.task.long_running_manager import get_long_running_manager  # 导入长任务管理器
            manager = get_long_running_manager()  # 获取管理器实例

            # 尝试获取任务ID（从working_memory或生成临时ID）
            task_id = getattr(working_memory, 'current_task_id', None) or f"task_{session_id}"  # 获取任务ID

            # 启动带强制确认的暂停流程
            task = await manager.pause_task_with_confirmation(  # 暂停任务
                task_id=task_id,  # 任务ID
                reason=reason,  # 原因
                trigger="ai"  # 触发者
            )

            if task:  # 如果暂停成功
                # 获取暂停提示词
                pause_prompt = manager.get_pause_prompt(task_id)  # 获取暂停提示

                if working_memory:  # 如果有工作记忆
                    working_memory.execution_paused = True  # 设置暂停标志
                    working_memory.current_task_id = task_id  # 保存任务ID
                    working_memory.pause_confirmation_state = "paused"  # 设置状态

                    # 添加暂停提示到工作记忆
                    working_memory.append({
                        "role": "system",
                        "content": f"【⏸️ 任务暂停 - 强制确认机制启动】\n\n原因: {reason}\n\n⚠️ 重要：在恢复任务前必须经过以下步骤：\n1. 你必须输出对需求的完整理解摘要\n2. 必须等待用户明确确认理解正确\n3. 未经确认禁止输出 (恢复执行)\n\n系统已准备好，请在下一轮输出你的理解摘要。"
                    })

                    # 保存任务ID到working_memory供后续使用
                    working_memory.pause_task_id = task_id  # 保存任务ID

                message = f"任务已暂停（强制确认模式）: {reason}"  # 消息内容

                # 语音播报
                if voice:  # 如果有语音实例
                    try:
                        voice.speak(DialogueManagerAnnouncements.TASK_PAUSE_CONFIRM, is_system=True, wait=False)  # 播报
                    except Exception as e:
                        logger.debug(f"语音播报失败，静默降级: {e}")
                        # 降级逻辑：已静默处理，无需额外操作

                # 发送事件
                sync = self._get_sync_manager()  # 获取同步管理器
                if sync:  # 如果获取成功
                    sync.emit_event("execution_paused", session_id, {  # 发送事件
                        "action": "pause_execution",  # 动作类型
                        "reason": reason,  # 原因
                        "confirmation_required": True,  # 需要确认
                        "message": message  # 消息内容
                    })

                return TriggerResult(  # 返回结果
                    success=True,  # 成功标志
                    message=message,  # 消息内容
                    should_continue=False,  # 暂停时不继续循环
                    data={"confirmation_required": True, "pause_prompt": pause_prompt}  # 附加数据
                )
        except Exception as e:  # 捕获异常
            logger.error(f"[FunctionTrigger] 启动暂停确认流程失败: {e}")  # 记录错误

        # 降级处理：原始暂停逻辑
        message = "任务执行已暂停，等待进一步指令..."  # 消息内容

        if voice:  # 如果有语音实例
            try:
                voice.speak(DialogueManagerAnnouncements.TASK_PAUSED, is_system=True, wait=False)  # 播报
            except Exception as e:
                logger.debug(f"语音播报失败，静默降级: {e}")
                # 降级逻辑：已静默处理，无需额外操作

        sync = self._get_sync_manager()  # 获取同步管理器
        if sync:  # 如果获取成功
            sync.emit_event("execution_paused", session_id, {  # 发送事件
                "action": "pause_execution",  # 动作类型
                "message": message  # 消息内容
            })

        if working_memory:  # 如果有工作记忆
            working_memory.execution_paused = True  # 设置暂停标志
            working_memory.append({  # 添加系统消息到工作记忆
                "role": "system",  # 角色为系统
                "content": "【执行暂停】任务已暂停，等待恢复指令"  # 消息内容
            })

        return TriggerResult(  # 返回结果
            success=True,  # 成功标志
            message=message,  # 消息内容
            should_continue=False  # 不继续循环
        )

    async def _trigger_resume_execution(self,  # 定义触发恢复执行的私有方法
                                  context: dict[str, Any]  # 参数：上下文字典
                                  ) -> TriggerResult:  # 返回：触发结果
        """
        触发恢复执行（增强版 - 强制确认检查）

        ⚠️ 重要：只有在用户确认理解正确后才能恢复！
        """  # 方法文档字符串
        session_id = context.get("session_id", "console")  # 获取会话ID，默认为console
        working_memory = context.get("working_memory")  # 获取工作记忆
        voice = self._get_voice_instance(context)  # 获取语音实例

        logger.info("[FunctionTrigger] AI计算机语言：恢复执行")  # 记录日志

        # 【强制确认检查】
        try:  # 开始异常处理
            from core.task.long_running_manager import get_long_running_manager  # 导入长任务管理器
            manager = get_long_running_manager()  # 获取管理器实例

            task_id = getattr(working_memory, 'pause_task_id', None) or f"task_{session_id}"  # 获取任务ID

            # 检查是否可以恢复（需要用户确认）
            if not manager.can_resume(task_id):  # 如果不能恢复
                # 无法恢复，获取当前状态
                status = manager.get_confirmation_status(task_id)  # 获取确认状态
                current_prompt = manager.get_pause_prompt(task_id)  # 获取暂停提示

                logger.warning(f"[FunctionTrigger] 任务 {task_id} 未经确认，拒绝恢复")  # 记录警告

                message = "⚠️ 无法恢复任务：必须先获得用户确认！"  # 消息内容

                if working_memory:  # 如果有工作记忆
                    working_memory.append({  # 添加系统消息到工作记忆
                        "role": "system",  # 角色为系统
                        "content": f"【⛔ 恢复被拒绝】{message}\n\n当前状态: {status.get('status', 'unknown')}\n\n{current_prompt}"  # 消息内容
                    })

                # 发送事件
                sync = self._get_sync_manager()  # 获取同步管理器
                if sync:  # 如果获取成功
                    sync.emit_event("resume_rejected", session_id, {  # 发送事件
                        "action": "resume_execution_rejected",  # 动作类型
                        "reason": "未经用户确认",  # 原因
                        "confirmation_status": status,  # 确认状态
                        "message": message  # 消息内容
                    })

                return TriggerResult(  # 返回结果
                    success=False,  # 失败标志
                    message=message,  # 消息内容
                    should_continue=False,  # 不继续循环，等待确认
                    data={"confirmation_required": True, "current_status": status}  # 附加数据
                )

            # 可以恢复，执行恢复操作
            task = await manager.resume_task_with_confirmation(task_id)  # 恢复任务

            if task:  # 如果恢复成功
                message = "任务执行已恢复（已通过确认）"  # 消息内容

                if voice:  # 如果有语音实例
                    try:
                        voice.speak(DialogueManagerAnnouncements.TASK_RESUMED, is_system=True, wait=False)  # 播报
                    except Exception as e:
                        logger.debug(f"语音播报失败，静默降级: {e}")
                        # 降级逻辑：已静默处理，无需额外操作

                sync = self._get_sync_manager()  # 获取同步管理器
                if sync:  # 如果获取成功
                    sync.emit_event("execution_resumed", session_id, {  # 发送事件
                        "action": "resume_execution",  # 动作类型
                        "message": message,  # 消息内容
                        "confirmed": True  # 已确认
                    })

                if working_memory:  # 如果有工作记忆
                    working_memory.execution_paused = False  # 清除暂停标志
                    working_memory.pause_confirmation_state = "resumed"  # 设置状态
                    working_memory.append({  # 添加系统消息到工作记忆
                        "role": "system",  # 角色为系统
                        "content": "【✅ 执行恢复】用户已确认理解正确，任务继续执行"  # 消息内容
                    })

                return TriggerResult(  # 返回结果
                    success=True,  # 成功标志
                    message=message,  # 消息内容
                    should_continue=True,  # 继续循环
                    data={"confirmed": True}  # 附加数据
                )

        except Exception as e:  # 捕获异常
            logger.error(f"[FunctionTrigger] 检查恢复确认状态失败: {e}")  # 记录错误

        # 降级处理：原始恢复逻辑
        message = "任务执行已恢复"  # 消息内容

        if voice:  # 如果有语音实例
            try:
                voice.speak(DialogueManagerAnnouncements.TASK_RESUMED, is_system=True, wait=False)  # 播报
            except Exception as e:
                logger.debug(f"语音播报失败，静默降级: {e}")
                # 降级逻辑：已静默处理，无需额外操作

        sync = self._get_sync_manager()  # 获取同步管理器
        if sync:  # 如果获取成功
            sync.emit_event("execution_resumed", session_id, {  # 发送事件
                "action": "resume_execution",  # 动作类型
                "message": message  # 消息内容
            })

        if working_memory:  # 如果有工作记忆
            working_memory.execution_paused = False  # 清除暂停标志
            working_memory.append({  # 添加系统消息到工作记忆
                "role": "system",  # 角色为系统
                "content": "【执行恢复】任务继续执行"  # 消息内容
            })

        return TriggerResult(  # 返回结果
            success=True,  # 成功标志
            message=message,  # 消息内容
            should_continue=True  # 继续循环
        )

    def _trigger_terminate_task(self,  # 定义触发终止任务的私有方法
                                context: dict[str, Any]  # 参数：上下文字典
                                ) -> TriggerResult:  # 返回：触发结果
        """触发终止任务（新增）"""  # 方法文档字符串
        session_id = context.get("session_id", "console")  # 获取会话ID，默认为console
        working_memory = context.get("working_memory")  # 获取工作记忆
        voice = self._get_voice_instance(context)  # 获取语音实例
        params = context.get("params", {})  # 获取参数字典

        reason = params.get("reason", "用户请求")  # 获取原因
        message = f"任务已终止: {reason}"  # 构建消息
        logger.info(f"[FunctionTrigger] AI计算机语言：终止任务 - {reason}")  # 记录日志

        # 语音播报
        if voice:  # 如果有语音实例
            try:
                voice.speak(DialogueManagerAnnouncements.TASK_TERMINATED, is_system=True, wait=False)  # 播报
            except Exception as e:
                logger.debug(f"语音播报失败，静默降级: {e}")
                # 降级逻辑：已静默处理，无需额外操作

        # 发送事件
        sync = self._get_sync_manager()  # 获取同步管理器
        if sync:  # 如果获取成功
            sync.emit_event("task_terminated", session_id, {  # 发送事件
                "action": "terminate_task",  # 动作类型
                "reason": reason,  # 原因
                "message": message  # 消息内容
            })

        if working_memory:  # 如果有工作记忆
            working_memory.task_terminated = True  # 设置终止标志
            working_memory.append({  # 添加系统消息到工作记忆
                "role": "system",  # 角色为系统
                "content": f"【任务终止】原因: {reason}"  # 消息内容
            })

        return TriggerResult(  # 返回结果
            success=True,  # 成功标志
            message=message,  # 消息内容
            should_continue=False  # 终止时不继续循环
        )

    def _trigger_submit_understanding(self,  # 定义触发提交理解摘要的私有方法
                                      context: dict[str, Any]  # 参数：上下文字典
                                      ) -> TriggerResult:  # 返回：触发结果
        """
        触发提交理解摘要（新增 - 用于暂停确认流程）

        AI输出理解摘要后调用，进入等待用户确认状态
        """  # 方法文档字符串
        session_id = context.get("session_id", "console")  # 获取会话ID，默认为console
        working_memory = context.get("working_memory")  # 获取工作记忆
        params = context.get("params", {})  # 获取参数字典

        understanding = params.get("understanding", "")  # 获取理解摘要

        logger.info("[FunctionTrigger] AI计算机语言：提交理解摘要")  # 记录日志

        # 集成暂停确认状态机
        try:  # 开始异常处理
            from core.task.long_running_manager import get_long_running_manager  # 导入长任务管理器
            manager = get_long_running_manager()  # 获取管理器实例

            task_id = getattr(working_memory, 'pause_task_id', None) or f"task_{session_id}"  # 获取任务ID

            # 提交AI理解摘要
            success = manager.submit_ai_understanding(task_id, understanding)  # 提交理解

            if success:  # 如果提交成功
                # 获取等待确认状态的提示（保留调用，返回值当前未使用）
                _await_prompt = manager.get_pause_prompt(task_id)  # noqa: F841

                if working_memory:  # 如果有工作记忆
                    working_memory.pause_confirmation_state = "awaiting_confirmation"  # 设置状态
                    working_memory.append({  # 添加系统消息到工作记忆
                        "role": "system",  # 角色为系统
                        "content": "【⏳ 理解已提交 - 等待用户确认】\n\n已输出理解摘要，正在等待用户确认...\n\n⚠️ 禁止未经确认输出 (恢复执行)\n\n请等待用户明确说\"确认\"或\"正确\"后才能恢复。"  # 消息内容
                    })

                message = "理解摘要已提交，等待用户确认"  # 消息内容

                # 发送事件
                sync = self._get_sync_manager()  # 获取同步管理器
                if sync:  # 如果获取成功
                    sync.emit_event("understanding_submitted", session_id, {  # 发送事件
                        "action": "submit_understanding",  # 动作类型
                        "understanding": understanding[:200] + "..." if len(understanding) > 200 else understanding,  # 截断显示
                        "message": message  # 消息内容
                    })

                return TriggerResult(  # 返回结果
                    success=True,  # 成功标志
                    message=message,  # 消息内容
                    should_continue=False,  # 等待确认时不继续循环
                    data={"awaiting_confirmation": True}  # 附加数据
                )
            else:  # 如果提交失败
                message = "提交理解摘要失败：任务未在暂停状态"  # 错误消息
                if working_memory:  # 如果有工作记忆
                    working_memory.append({  # 添加系统消息到工作记忆
                        "role": "system",  # 角色为系统
                        "content": f"【⚠️ 提交失败】{message}"  # 消息内容
                    })

                return TriggerResult(  # 返回结果
                    success=False,  # 失败标志
                    message=message,  # 消息内容
                    should_continue=True  # 继续循环
                )

        except Exception as e:  # 捕获异常
            logger.error(f"[FunctionTrigger] 提交理解摘要失败: {e}")  # 记录错误

            return TriggerResult(  # 返回错误结果
                success=False,  # 失败标志
                message=f"提交理解摘要失败: {e}",  # 错误消息
                should_continue=True  # 继续循环
            )


# 全局单例
_function_trigger: FunctionTrigger | None = None  # 初始化全局实例为None


def get_function_trigger() -> FunctionTrigger:  # 获取全局FunctionTrigger实例的函数
    """获取全局FunctionTrigger实例"""  # 函数文档字符串
    global _function_trigger  # 声明使用全局变量
    if _function_trigger is None:  # 如果实例尚未创建
        _function_trigger = FunctionTrigger()  # 创建实例
    return _function_trigger  # 返回全局实例


def reset_function_trigger():  # 重置全局实例的函数（主要用于测试）
    """重置全局实例（主要用于测试）"""  # 函数文档字符串
    global _function_trigger  # 声明使用全局变量
    _function_trigger = None  # 重置为None


# ═══════════════════════════════════════════════════════════════════════════════
# 【总结性注释】文件角色、关联关系与核心效果
# ═══════════════════════════════════════════════════════════════════════════════
#
# 【文件角色】
# 本文件（function_trigger.py）是 SiliconBase V5 系统的"底座功能触发器"核心模块。
# 它统一管理所有AI计算机语言标记的触发处理，是AI与系统功能之间的桥梁。
# 通过统一的触发接口，AI可以使用预定义的计算机语言来控制系统的各种功能。
#
# 【在系统中的位置】
# - 位于: SiliconBase_V5/core/function_trigger.py
# - 上游调用: agent_loop.py（AI输出计算机语言标记时触发）
# - 下游使用: 各子系统（learning_system、planner、reflector等）
#
# 【核心数据结构】
# 1. TriggerType(Enum): 21个AI计算机语言标记枚举
#    - 用户交互层（4个）: CALL_USER, ASK_USER, WAIT_CONFIRM, NOTIFY_USER
#    - 工具查询层（3个）: FIND_TOOL, QUERY_TOOL_LIST, QUERY_TOOL_DETAIL
#    - 记忆认知层（3个）: QUERY_MEMORY, RECORD_MEMORY, DELETE_MEMORY
#    - 学习进化层（4个）: ENTER_LEARNING, EXECUTE_PLAN, REFLECT, EVOLVE
#    - 预测感知层（3个）: WORLD_MODEL_PREDICT, VISION_ANALYZE, BEHAVIOR_ANALYZE
#    - 系统控制层（4个）: PAUSE_EXECUTION, RESUME_EXECUTION, TERMINATE_TASK, SUBMIT_UNDERSTANDING
#
# 2. TriggerResult(dataclass): 触发结果封装
#    - success: 是否成功
#    - message: 结果消息
#    - data: 附加数据
#    - should_continue: 是否继续Agent循环
#
# 【关联文件】
# 1. core/agent_loop.py            - Agent主循环
#    * 关系：上游调用者，解析AI输出中的计算机语言标记
#    * 交互：调用 trigger() 方法触发功能
#
# 2. core/learning_system.py       - 学习系统
#    * 关系：下游功能模块
#    * 交互：处理 ENTER_LEARNING 触发，进入L3学习模式
#
# 3. core/planner.py               - 规划器
#    * 关系：下游功能模块
#    * 交互：处理 EXECUTE_PLAN 触发，创建执行计划
#
# 4. core/reflector.py             - 反思系统
#    * 关系：下游功能模块
#    * 交互：处理 REFLECT 触发，执行深度反思
#
# 5. core/evolution.py             - 进化引擎
#    * 关系：下游功能模块
#    * 交互：处理 EVOLVE 触发，触发能力进化
#
# 6. core/world_model.py           - 世界模型
#    * 关系：下游功能模块
#    * 交互：处理 WORLD_MODEL_PREDICT 触发，预测未来状态
#
# 7. core/vision_model.py          - 视觉模型
#    * 关系：下游功能模块
#    * 交互：处理 VISION_ANALYZE 触发，进行视觉分析
#
# 8. core/behavior_analyzer.py     - 行为分析器
#    * 关系：下游功能模块
#    * 交互：处理 BEHAVIOR_ANALYZE 触发，分析执行历史
#
# 9. core/long_running_manager.py  - 长任务管理器
#    * 关系：下游功能模块
#    * 交互：处理 PAUSE_EXECUTION/RESUME_EXECUTION 触发，管理暂停确认状态机
#
# 10. core/realtime_sync.py        - 实时同步管理器
#    * 关系：事件通知模块
#    * 交互：发送事件通知前端UI更新
#
# 11. core/memory.py               - 记忆系统
#    * 关系：下游功能模块
#    * 交互：处理 RECORD_MEMORY/DELETE_MEMORY 触发，操作记忆
#
# 12. core/dialogue_manager.py     - 对话管理器
#    * 关系：辅助获取语音实例
#    * 交互：从中获取voice实例用于播报
#
# 13. core/global_state.py         - 全局状态
#    * 关系：辅助获取语音实例
#    * 交互：从中获取语音接口
#
# 【核心功能效果】
# 1. 标准化交互: AI使用统一的计算机语言与系统交互
# 2. 功能解耦: 各功能模块独立实现，通过触发器连接
# 3. 可扩展性: 新增触发类型只需添加枚举值和处理方法
# 4. 可靠性: 统一的异常处理和错误返回
# 5. 多模态反馈: 支持语音、UI事件、工作记忆多种反馈方式
# 6. 强制确认机制: PAUSE/RESUME 触发集成确认状态机，确保用户理解正确
# 7. 层级切换: FIND_TOOL/QUERY_TOOL_LIST/QUERY_TOOL_DETAIL 触发支持L2/L3层级切换
#
# 【使用场景】
# - AI输出 "(呼叫用户)" 标记时，触发语音播报和UI通知
# - AI输出 "(进入学习)" 标记时，切换到L3学习模式
# - AI输出 "(暂停执行)" 标记时，启动强制确认流程
# - AI输出 "(反思)" 标记时，调用反思系统分析执行过程
# - AI输出 "(查找工具)" 标记时，切换到L2工具查询模式
#
# ═══════════════════════════════════════════════════════════════════════════════
