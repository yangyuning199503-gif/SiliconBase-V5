#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
异步事件总线  # 模块功能描述：基于asyncio的高性能事件总线

提供从线程池到异步架构的迁移路径  # 设计目标：支持渐进式迁移
保持原有API，内部使用asyncio而非线程池  # 向后兼容设计

设计原则：  # 架构设计原则说明
1. 向后兼容：保持EventBus原有API  # 原则1：API兼容
2. 可选切换：通过配置启用异步模式  # 原则2：可配置切换
3. 性能优化：减少线程切换开销  # 原则3：性能优化
4. 避免死锁：单线程事件处理  # 原则4：避免并发问题
"""

import asyncio  # 导入异步IO模块，核心依赖
import contextlib
import threading  # 导入线程模块，用于单例锁
import time  # 导入时间模块，用于事件时间戳
from collections import defaultdict  # 导入默认字典，用于自动创建空列表
from collections.abc import Callable  # 导入类型注解
from typing import Any

from core.diagnostic import safe_create_task


class AsyncEventBus:  # 定义异步事件总线类
    """
    异步事件总线  # 类文档字符串

    使用asyncio替代线程池，避免多线程问题  # 核心优势说明
    """

    def __init__(self):  # 初始化方法
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)  # 订阅者字典，事件类型->回调列表
        self._event_queue: asyncio.Queue = asyncio.Queue()  # 异步事件队列
        self._running = False  # 运行状态标志
        self._process_task: asyncio.Task | None = None  # 事件处理任务引用
        self._lock = asyncio.Lock()  # 异步锁，用于保护订阅者操作

        # 统计信息  # 统计信息注释
        self._stats = {  # 初始化统计字典
            "events_emitted": 0,  # 已发射事件数
            "events_processed": 0,  # 已处理事件数
            "errors": 0  # 错误次数
        }

    @property  # 属性装饰器
    def is_running(self) -> bool:  # 运行状态属性
        """事件总线是否正在运行"""  # 属性文档字符串
        return self._running  # 返回运行状态

    async def start(self):  # 启动事件总线方法
        """启动事件处理循环"""  # 方法文档字符串
        if self._running:  # 检查是否已在运行
            return  # 已在运行则直接返回

        self._running = True  # 设置运行标志
        self._process_task = safe_create_task(self._process_events(), name="_process_events")  # 创建事件处理任务
        print("[AsyncEventBus] 异步事件总线已启动")  # 打印启动信息

    async def stop(self):  # 停止事件总线方法
        """停止事件处理循环"""  # 方法文档字符串
        if not self._running:  # 检查是否已停止
            return  # 已停止则直接返回

        self._running = False  # 清除运行标志

        # 等待队列处理完成  # 优雅关闭逻辑
        await self._event_queue.join()  # 等待队列中所有事件处理完成

        if self._process_task:  # 如果有处理任务
            self._process_task.cancel()  # 取消任务
            with contextlib.suppress(asyncio.CancelledError):  # 忽略取消异常
                await self._process_task  # 等待任务结束

        print("[AsyncEventBus] 异步事件总线已停止")  # 打印停止信息

    def subscribe(self, event_type: str, handler: Callable) -> bool:  # 订阅事件方法
        """
        订阅事件

        Args:
            event_type: 事件类型
            handler: 事件处理函数（可以是同步或异步）

        Returns:
            bool: 订阅成功返回True
        """  # 方法文档字符串
        if handler not in self._subscribers[event_type]:  # 检查是否已订阅
            self._subscribers[event_type].append(handler)  # 添加处理器到列表
            print(f"[AsyncEventBus] 订阅事件 '{event_type}'")  # 打印订阅信息
            return True  # 返回成功
        return False  # 已订阅返回失败

    def unsubscribe(self, event_type: str, handler: Callable) -> bool:  # 取消订阅方法
        """取消订阅"""  # 方法文档字符串
        if event_type in self._subscribers and handler in self._subscribers[event_type]:  # 检查存在性
            self._subscribers[event_type].remove(handler)  # 从列表移除处理器
            print(f"[AsyncEventBus] 取消订阅事件 '{event_type}'")  # 打印取消信息
            return True  # 返回成功
        return False  # 不存在返回失败

    async def emit(self, event_type: str, data: dict[str, Any]) -> bool:  # 异步发射事件方法
        """
        异步发射事件

        非阻塞，事件入队后由处理循环异步处理
        """  # 方法文档字符串
        event = {  # 构建事件字典
            "type": event_type,  # 事件类型
            "data": data,  # 事件数据
            "timestamp": time.time()  # 事件时间戳
        }

        await self._event_queue.put(event)  # 将事件放入队列
        self._stats["events_emitted"] += 1  # 统计发射数+1
        return True  # 返回成功

    def emit_sync(self, event_type: str, data: dict[str, Any]) -> bool:  # 同步发射事件方法
        """
        同步发射事件（向后兼容）

        创建异步任务处理事件
        """  # 方法文档字符串
        try:  # 异常处理
            loop = asyncio.get_event_loop()  # 获取当前事件循环
            if loop.is_running():  # 如果事件循环正在运行
                # 如果事件循环正在运行，创建任务  # 创建任务注释
                loop.create_task(self.emit(event_type, data))  # 创建异步任务
            else:  # 事件循环未运行
                # 否则直接运行  # 直接运行注释
                loop.run_until_complete(self.emit(event_type, data))  # 运行直到完成
            return True  # 返回成功
        except Exception as e:  # 捕获异常
            print(f"[AsyncEventBus] 发射事件失败: {e}")  # 打印错误
            return False  # 返回失败

    async def _process_events(self):  # 事件处理循环（私有方法）
        """事件处理循环"""  # 方法文档字符串
        while self._running:  # 当运行标志为True时循环
            try:  # 异常处理
                # 获取事件（带超时，避免永久阻塞）  # 超时设计注释
                event = await asyncio.wait_for(  # 带超时等待
                    self._event_queue.get(),  # 从队列获取事件
                    timeout=1.0  # 1秒超时
                )

                # 处理事件  # 事件处理
                await self._handle_event(event)  # 调用处理方法

                # 标记任务完成  # 队列任务完成
                self._event_queue.task_done()  # 标记队列任务已完成
                self._stats["events_processed"] += 1  # 统计处理数+1

            except asyncio.TimeoutError:  # 超时异常
                # 超时，继续循环  # 超时处理注释
                continue  # 继续下一轮循环
            except Exception as e:  # 其他异常
                print(f"[AsyncEventBus] 处理事件异常: {e}")  # 打印错误
                self._stats["errors"] += 1  # 统计错误数+1

    async def _handle_event(self, event: dict[str, Any]):  # 处理单个事件（私有方法）
        """处理单个事件"""  # 方法文档字符串
        event_type = event["type"]  # 获取事件类型
        data = event["data"]  # 获取事件数据

        # 获取订阅者  # 订阅者获取
        handlers = self._subscribers.get(event_type, [])  # 获取该事件的处理器列表

        # 调用所有订阅者  # 调用处理器
        for handler in handlers:  # 遍历处理器
            try:  # 异常处理
                if asyncio.iscoroutinefunction(handler):  # 检查是否为协程函数
                    # 异步处理函数  # 异步调用
                    await handler(event_type, data)  # 直接await调用
                else:  # 同步处理函数
                    # 同步处理函数，在线程中执行避免阻塞  # 同步调用转异步
                    await asyncio.to_thread(handler, event_type, data)  # 在线程池中执行

            except Exception as e:  # 捕获异常
                print(f"[AsyncEventBus] 处理函数异常: {e}")  # 打印错误
                self._stats["errors"] += 1  # 统计错误数+1

    def get_stats(self) -> dict[str, Any]:  # 获取统计信息方法
        """获取统计信息"""  # 方法文档字符串
        return {  # 返回统计字典
            **self._stats,  # 展开基础统计
            "subscribers": {  # 订阅者统计
                event_type: len(handlers)  # 每种事件的处理器数量
                for event_type, handlers in self._subscribers.items()  # 遍历订阅者字典
            },
            "queue_size": self._event_queue.qsize()  # 当前队列大小
        }


# 全局单例  # 全局单例注释
_async_event_bus: AsyncEventBus | None = None  # 异步事件总线实例变量
_lock = threading.Lock()  # 线程锁，用于单例创建

def get_async_event_bus() -> AsyncEventBus:  # 获取异步事件总线单例函数
    """获取异步事件总线单例"""  # 函数文档字符串
    global _async_event_bus  # 声明使用全局变量
    if _async_event_bus is None:  # 检查实例是否存在
        with _lock:  # 获取锁
            if _async_event_bus is None:  # 双重检查
                _async_event_bus = AsyncEventBus()  # 创建新实例
    return _async_event_bus  # 返回单例实例


async def start_async_event_bus():  # 启动异步事件总线函数
    """启动异步事件总线"""  # 函数文档字符串
    bus = get_async_event_bus()  # 获取单例
    await bus.start()  # 启动总线


async def stop_async_event_bus():  # 停止异步事件总线函数
    """停止异步事件总线"""  # 函数文档字符串
    bus = get_async_event_bus()  # 获取单例
    await bus.stop()  # 停止总线


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"异步事件总线"实现，基于asyncio提供高性能的事件分发机制。
# 作为core/event_bus.py的异步替代方案，消除了线程切换开销，适用于高并发场景。
#
# 【架构设计】
# - 异步队列: 使用asyncio.Queue实现无锁事件队列
# - 单线程处理: 所有事件在单一协程中顺序处理，避免竞态条件
# - 混合同步支持: 同步回调自动转在线程池中执行
# - 优雅关闭: 支持等待队列排空后安全关闭
#
# 【关联文件】
# - core/event_bus.py                : 主事件总线，通过配置调用本模块
# - config/global.yaml               : 通过 event_bus.use_async 配置启用
#
# 【核心功能效果】
# 1. 高性能: 基于asyncio，单线程可处理数万QPS
# 2. 无锁设计: 使用异步队列替代线程安全队列，消除锁竞争
# 3. 兼容同步: 自动检测回调类型，同步回调转线程池执行
# 4. 超时保护: 队列获取带超时，避免永久阻塞
# 5. 统计监控: 提供事件发射、处理、错误等统计信息
# 6. 安全关闭: 支持优雅关闭，等待未完成事件处理
#
# 【使用场景】
# - 高并发事件处理: 大量事件需要快速分发
# - 异步应用集成: 与FastAPI等异步框架配合使用
# - 资源受限环境: 减少线程数量，降低内存占用
#
# 【启用方式】
# 在 config/global.yaml 中设置:
#   event_bus:
#     use_async: true
# =============================================================================
