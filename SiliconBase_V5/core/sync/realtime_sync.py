#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
实时同步管理器 - 为双AI联动提供事件推送 V5.2  # 模块功能：实时事件同步管理
- 内存事件存储（单实例模式）  # 模式1：单实例内存存储
- Redis Pub/Sub（多实例模式）  # 模式2：多实例Redis模式
- 自动降级到内存模式  # 降级策略

Redis Key规范：  # Redis键名规范说明
- pubsub:{user_id} -> Channel (实时事件通道)  # Pub/Sub通道命名
"""
import asyncio  # 导入asyncio模块，用于异步支持
import contextlib
import json  # 导入JSON模块，用于数据序列化
import logging  # 导入日志模块
import os  # 导入os模块，用于环境变量读取
import threading  # 导入线程模块，用于并发控制
import time  # 导入时间模块
from collections.abc import Callable  # 导入类型注解
from dataclasses import dataclass  # 导入数据类和工具
from datetime import datetime, timedelta  # 导入日期时间类
from typing import Any

from core.diagnostic import safe_create_task

logger = logging.getLogger(__name__)  # 获取当前模块的logger

# 可选的Redis支持  # 可选依赖处理
REDIS_AVAILABLE = False  # Redis可用标志，默认False
try:  # 尝试导入Redis模块
    from core.redis_backend import RedisKeyBuilder, RedisStorageBackend, is_redis_available  # 导入Redis后端
    REDIS_AVAILABLE = True  # 标记Redis可用
except ImportError:  # 导入失败
    REDIS_AVAILABLE = False  # 标记Redis不可用


@dataclass  # 数据类装饰器
class SyncEvent:  # 定义同步事件数据类
    """同步事件数据结构"""  # 类文档字符串
    event_type: str  # 事件类型字段
    timestamp: str  # 时间戳字段
    session_id: str  # 会话ID字段
    data: dict[str, Any]  # 事件数据字典
    user_id: str = "default_user"  # 新增：用户ID用于隔离，默认default_user

    def to_dict(self) -> dict:  # 转换为字典方法
        """转换为字典"""  # 方法文档字符串
        return {  # 返回包含所有字段的字典
            "type": self.event_type,  # 事件类型（前端兼容：使用type而非event_type）
            "timestamp": self.timestamp,  # 时间戳
            "session_id": self.session_id,  # 会话ID
            "data": self.data,  # 事件数据
            "user_id": self.user_id  # 用户ID
        }

    @classmethod  # 类方法装饰器
    def from_dict(cls, data: dict) -> "SyncEvent":  # 从字典创建实例
        """从字典创建SyncEvent实例"""  # 方法文档字符串
        return cls(  # 创建并返回实例
            event_type=data.get("type") or data.get("event_type", ""),  # 获取事件类型（兼容type和event_type）
            timestamp=data.get("timestamp", ""),  # 获取时间戳
            session_id=data.get("session_id", ""),  # 获取会话ID
            data=data.get("data", {}),  # 获取数据字典
            user_id=data.get("user_id", "default_user")  # 获取用户ID，带默认值
        )


class RealtimeSyncManager:  # 定义实时同步管理器类
    """
    实时同步管理器
    支持内存模式和Redis Pub/Sub模式
    """  # 类文档字符串
    _instance = None  # 单例实例存储
    _lock = threading.Lock()  # 类级锁

    def __new__(cls, use_redis: bool = None):  # 重写new方法实现单例
        if cls._instance is None:  # 检查实例是否存在
            with cls._lock:  # 获取锁
                if cls._instance is None:  # 双重检查
                    cls._instance = super().__new__(cls)  # 创建实例
                    cls._instance._initialized = False  # 标记未初始化
        return cls._instance  # 返回单例

    def __init__(self, use_redis: bool = None):  # 初始化方法
        if self._initialized:  # 检查是否已初始化
            return  # 已初始化则返回
        self._initialized = True  # 标记已初始化

        # 配置  # 配置注释
        self._use_redis = use_redis  # 设置Redis使用标志
        if self._use_redis is None:  # 如果未指定
            self._use_redis = os.getenv("STORAGE_BACKEND", "memory") == "redis"  # 从环境变量读取

        # 内存存储（作为降级方案）  # 内存存储初始化
        self._session_events: dict[str, list[SyncEvent]] = {}  # 会话事件字典
        self._global_events: list[SyncEvent] = []  # 全局事件列表
        self._max_events_per_session = 100  # 每会话最大事件数
        self._max_global_events = 200  # 全局最大事件数
        self._callbacks: list[Callable] = []  # 回调函数列表
        self._active_session_id: str | None = None  # 当前活跃会话ID
        self._data_lock = threading.RLock()  # 数据锁，保护共享数据

        # Redis相关  # Redis配置
        self._redis_backend: Any | None = None  # Redis后端实例
        self._pubsub: Any | None = None  # Pub/Sub实例
        self._pubsub_thread: threading.Thread | None = None  # 订阅线程
        self._subscribed_channels: set = set()  # 已订阅通道集合

        if self._use_redis and REDIS_AVAILABLE:  # 如果启用Redis且可用
            try:  # 异常处理
                self._redis_backend = RedisStorageBackend()  # 直接创建Redis后端
                logger.info("[RealtimeSyncManager] Redis Pub/Sub已启用")  # 记录日志
            except Exception as e:  # 捕获异常
                logger.error(f"[RealtimeSyncManager] Redis初始化失败: {e}")  # 记录错误
                self._use_redis = False  # 禁用Redis

        # 启动清理线程（内存模式）  # 清理线程
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)  # 创建守护线程
        self._cleanup_thread.start()  # 启动清理线程

    async def _is_redis_ready_async(self) -> bool:  # 检查Redis是否就绪
        """检查Redis是否就绪"""  # 方法文档字符串
        if not self._use_redis or not self._redis_backend:  # 检查配置和实例
            return False  # 未启用或未初始化
        return await is_redis_available()  # 调用异步检查函数

    def _get_channel_name(self, user_id: str) -> str:  # 获取通道名
        """获取Pub/Sub通道名"""  # 方法文档字符串
        if REDIS_AVAILABLE:  # 如果Redis可用
            return RedisKeyBuilder.pubsub_channel(user_id)  # 使用RedisKeyBuilder
        return f"pubsub:{user_id}"  # 返回默认格式

    def emit_event(self, event_type: str, session_id: str, data: dict = None, user_id: str = None):
        """
        发送事件（同步快捷方法）。
        内存操作立即完成，Redis publish 在后台异步执行，不阻塞调用方。
        """
        user_id = user_id or "default_user"

        event = SyncEvent(
            event_type=event_type,
            timestamp=datetime.now().isoformat(),
            session_id=session_id,
            data=data or {},
            user_id=user_id
        )

        # 1. 写入内存（同步，不阻塞）
        with self._data_lock:
            if session_id not in self._session_events:
                self._session_events[session_id] = []
            self._session_events[session_id].append(event)
            if len(self._session_events[session_id]) > self._max_events_per_session:
                self._session_events[session_id].pop(0)

            self._global_events.append(event)
            if len(self._global_events) > self._max_global_events:
                self._global_events.pop(0)

            if event_type == "start":
                self._active_session_id = session_id

        # 2. Redis publish 后台异步执行（不阻塞事件循环）
        if self._use_redis and self._redis_backend:
            try:
                asyncio.get_running_loop()
                channel = self._get_channel_name(user_id)
                message = json.dumps(event.to_dict(), ensure_ascii=False)
                safe_create_task(self._redis_backend.publish(channel, message), name="publish")
            except RuntimeError:
                pass  # 无事件循环，跳过 Redis

        # 3. 触发本地回调
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception as e:
                logger.error(f"[RealtimeSyncManager] 回调执行失败: {e}")

    async def emit_event_async(self, event_type: str, session_id: str, data: dict = None, user_id: str = None):  # 发送事件方法
        """
        发送事件（异步版，await 可确保 Redis publish 完成）

        Args:
            event_type: 事件类型
            session_id: 会话ID
            data: 事件数据
            user_id: 用户ID（可选，默认default_user）
        """  # 方法文档字符串
        user_id = user_id or "default_user"  # 设置默认用户ID

        event = SyncEvent(  # 创建事件对象
            event_type=event_type,  # 事件类型
            timestamp=datetime.now().isoformat(),  # ISO格式时间戳
            session_id=session_id,  # 会话ID
            data=data or {},  # 事件数据，默认为空字典
            user_id=user_id  # 用户ID
        )

        # 1. 写入内存（始终写入，作为降级方案）  # 内存写入
        with self._data_lock:  # 获取数据锁
            if session_id not in self._session_events:  # 检查会话是否存在
                self._session_events[session_id] = []  # 创建新列表
            self._session_events[session_id].append(event)  # 添加事件
            if len(self._session_events[session_id]) > self._max_events_per_session:  # 检查是否超限
                self._session_events[session_id].pop(0)  # 移除最旧事件

            self._global_events.append(event)  # 添加到全局事件
            if len(self._global_events) > self._max_global_events:  # 检查是否超限
                self._global_events.pop(0)  # 移除最旧事件

            if event_type == "start":  # 如果是开始事件
                self._active_session_id = session_id  # 设置为活跃会话

        # 2. 发布到Redis（如果可用）  # Redis发布
        if await self._is_redis_ready_async():  # 异步检查Redis是否就绪
            try:  # 异常处理
                channel = self._get_channel_name(user_id)  # 获取通道名
                message = json.dumps(event.to_dict(), ensure_ascii=False)  # 序列化为JSON
                await self._redis_backend.publish(channel, message)  # 异步发布消息
            except Exception as e:  # 捕获异常
                logger.error(f"[RealtimeSyncManager] Redis发布失败: {e}")  # 记录错误

        # 3. 触发本地回调  # 回调触发
        for cb in self._callbacks:  # 遍历所有回调
            try:  # 异常处理
                cb(event)  # 调用回调函数
            except Exception as e:  # 捕获异常
                logger.error(f"[RealtimeSyncManager] 回调执行失败: {e}")  # 记录错误

    async def get_session_events_async(self, session_id: str, after_timestamp: str = None, user_id: str = None) -> list[dict]:  # 获取会话事件
        """
        获取会话事件

        Args:
            session_id: 会话ID
            after_timestamp: 只返回此时间之后的事件
            user_id: 用户ID（可选）

        Returns:
            事件字典列表
        """  # 方法文档字符串
        with self._data_lock:  # 获取数据锁
            events = self._session_events.get(session_id, [])  # 获取会话事件
            if after_timestamp:  # 如果有时间过滤条件
                events = [e for e in events if e.timestamp > after_timestamp]  # 过滤事件
            return [e.to_dict() for e in events]  # 转换为字典列表

    def get_active_session(self) -> str | None:  # 获取活跃会话
        """获取当前活跃会话ID"""  # 方法文档字符串
        with self._data_lock:  # 获取数据锁
            return self._active_session_id  # 返回活跃会话ID

    async def get_full_dialogue_chain_async(self, session_id: str, user_id: str = None) -> list[dict]:  # 获取完整对话链
        """
        获取完整对话链

        Args:
            session_id: 会话ID
            user_id: 用户ID（可选）

        Returns:
            对话链列表
        """  # 方法文档字符串
        events = await self.get_session_events_async(session_id, user_id=user_id)  # 异步获取会话事件
        chain = []  # 对话链列表
        for e in events:  # 遍历事件
            event_type = e.get("type") or e.get("event_type", "")  # 获取事件类型（兼容两种字段名）
            item = {  # 创建对话项
                "timestamp": e["timestamp"],  # 时间戳
                "type": event_type,  # 事件类型
                "data": e["data"]  # 事件数据
            }
            if event_type == "start":  # 开始事件
                item["actor"] = "user"  # 角色为用户
                item["content"] = e["data"].get("instruction", "")  # 获取指令内容
            elif event_type == "think_analyzing":  # 思考分析事件
                item["actor"] = "think_ai"  # 角色为思考AI
                item["content"] = f"分析中... [{e['data'].get('step', '')}]"  # 分析内容
            elif event_type == "new_message":  # 新消息事件
                item["actor"] = e["data"].get("from", "")  # 获取发送者
                item["content"] = f"→ {e['data'].get('to', '')}: {e['data'].get('type', '')}"  # 消息内容
            elif event_type == "dialogue_agreed":  # 达成共识事件
                item["actor"] = "system"  # 角色为系统
                item["content"] = f"[OK] 达成共识（{e['data'].get('round', 0)}轮）"  # 共识内容
            elif event_type == "executing":  # 执行中事件
                item["actor"] = "decision_ai"  # 角色为决策AI
                item["content"] = "正在执行..."  # 执行状态
            elif event_type == "executed":  # 执行完成事件
                item["actor"] = "decision_ai"  # 角色为决策AI
                item["content"] = e["data"].get("summary", "执行完成")  # 执行摘要
            elif event_type == "completed":  # 完成事件
                item["actor"] = "system"  # 角色为系统
                item["content"] = f"{'[OK]' if e['data'].get('success') else '[FAIL]'} 处理完成"  # 完成状态
            else:  # 其他事件类型
                item["actor"] = "system"  # 默认系统角色
                item["content"] = str(e["data"])  # 数据转字符串
            chain.append(item)  # 添加到对话链
        return chain  # 返回对话链

    def register_callback(self, callback: Callable):  # 注册回调方法
        """
        注册事件回调

        Args:
            callback: 回调函数，接收SyncEvent参数
        """  # 方法文档字符串
        self._callbacks.append(callback)  # 添加回调到列表

    def unregister_callback(self, callback: Callable):  # 注销回调方法
        """
        注销事件回调

        Args:
            callback: 要注销的回调函数
        """  # 方法文档字符串
        if callback in self._callbacks:  # 检查回调是否存在
            self._callbacks.remove(callback)  # 从列表移除

    async def subscribe_to_channel_async(self, user_id: str, callback: Callable = None) -> bool:  # 订阅通道方法
        """
        订阅Redis通道（多实例同步）

        Args:
            user_id: 用户ID
            callback: 消息回调函数

        Returns:
            是否订阅成功
        """  # 方法文档字符串
        if not await self._is_redis_ready_async():  # 异步检查Redis是否就绪
            return False  # 返回失败

        channel = self._get_channel_name(user_id)  # 获取通道名

        try:  # 异常处理
            pubsub = await self._redis_backend.subscribe(channel)  # 异步订阅通道
            if pubsub:  # 订阅成功
                self._subscribed_channels.add(channel)  # 添加到已订阅集合

                # 启动异步监听任务
                async def listen():  # 定义异步监听函数
                    async for message in pubsub.listen():  # 异步监听消息
                        if message["type"] == "message":  # 如果是消息类型
                            try:  # 异常处理
                                data = json.loads(message["data"])  # 解析JSON
                                event = SyncEvent.from_dict(data)  # 创建事件对象

                                # 更新本地缓存  # 缓存更新
                                with self._data_lock:  # 获取数据锁
                                    if event.session_id not in self._session_events:  # 检查会话
                                        self._session_events[event.session_id] = []  # 创建列表
                                    self._session_events[event.session_id].append(event)  # 添加事件

                                # 触发回调  # 回调触发
                                if callback:  # 如果有回调
                                    callback(event)  # 调用回调
                                for cb in self._callbacks:  # 遍历所有回调
                                    with contextlib.suppress(Exception):  # 捕获并忽略异常
                                        cb(event)  # 调用回调
                            except Exception as e:  # 捕获异常
                                logger.error(f"[RealtimeSyncManager] 处理Redis消息失败: {e}")  # 记录错误

                safe_create_task(listen(), name="listen")  # 创建后台异步任务

                logger.info(f"[RealtimeSyncManager] 已订阅通道: {channel}")  # 记录日志
                return True  # 返回成功
        except Exception as e:  # 捕获异常
            logger.error(f"[RealtimeSyncManager] 订阅通道失败: {e}")  # 记录错误

        return False  # 返回失败

    def _cleanup_loop(self):  # 清理循环（私有方法）
        """定时清理过期事件（超过24小时）"""  # 方法文档字符串
        # DESIGN-NOTE: 实时同步事件清理守护线程，设计为长期运行  # 设计说明
        # 中断机制：主进程退出时daemon线程自动终止  # 中断机制
        # 清理周期：每小时执行一次，清理24小时前的过期事件  # 清理策略
        while True:  # 无限循环
            time.sleep(3600)  # 每小时检查一次，休眠3600秒
            cutoff = (datetime.now() - timedelta(hours=24)).isoformat()  # 计算截止时间
            with self._data_lock:  # 获取数据锁
                # 清理全局事件  # 全局事件清理
                self._global_events = [e for e in self._global_events if e.timestamp >= cutoff]  # 过滤过期事件
                # 清理会话事件  # 会话事件清理
                for session_id in list(self._session_events.keys()):  # 遍历会话
                    self._session_events[session_id] = [e for e in self._session_events[session_id] if e.timestamp >= cutoff]  # 过滤事件
                    if not self._session_events[session_id]:  # 如果会话为空
                        del self._session_events[session_id]  # 删除会话

            logger.debug("[RealtimeSyncManager] 已清理过期事件")  # 记录调试日志

    def get_storage_status(self) -> dict:  # 获取存储状态
        """获取存储状态"""  # 方法文档字符串
        # 同步路径下不调用异步的 _is_redis_ready_async，仅检查实例是否存在
        redis_ready = self._use_redis and self._redis_backend is not None
        return {  # 返回状态字典
            "use_redis": self._use_redis,  # 是否使用Redis
            "redis_available": redis_ready,  # Redis后端实例是否已初始化
            "active_sessions": len(self._session_events),  # 活跃会话数
            "global_events": len(self._global_events),  # 全局事件数
            "subscribed_channels": list(self._subscribed_channels)  # 已订阅通道列表
        }

    async def clear_session_events_async(self, session_id: str):  # 清空会话事件
        """
        清空指定会话的事件

        Args:
            session_id: 会话ID
        """  # 方法文档字符串
        with self._data_lock:  # 获取数据锁
            if session_id in self._session_events:  # 检查会话是否存在
                del self._session_events[session_id]  # 删除会话


def get_realtime_sync_manager(use_redis: bool = None) -> RealtimeSyncManager:  # 获取管理器函数
    """
    获取实时同步管理器实例

    Args:
        use_redis: 是否使用Redis

    Returns:
        RealtimeSyncManager实例
    """  # 函数文档字符串
    return RealtimeSyncManager(use_redis=use_redis)  # 返回单例实例


# 向后兼容  # 向后兼容注释
RealtimeSync = RealtimeSyncManager  # 别名，保持向后兼容


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"实时同步管理器"，负责在双AI架构中传递事件消息。
# 支持单实例内存模式和Redis多实例模式，提供自动降级机制。
#
# 【架构设计】
# - 双模式支持: 内存模式(单实例) + Redis Pub/Sub模式(多实例)
# - 自动降级: Redis不可用时自动降级到内存模式
# - 事件缓存: 按会话和全局分别存储，支持容量限制
# - 回调机制: 支持注册多个回调函数，事件发生时并行通知
# - 多实例同步: Redis模式下支持多实例间事件同步
#
# 【关联文件】
# - core/redis_backend.py            : Redis存储后端实现
# - api/cloud_api.py /ws/*           : WebSocket端点，注册回调接收事件
# - core/agent_loop.py               : 任务循环，发射各类任务事件
# - core/long_running_manager.py     : 长任务管理，发射暂停/恢复事件
#
# 【核心功能效果】
# 1. 双AI联动: 支持Think AI和Decision AI之间的实时通信
# 2. 事件追溯: 提供get_full_dialogue_chain_async()构建完整对话链
# 3. 多租户支持: 通过user_id实现用户数据隔离
# 4. 容量控制: 自动限制每会话和全局事件数量，防止内存溢出
# 5. 定时清理: 每小时自动清理24小时前的过期事件
# 6. 多实例部署: Redis模式支持多实例间的实时事件同步
#
# 【使用场景】
# - 任务状态实时推送: 将任务进度实时推送到前端
# - 双AI通信: Think AI和Decision AI之间的协作消息传递
# - 多实例同步: 分布式部署时的跨实例事件同步
# - 会话恢复: 通过历史事件重建会话上下文
#
# 【Redis配置】
# 设置环境变量启用Redis模式:
#   STORAGE_BACKEND=redis
#   REDIS_URL=redis://localhost:6379/0
# =============================================================================
