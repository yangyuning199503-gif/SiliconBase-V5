#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
任务事件适配器 - 连接 V6 事件总线与 V5 任务队列  # 模块功能概述

实现功能：  # 功能列表
1. 监听 MSG_TASK_PROPOSED 事件  # 功能1
2. 将事件消息转换为 Task 对象  # 功能2
3. 推送到现有 task_queue  # 功能3

这是向后兼容的关键层，确保新的基于事件的 Consciousness  # 兼容性说明
可以与现有的基于 task_queue 的执行系统协同工作。  # 兼容目的

依赖：  # 依赖说明
    - core.event_bus: 事件总线  # 依赖1
    - core.task_queue: 现有任务队列  # 依赖2
    - core.protocol: 消息协议定义  # 依赖3
"""  # 文档字符串结束

import contextlib
import threading  # 导入线程模块
import time  # 导入时间模块

from core.logger import logger  # 导入日志记录器
from core.mode.work_mode_manager import WorkMode, get_work_mode_manager
from core.protocol import (  # 导入协议相关
    MSG_TASK_ACCEPTED,
    MSG_TASK_PROPOSED,  # 消息类型
    MSG_TASK_REJECTED,
    MSG_TASK_REQUEST,
    get_message_summary,
    is_valid_message,  # 工具函数
    priority_to_number,
)  # 导入结束
from core.sync.event_bus import event_bus  # 导入事件总线
from core.task.task_queue import Task, task_queue  # 导入任务和任务队列


class TaskEventAdapter:  # 定义任务事件适配器类
    """  # 类文档字符串开始
    任务事件适配器  # 类功能

    将 V6 标准化事件协议适配到 V5 任务队列系统。  # 适配说明
    实现事件驱动架构与现有命令式架构的桥接。  # 桥接说明
    """  # 类文档字符串结束

    _instance = None  # 单例实例引用  # 类级实例引用
    _lock = threading.Lock()  # 线程锁  # 类级锁

    def __new__(cls):  # 重写实例创建方法
        with cls._lock:  # 获取锁
            if cls._instance is None:  # 如果实例不存在
                cls._instance = super().__new__(cls)  # 创建新实例
                cls._instance._initialized = False  # 标记未初始化
        return cls._instance  # 返回实例

    def __init__(self):  # 初始化方法
        if self._initialized:  # 如果已初始化
            return  # 直接返回
        self._initialized = True  # 标记已初始化

        # 事件订阅ID列表，用于后续取消订阅  # 注释：订阅管理
        self._subscriptions = []  # 订阅ID列表

        # 统计信息  # 注释：统计
        self._stats = {  # 统计字典
            "tasks_proposed": 0,  # 提案任务数
            "tasks_accepted": 0,  # 接受任务数
            "tasks_rejected": 0,  # 拒绝任务数
            "errors": 0  # 错误数
        }  # 统计字典结束

        # 订阅事件  # 注释：订阅事件
        self._subscribe_events()  # 调用订阅方法

        logger.info("任务事件适配器初始化完成")  # 记录日志

    def _subscribe_events(self):  # 定义订阅事件方法
        """订阅任务相关事件"""  # 方法文档字符串
        # 监听内部任务提案（来自 Consciousness）  # 注释：监听提案
        sub_id = event_bus.subscribe(MSG_TASK_PROPOSED, self._on_task_proposed)  # 订阅
        self._subscriptions.append(sub_id)  # 添加订阅ID

        # 监听正式任务请求（来自其他模块）  # 注释：监听请求
        sub_id = event_bus.subscribe(MSG_TASK_REQUEST, self._on_task_proposed)  # 订阅
        self._subscriptions.append(sub_id)  # 添加订阅ID

        # 使用通配符监听所有任务相关事件（用于日志统计）  # 注释：监听所有
        sub_id = event_bus.subscribe("task:*", self._on_any_task_event)  # 订阅
        self._subscriptions.append(sub_id)  # 添加订阅ID

    async def _on_task_proposed(self, event):  # 定义任务提案处理方法
        """  # 方法文档字符串开始
        处理任务提案/请求事件  # 方法功能

        将标准化的任务消息转换为 Task 对象并推送到队列。  # 处理逻辑

        Args:  # 参数说明
            event: EventBus 传入的 Event 对象，event.data 为 AgentMessage 或 payload  # 参数1
        """  # 方法文档字符串结束

        # 兼容 Event 对象和直接 dict
        msg = event.data if hasattr(event, 'data') else event
        event_type = event.name if hasattr(event, 'name') else None

        # 专注模式下忽略思维线程发来的任务提案
        try:
            mode_manager = get_work_mode_manager()
            current_mode = mode_manager.get_current_mode()
            if current_mode == WorkMode.FOCUS:
                logger.debug("[TaskEventAdapter] 专注模式下忽略思维线程任务提案")
                return
        except Exception as e:
            logger.warning(f"[TaskEventAdapter] 无法获取工作模式，放行提案: {e}")

        self._stats["tasks_proposed"] += 1  # 增加提案计数

        try:  # 异常处理
            # 提取 payload  # 注释：提取payload
            if is_valid_message(msg):  # 如果是有效消息
                payload = msg.get("payload", {})  # 从消息获取payload
                trace_id = msg.get("trace_id", "unknown")  # 获取跟踪ID
                source = msg.get("source", "unknown")  # 获取来源
            else:  # 直接传入payload的情况
                # 兼容直接传入 payload 的情况  # 注释：兼容处理
                payload = msg  # 直接使用msg作为payload
                trace_id = "direct"  # 设置跟踪ID
                source = payload.get("source", "unknown")  # 获取来源

            # 验证必要字段  # 注释：验证字段
            goal = payload.get("goal") or payload.get("action")  # 获取目标或动作
            if not goal:  # 如果没有目标
                logger.warning(f"任务提案缺少目标，忽略 [{trace_id}]")  # 记录警告
                self._stats["tasks_rejected"] += 1  # 增加拒绝计数
                return  # 直接返回

            # 提取优先级  # 注释：提取优先级
            priority_str = payload.get("priority", "normal")  # 获取优先级字符串
            if isinstance(priority_str, str):  # 如果是字符串
                priority = priority_to_number(priority_str)  # 转换为数字
                # 转换为 1-10 的优先级（数值越小优先级越高）  # 注释：优先级转换
                priority = min(10, max(1, priority * 3))  # 限制范围
            else:  # 如果是数字
                priority = int(priority_str)  # 转为整数

            # 创建 Task 对象  # 注释：创建任务
            task = Task(  # 创建任务
                type="user",  # 类型为用户任务
                intent={"raw": goal},  # 意图
                priority=priority,  # 优先级
                session_id="consciousness" if source == "consciousness" else "event_adapter",  # 会话ID
                metadata={  # 元数据
                    "source": source,  # 来源
                    "trace_id": trace_id,  # 跟踪ID
                    "original_event": event_type,  # 原始事件
                    **payload.get("context", {})  # 合并上下文
                }  # 元数据结束
            )  # 任务创建结束

            # 推送到任务队列  # 注释：推送任务
            await task_queue.push_async(task, front=(priority <= 3))  # 高优先级放队首

            self._stats["tasks_accepted"] += 1  # 增加接受计数

            # 向经验总线发布任务入队事件
            try:
                from core.consciousness.Consciousness import get_consciousness
                from core.consciousness.experience_bus import ExperienceEvent
                consciousness = get_consciousness()
                if consciousness and getattr(consciousness, 'experience_bus', None):
                    import asyncio
                    evt = ExperienceEvent(
                        source="task_scheduler", event_type="task_enqueued",
                        timestamp=time.time(), context={"task_id": task.id, "source": "consciousness_proposal"},
                        action="enqueue_task", outcome=0.6
                    )
                    with contextlib.suppress(RuntimeError):
                        asyncio.get_running_loop().create_task(consciousness.experience_bus.publish(evt))
            except Exception:
                pass

            logger.info(f"任务已接受并推送到队列 [{trace_id}]: {goal[:50]}...")  # 记录日志

            # 广播任务被接受的事件  # 注释：广播接受事件
            stats = await task_queue.get_stats_async()
            event_bus.emit(MSG_TASK_ACCEPTED, {  # 发送事件
                "task_id": payload.get("task_id", "unknown"),  # 任务ID
                "trace_id": trace_id,  # 跟踪ID
                "queue_position": stats.get("queue_size", 0)  # 队列位置
            })  # 事件发送结束

        except Exception as e:  # 捕获异常
            self._stats["errors"] += 1  # 增加错误计数
            logger.error(f"处理任务提案时出错: {e}", exc_info=True)  # 记录错误

            # 广播任务被拒绝的事件  # 注释：广播拒绝事件
            if is_valid_message(msg):  # 如果是有效消息
                event_bus.emit(MSG_TASK_REJECTED, {  # 发送事件
                    "trace_id": msg.get("trace_id", "unknown"),  # 跟踪ID
                    "reason": str(e)  # 原因
                })  # 事件发送结束

    def _on_any_task_event(self, event):  # 定义任意任务事件处理方法
        """  # 方法文档字符串开始
        监听所有任务事件（用于统计和调试）  # 方法功能

        Args:  # 参数说明
            event: EventBus 传入的 Event 对象  # 参数1
        """  # 方法文档字符串结束
        if logger.isEnabledFor(logger.DEBUG):  # 如果启用了DEBUG日志
            msg = event.data if hasattr(event, 'data') else event
            event_type = event.name if hasattr(event, 'name') else "unknown"
            if is_valid_message(msg):  # 如果是有效消息
                summary = get_message_summary(msg)  # 获取消息摘要
                logger.debug(f"[TaskEvent] {event_type}: {summary}")  # 记录调试日志

    def get_stats(self) -> dict[str, int]:  # 定义获取统计方法
        """获取适配器统计信息"""  # 方法文档字符串
        return self._stats.copy()  # 返回统计副本

    def reset_stats(self):  # 定义重置统计方法
        """重置统计信息"""  # 方法文档字符串
        self._stats = {  # 重置统计字典
            "tasks_proposed": 0,  # 提案数归零
            "tasks_accepted": 0,  # 接受数归零
            "tasks_rejected": 0,  # 拒绝数归零
            "errors": 0  # 错误数归零
        }  # 重置结束

    def shutdown(self):  # 定义关闭方法
        """清理资源，取消事件订阅"""  # 方法文档字符串
        logger.info("[TaskEventAdapter] 正在关闭，取消事件订阅...")  # 记录日志
        for sub_id in self._subscriptions:  # 遍历订阅ID
            try:  # 异常处理
                event_bus.unsubscribe(sub_id)  # 取消订阅
            except Exception as e:  # 捕获异常
                logger.debug(f"[TaskEventAdapter] 取消订阅失败 {sub_id}: {e}")  # 记录调试
        self._subscriptions.clear()  # 清空订阅列表
        logger.info("[TaskEventAdapter] 事件订阅已清理完成")  # 记录日志


# ============================================================================  # 分隔注释：全局单例
# 全局单例  # 区域标题
# ============================================================================  # 分隔线

task_event_adapter = TaskEventAdapter()  # 实例化全局适配器


# ============================================================================  # 分隔注释：便捷函数
# 便捷函数  # 区域标题
# ============================================================================  # 分隔线

def get_adapter_stats() -> dict[str, int]:  # 定义获取适配器统计函数
    """获取适配器统计信息"""  # 函数文档字符串
    return task_event_adapter.get_stats()  # 调用适配器方法


def reset_adapter_stats():  # 定义重置适配器统计函数
    """重置适配器统计信息"""  # 函数文档字符串
    task_event_adapter.reset_stats()  # 调用适配器方法


def start_adapter():  # 定义启动适配器函数
    """  # 函数文档字符串开始
    启动适配器  # 函数功能

    实际上适配器在导入时已经初始化，此函数用于显式确认启动。  # 说明
    """  # 函数文档字符串结束
    logger.info("任务事件适配器已启动")  # 记录日志
    return task_event_adapter  # 返回适配器实例


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"任务事件适配器"，作为V6事件总线与V5任务队列
# 之间的桥梁，实现事件驱动架构与命令式架构的兼容。
#
# 【核心功能】
# 1. 事件监听: 订阅MSG_TASK_PROPOSED、MSG_TASK_REQUEST等任务相关事件
# 2. 协议转换: 将标准化事件消息转换为Task对象
# 3. 任务推送: 将转换后的Task推送到V5任务队列
# 4. 事件反馈: 广播MSG_TASK_ACCEPTED、MSG_TASK_REJECTED事件
# 5. 统计监控: 记录任务提案、接受、拒绝、错误等统计数据
#
# 【关联文件】
# - core/event_bus.py             : 事件总线，本模块订阅和发送事件
# - core/task_queue.py            : V5任务队列，本模块将任务推送到此
# - core/protocol.py              : 消息协议定义(MSG_TASK_PROPOSED等)
# - core/logger.py                : 日志记录
#
# 【事件流程】
# 1. Consciousness或其他模块通过event_bus.emit(MSG_TASK_PROPOSED, {...})提案任务
# 2. TaskEventAdapter._on_task_proposed()接收事件
# 3. 提取goal、priority、source等信息，创建Task对象
# 4. 调用task_queue.push()推送任务
# 5. 广播MSG_TASK_ACCEPTED或MSG_TASK_REJECTED事件
#
# 【使用场景】
# - 意识层(Consciousness)提出任务提案
# - 外部系统通过事件总线提交任务
# - 需要向后兼容V5任务队列的模块
#
# 【注意事项】
# - 适配器是单例模式，导入时自动初始化
# - 高优先级任务(priority<=3)会插队到队首
# - 需要显式调用shutdown()清理事件订阅
# =============================================================================
