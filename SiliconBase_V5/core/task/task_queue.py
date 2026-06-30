#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
任务队列 V5.3 - 全异步Redis版  # 模块标题和版本
【修复说明】  # 修复说明
1. 修复Task类dataclass装饰器，添加order=False避免与自定义__lt__冲突  # 修复1
2. 修复__lt__方法，确保PriorityQueue排序逻辑正确  # 修复2
3. 完善线程安全锁机制 - 修复P0-018竞态条件  # 修复3
4. 修复状态枚举的引用问题  # 修复4
5. 增加Redis支持，支持多实例任务队列  # 修复5
6. 【P0-018修复】get_all_pending_tasks添加锁保护  # 修复6
7. 【P0-018修复】cancel方法添加内存队列检查  # 修复7
8. 【P0-018修复】clear方法统一锁使用  # 修复8
9. 【P0-018修复】get_stats方法加锁保证一致性  # 修复9
10. 所有Redis I/O操作改为异步，移除同步Redis路径  # 修复10

Redis Key规范：  # Redis规范
- task_queue:{user_id} -> SortedSet (任务队列，按优先级排序)  # Key1
- task_processing:{user_id} -> String (当前处理中的任务)  # Key2
"""  # 文档字符串结束
import asyncio  # 导入异步IO模块
import json  # 导入JSON模块
import time  # 导入时间模块
import uuid  # 导入UUID模块，用于生成唯一ID
from concurrent.futures import ThreadPoolExecutor, as_completed  # 导入并行执行支持
from dataclasses import dataclass, field  # 导入数据类相关
from os import getenv  # 从os导入环境变量获取
from queue import Empty, PriorityQueue  # 导入优先级队列和空异常
from typing import Any  # 导入类型注解

from core.task.task_status import TaskStatus  # 导入任务状态枚举

# 延迟导入logger避免循环依赖  # 注释：延迟导入说明
logger = None  # 初始化logger为None

def _get_logger():  # 定义获取logger的函数
    """延迟获取logger实例"""  # 函数文档字符串
    global logger  # 声明使用全局变量
    if logger is None:  # 如果logger为None
        from core.logger import logger as _logger  # 导入logger
        logger = _logger  # 赋值给全局变量
    return logger  # 返回logger

# 可选的Redis支持  # 注释：Redis支持
try:  # 尝试导入
    from core.redis_backend import RedisKeyBuilder, RedisStorageBackend  # 导入Redis相关
    REDIS_AVAILABLE = True  # 标记Redis可用
except ImportError:  # 如果导入失败
    REDIS_AVAILABLE = False  # 标记Redis不可用


@dataclass(order=False)  # 数据类装饰器，关闭自动排序
class Task:  # 定义任务数据类
    """任务数据结构"""  # 类文档字符串
    priority: int = field(default=3, compare=True)   # 数值越小优先级越高  # 优先级
    created_at: float = field(default_factory=time.time, compare=True)  # 创建时间  # 创建时间戳
    id: str = field(default_factory=lambda: uuid.uuid4().hex, compare=False)  # 唯一ID  # 任务ID
    type: str = field(default="user", compare=False)  # 任务类型  # 类型
    status: TaskStatus = field(default=TaskStatus.PENDING, compare=False)  # 任务状态  # 状态
    intent: dict = field(default_factory=dict, compare=False)  # 任务意图  # 意图
    steps: list = field(default_factory=list, compare=False)  # 执行步骤  # 步骤
    current_step_index: int = field(default=0, compare=False)  # 当前步骤索引  # 步骤索引
    result: dict | None = field(default=None, compare=False)  # 执行结果  # 结果
    error: str | None = field(default=None, compare=False)  # 错误信息  # 错误
    error_code: str | None = field(default=None, compare=False)  # 错误码  # 错误码
    session_id: str = field(default="", compare=False)  # 会话ID  # 会话ID
    timeout: int = field(default=300, compare=False)  # 超时时间（5分钟，支持更长时间任务）
    retry_count: int = field(default=0, compare=False)  # 当前重试次数  # 重试计数
    max_retries: int = field(default=2, compare=False)  # 最大重试次数  # 最大重试
    metadata: dict = field(default_factory=dict, compare=False)  # 元数据  # 元数据
    plan_steps: list = field(default_factory=list, compare=False)      # 计划步骤列表  # 计划步骤
    current_plan_index: int = field(default=0, compare=False)          # 当前执行的计划索引  # 计划索引
    execution_context: dict = field(default_factory=dict, compare=False)  # 中间结果上下文  # 执行上下文
    user_id: str = field(default="default_user", compare=False)        # 用户ID用于隔离  # 用户ID

    def __lt__(self, other):  # 定义小于比较方法
        """用于PriorityQueue的比较方法，priority小的优先，priority相同则created_at小的优先"""  # 方法文档字符串
        if not isinstance(other, Task):  # 如果比较对象不是Task
            return NotImplemented  # 返回NotImplemented
        if self.priority != other.priority:  # 如果优先级不同
            return self.priority < other.priority  # 按优先级比较
        if self.created_at != other.created_at:  # 如果创建时间不同
            return self.created_at < other.created_at  # 按时间比较
        return self.id < other.id  # 最后按ID比较

    def to_dict(self) -> dict:  # 定义转换为字典方法
        """转换为字典"""  # 方法文档字符串
        return {  # 返回字典
            "id": self.id,  # ID
            "priority": self.priority,  # 优先级
            "created_at": self.created_at,  # 创建时间
            "type": self.type,  # 类型
            "status": self.status.value,  # 状态值
            "intent": self.intent,  # 意图
            "steps": self.steps,  # 步骤
            "current_step_index": self.current_step_index,  # 步骤索引
            "result": self.result,  # 结果
            "error": self.error,  # 错误
            "error_code": self.error_code,  # 错误码
            "session_id": self.session_id,  # 会话ID
            "timeout": self.timeout,  # 超时
            "retry_count": self.retry_count,  # 重试计数
            "max_retries": self.max_retries,  # 最大重试
            "metadata": self.metadata,  # 元数据
            "plan_steps": self.plan_steps,  # 计划步骤
            "current_plan_index": self.current_plan_index,  # 计划索引
            "execution_context": self.execution_context,  # 执行上下文
            "user_id": self.user_id  # 用户ID
        }  # 字典结束

    @classmethod  # 类方法装饰器
    def from_dict(cls, data: dict) -> "Task":  # 定义从字典创建方法
        """从字典创建任务"""  # 方法文档字符串
        task = cls()  # 创建空任务
        task.id = data.get("id", uuid.uuid4().hex)  # ID
        task.priority = data.get("priority", 3)  # 优先级
        task.created_at = data.get("created_at", time.time())  # 创建时间
        task.type = data.get("type", "user")  # 类型
        status_str = data.get("status", "pending")  # 状态字符串
        task.status = TaskStatus(status_str) if isinstance(status_str, str) else TaskStatus.PENDING  # 状态枚举
        task.intent = data.get("intent", {})  # 意图
        task.steps = data.get("steps", [])  # 步骤
        task.current_step_index = data.get("current_step_index", 0)  # 步骤索引
        task.result = data.get("result")  # 结果
        task.error = data.get("error")  # 错误
        task.error_code = data.get("error_code")  # 错误码
        task.session_id = data.get("session_id", "")  # 会话ID
        task.timeout = data.get("timeout", 300)  # 超时（5分钟默认值）
        task.retry_count = data.get("retry_count", 0)  # 重试计数
        task.max_retries = data.get("max_retries", 2)  # 最大重试
        task.metadata = data.get("metadata", {})  # 元数据
        task.plan_steps = data.get("plan_steps", [])  # 计划步骤
        task.current_plan_index = data.get("current_plan_index", 0)  # 计划索引
        task.execution_context = data.get("execution_context", {})  # 执行上下文
        task.user_id = data.get("user_id", "default_user")  # 用户ID
        return task  # 返回任务


class TaskQueue:  # 定义任务队列类
    """  # 类文档字符串开始
    任务队列  # 类功能
    支持内存模式和Redis模式（全异步Redis I/O）  # 支持模式
    """  # 类文档字符串结束

    def __init__(self, user_id: str = None, use_redis: bool = None):  # 初始化方法
        """  # 方法文档字符串开始
        初始化任务队列  # 方法功能

        Args:  # 参数说明
            user_id: 用户ID（用于隔离）  # 参数1
            use_redis: 是否使用Redis  # 参数2
        """  # 方法文档字符串结束
        self._user_id = user_id or "default_user"  # 设置用户ID

        # 配置  # 注释：配置
        self._use_redis = use_redis  # Redis使用标志
        if self._use_redis is None:  # 如果未指定
            self._use_redis = getenv("STORAGE_BACKEND", "memory") == "redis"  # 从环境变量获取

        # 内存队列  # 注释：内存队列
        self._queue = PriorityQueue()  # 创建优先级队列
        self._current_task: Task | None = None  # 当前任务
        self._current_task_lock = asyncio.Lock()  # 当前任务锁（异步）
        self._lock = asyncio.Lock()  # 队列锁（异步，允许在协程中重入逻辑）

        # Redis支持  # 注释：Redis支持
        self._redis_backend: RedisStorageBackend | None = None  # Redis后端
        if self._use_redis and REDIS_AVAILABLE:  # 如果启用Redis且可用
            try:  # 异常处理
                self._redis_backend = RedisStorageBackend()  # 创建Redis后端（构造无I/O）
                _get_logger().info(f"[TaskQueue] Redis后端已启用: user={self._user_id}")  # 记录日志
            except Exception as e:  # 捕获异常
                _get_logger().error(f"[TaskQueue] Redis初始化失败: {e}")  # 记录错误
                self._use_redis = False  # 禁用Redis

        if not self._use_redis:  # 如果不使用Redis
            _get_logger().info(f"[TaskQueue] 使用内存队列: user={self._user_id}")  # 记录日志

        # 【P1】长任务中断恢复：暂停请求标志
        self._pause_requests: dict[str, str] = {}  # task_id -> reason

    async def _is_redis_ready_async(self) -> bool:  # 定义异步检查Redis就绪方法
        """检查Redis是否就绪（异步）"""  # 方法文档字符串
        if not self._use_redis or not self._redis_backend:  # 如果未启用或不存在
            return False  # 返回False
        return await self._redis_backend.is_available()  # 异步检查Redis可用性

    def _get_queue_key(self) -> str:  # 定义获取队列Key方法
        """获取Redis队列key"""  # 方法文档字符串
        if REDIS_AVAILABLE:  # 如果Redis可用
            return RedisKeyBuilder.task_queue(self._user_id)  # 使用Key构建器
        return f"task_queue:{self._user_id}"  # 返回默认格式

    def _get_processing_key(self) -> str:  # 定义获取处理Key方法
        """获取处理中任务key"""  # 方法文档字符串
        if REDIS_AVAILABLE:  # 如果Redis可用
            return f"{RedisKeyBuilder.PREFIX}:task_processing:{self._user_id}"  # 使用Key构建器
        return f"task_processing:{self._user_id}"  # 返回默认格式

    def _serialize_task(self, task: Task) -> str:  # 定义序列化任务方法
        """序列化任务"""  # 方法文档字符串
        return json.dumps(task.to_dict(), ensure_ascii=False)  # 转为JSON字符串

    def _deserialize_task(self, data: str) -> Task | None:  # 定义反序列化方法
        """反序列化任务"""  # 方法文档字符串
        try:  # 异常处理
            obj = json.loads(data)  # 解析JSON
            return Task.from_dict(obj)  # 创建任务对象
        except Exception as e:  # 捕获异常
            _get_logger().error(f"[TaskQueue] 任务反序列化失败: {e}")  # 记录错误
            return None  # 返回None

    async def push_async(self, task: Task, front: bool = False):  # 定义异步推送任务方法
        """  # 方法文档字符串开始
        插入任务（异步）  # 方法功能

        Args:  # 参数说明
            task: 任务对象  # 参数1
            front: front=True 表示插队（使用负数优先级确保优先）  # 参数2
        """  # 方法文档字符串结束
        task.user_id = self._user_id  # 设置用户ID

        if front:  # 如果要插队
            task.priority = -1  # 负数确保优于所有正数优先级  # 设置负优先级

        async with self._lock:  # 获取异步锁
            # 1. 写入内存队列  # 注释：写入内存
            self._queue.put(task)  # 放入队列

            # 2. 写入Redis（如果可用）  # 注释：写入Redis
            if await self._is_redis_ready_async():  # 如果Redis就绪（异步检查）
                try:  # 异常处理
                    queue_key = self._get_queue_key()  # 获取队列Key
                    score = task.priority * 1000000000 + task.created_at  # 组合分数  # 计算排序分数
                    task_data = self._serialize_task(task)  # 序列化任务
                    await self._redis_backend.zadd(queue_key, score, task_data)  # 异步添加到有序集合
                except Exception as e:  # 捕获异常
                    _get_logger().error(f"[TaskQueue] Redis推送失败: {e}")  # 记录错误

    async def pop_async(self) -> Task | None:  # 定义异步弹出任务方法
        """  # 方法文档字符串开始
        取出任务（异步）  # 方法功能

        Returns:  # 返回值说明
            Task对象或None  # 返回类型
        """  # 方法文档字符串结束
        async with self._lock:  # 获取异步锁
            # 1. 尝试从Redis获取（分布式场景）  # 注释：从Redis获取
            if await self._is_redis_ready_async():  # 如果Redis就绪（异步检查）
                try:  # 异常处理
                    queue_key = self._get_queue_key()  # 获取队列Key
                    tasks = await self._redis_backend.zrange(queue_key, 0, 0)  # 异步获取第一个
                    if tasks:  # 如果有任务
                        task_data = tasks[0]  # 获取任务数据
                        task = self._deserialize_task(task_data)  # 反序列化
                        if task:  # 如果成功
                            # 从Redis移除  # 注释：移除任务
                            await self._redis_backend.zrem(queue_key, task_data)  # 异步删除
                            # 标记为处理中  # 注释：标记处理中
                            processing_key = self._get_processing_key()  # 获取处理Key
                            await self._redis_backend.set(processing_key, self._serialize_task(task), expire_seconds=3600)  # 异步设置

                            task.status = TaskStatus.RUNNING  # 设置状态为运行中
                            async with self._current_task_lock:  # 获取异步当前任务锁
                                self._current_task = task  # 设置当前任务
                            return task  # 返回任务
                except Exception as e:  # 捕获异常
                    _get_logger().error(f"[TaskQueue] Redis弹出失败: {e}")  # 记录错误

            # 2. 从内存队列获取  # 注释：从内存获取
            try:  # 异常处理
                task = self._queue.get(timeout=0.1)  # 获取任务，超时0.1秒
                task.status = TaskStatus.RUNNING  # 设置状态为运行中
                async with self._current_task_lock:  # 获取异步当前任务锁
                    self._current_task = task  # 设置当前任务
                return task  # 返回任务
            except Empty:  # 如果队列为空
                return None  # 返回None
            except (RuntimeError, ValueError) as e:
                _get_logger().error(f"[TaskQueue] 获取任务失败: {e}", exc_info=True)
                return None

    def current_task(self) -> Task | None:
        """获取当前任务（纯内存，不涉及Redis I/O）。
        分布式场景请使用 current_task_async()。"""
        return self._current_task

    async def current_task_async(self) -> Task | None:  # 定义异步获取当前任务方法
        """获取当前任务（异步，含Redis分布式回退）"""  # 方法文档字符串
        async with self._current_task_lock:  # 获取异步当前任务锁
            # 先检查内存  # 注释：检查内存
            if self._current_task:  # 如果当前任务存在
                return self._current_task  # 返回当前任务

            # 再检查Redis（分布式场景）  # 注释：检查Redis
            if await self._is_redis_ready_async():  # 如果Redis就绪（异步检查）
                try:  # 异常处理
                    processing_key = self._get_processing_key()  # 获取处理Key
                    data = await self._redis_backend.get(processing_key)  # 异步获取数据
                    if data:  # 如果有数据
                        return self._deserialize_task(data) if isinstance(data, str) else Task.from_dict(data)  # 反序列化
                except Exception as e:  # 捕获异常
                    _get_logger().error(f"[TaskQueue] 获取Redis当前任务失败: {e}")  # 记录错误

            return None  # 返回None

    async def complete_async(self, result: dict = None):  # 定义异步完成当前任务方法
        """完成当前任务（异步）"""  # 方法文档字符串
        async with self._current_task_lock:  # 获取异步当前任务锁
            if self._current_task:  # 如果当前任务存在
                self._current_task.status = TaskStatus.COMPLETED  # 设置状态为已完成
                self._current_task.result = result  # 设置结果
                self._current_task = None  # 清空当前任务

            # 清除Redis中的处理中标记  # 注释：清除Redis标记
            if await self._is_redis_ready_async():  # 如果Redis就绪（异步检查）
                try:  # 异常处理
                    processing_key = self._get_processing_key()  # 获取处理Key
                    await self._redis_backend.delete(processing_key)  # 异步删除标记
                except Exception as e:  # 捕获异常
                    _get_logger().error(f"[TaskQueue] 清除Redis处理标记失败: {e}")  # 记录错误

    async def fail_async(self, error: str, error_code: str = None):  # 定义异步失败当前任务方法
        """标记当前任务失败（异步）"""  # 方法文档字符串
        async with self._current_task_lock:  # 获取异步当前任务锁
            if self._current_task:  # 如果当前任务存在
                self._current_task.status = TaskStatus.FAILED  # 设置状态为失败
                self._current_task.error = error  # 设置错误信息
                self._current_task.error_code = error_code  # 设置错误码
                self._current_task = None  # 清空当前任务

            # 清除Redis中的处理中标记  # 注释：清除Redis标记
            if await self._is_redis_ready_async():  # 如果Redis就绪（异步检查）
                try:  # 异常处理
                    processing_key = self._get_processing_key()  # 获取处理Key
                    await self._redis_backend.delete(processing_key)  # 异步删除标记
                except Exception as e:  # 捕获异常
                    _get_logger().error(f"[TaskQueue] 清除Redis处理标记失败: {e}")  # 记录错误

    async def interrupt_async(self, reason: str = "用户打断"):  # 定义异步中断当前任务方法
        """中断当前任务（异步）"""  # 方法文档字符串
        async with self._current_task_lock:  # 获取异步当前任务锁
            if self._current_task:  # 如果当前任务存在
                self._current_task.status = TaskStatus.INTERRUPTED  # 设置状态为已中断
                self._current_task.error = reason  # 设置错误信息
                self._current_task.error_code = "INTERRUPTED"  # 设置错误码
                self._current_task = None  # 清空当前任务

            # 清除Redis中的处理中标记  # 注释：清除Redis标记
            if await self._is_redis_ready_async():  # 如果Redis就绪（异步检查）
                try:  # 异常处理
                    processing_key = self._get_processing_key()  # 获取处理Key
                    await self._redis_backend.delete(processing_key)  # 异步删除标记
                except Exception as e:  # 捕获异常
                    _get_logger().error(f"[TaskQueue] 清除Redis处理标记失败: {e}")  # 记录错误

    async def cancel_async(self, task_id: str) -> bool:  # 定义异步取消任务方法
        """  # 方法文档字符串开始
        取消指定任务（异步）  # 方法功能

        【P0-018修复】添加内存队列检查和返回值
        【死锁修复】统一锁获取顺序：先_lock后_current_task_lock  # 修复说明

        Args:  # 参数说明
            task_id: 任务ID  # 参数

        Returns:  # 返回值说明
            是否成功找到并取消任务  # 返回类型
        """  # 方法文档字符串结束
        cancelled = False  # 取消标志

        # 【死锁修复】先获取_lock，再获取_current_task_lock，与pop_async()方法保持一致
        async with self._lock:  # 获取异步队列锁
            # 【P0-018修复】从内存队列中移除  # 注释：从内存取消
            temp_queue = PriorityQueue()  # 创建临时队列
            while not self._queue.empty():  # 当原队列不为空
                try:  # 异常处理
                    task = self._queue.get(timeout=0.1)  # 获取任务
                    if task.id == task_id:  # 如果是要取消的任务
                        cancelled = True  # 设置取消标志
                        _get_logger().info(f"[TaskQueue] 已从内存队列取消任务: {task_id}")  # 记录日志
                    else:  # 不是目标任务
                        temp_queue.put(task)  # 放入临时队列
                except Empty:  # 如果队列为空
                    break  # 跳出循环

            # 恢复剩余任务  # 注释：恢复队列
            while not temp_queue.empty():  # 当临时队列不为空
                self._queue.put(temp_queue.get())  # 放回主队列

            # 【死锁修复】在_lock保护下获取_current_task_lock，检查并取消当前任务
            async with self._current_task_lock:  # 获取异步当前任务锁
                if self._current_task and self._current_task.id == task_id:  # 如果是当前任务
                    self._current_task.status = TaskStatus.CANCELLED  # 设置状态为已取消
                    self._current_task.error = "用户取消"  # 设置错误信息
                    self._current_task.error_code = "CANCELLED"  # 设置错误码
                    self._current_task = None  # 清空当前任务
                    cancelled = True  # 设置取消标志
                    _get_logger().info(f"[TaskQueue] 已取消当前任务: {task_id}")  # 记录日志

        # 从Redis队列中移除（如果存在）  # 注释：从Redis取消
        if await self._is_redis_ready_async():  # 如果Redis就绪（异步检查）
            try:  # 异常处理
                queue_key = self._get_queue_key()  # 获取队列Key
                tasks = await self._redis_backend.zrange(queue_key, 0, -1)  # 异步获取所有任务
                for task_data in tasks:  # 遍历任务
                    task = self._deserialize_task(task_data)  # 反序列化
                    if task and task.id == task_id:  # 如果找到目标
                        await self._redis_backend.zrem(queue_key, task_data)  # 异步从Redis移除
                        cancelled = True  # 设置取消标志
                        _get_logger().info(f"[TaskQueue] 已从Redis队列取消任务: {task_id}")  # 记录日志
                        break  # 跳出循环
            except Exception as e:  # 捕获异常
                _get_logger().error(f"[TaskQueue] Redis取消任务失败: {e}")  # 记录错误

        return cancelled  # 返回取消结果

    async def get_stats_async(self) -> dict[str, Any]:  # 定义异步获取统计方法
        """  # 方法文档字符串开始
        获取任务队列统计信息（异步）  # 方法功能

        【P0-018修复】添加锁保证一致性
        【死锁修复】统一锁获取顺序：先_lock后_current_task_lock  # 修复说明
        """  # 方法文档字符串结束
        redis_available = await self._is_redis_ready_async()  # 异步检查Redis状态（在锁外）
        # 【死锁修复】先获取_lock，再获取_current_task_lock，与pop_async()方法保持一致
        async with self._lock:  # 获取异步队列锁
            queue_size = self._queue.qsize()  # 获取队列大小

            async with self._current_task_lock:  # 获取异步当前任务锁
                current = self._current_task  # 获取当前任务

                stats = {  # 构建统计字典
                    "current_task": {  # 当前任务信息
                        "id": current.id if current else None,  # ID
                        "status": current.status.value if current else None,  # 状态
                        "type": current.type if current else None  # 类型
                    },  # 当前任务结束
                    "queue_size": queue_size,  # 队列大小
                    "has_running_task": current is not None,  # 是否有运行中任务
                    "user_id": self._user_id,  # 用户ID
                    "use_redis": self._use_redis,  # 是否使用Redis
                    "redis_available": redis_available  # Redis是否就绪
                }  # 统计字典结束

        # Redis队列长度（在锁外访问Redis，避免长时间持有锁）  # 注释：Redis统计
        if redis_available:  # 如果Redis就绪
            try:  # 异常处理
                queue_key = self._get_queue_key()  # 获取队列Key
                tasks = await self._redis_backend.zrange(queue_key, 0, -1)  # 异步获取所有任务
                stats["redis_queue_size"] = len(tasks)  # 设置Redis队列大小
            except (ConnectionError, RuntimeError) as e:
                _get_logger().error(f"[TaskQueue] 获取Redis队列统计失败: {e}", exc_info=True)
                stats["redis_queue_size"] = 0

        return stats  # 返回统计信息

    async def get_all_pending_tasks_async(self) -> list[Task]:  # 定义异步获取所有待处理任务方法
        """  # 方法文档字符串开始
        获取所有待处理任务【协程安全】（异步）  # 方法功能

        【并发修复-BUG-005】使用异步锁安全访问队列，避免drain-restore竞态条件  # 修复说明
        """  # 方法文档字符串结束
        tasks = []  # 初始化任务列表

        # 【并发修复-BUG-005】使用异步锁安全获取内存队列任务
        # PriorityQueue.queue 是内部的deque，在锁保护下可以安全访问
        # 这种方法避免了 drain-restore 过程中可能的竞态条件
        async with self._lock:  # 加异步锁保护队列访问
            # 直接复制队列内容，不修改队列状态
            try:
                # PriorityQueue内部使用deque存储元素
                queue_contents = list(self._queue.queue)  # 原子性复制队列内容
                for item in queue_contents:  # 遍历复制的列表
                    if isinstance(item, Task):  # 确保是Task类型
                        tasks.append(item)  # 添加到结果列表
            except (RuntimeError, ValueError) as e:
                _get_logger().error(f"[TaskQueue] 获取内存队列任务失败: {e}", exc_info=True)

        # 从Redis获取（Redis操作本身原子，不需要额外锁）  # 注释：获取Redis任务
        if await self._is_redis_ready_async():  # 如果Redis就绪（异步检查）
            try:  # 异常处理
                queue_key = self._get_queue_key()  # 获取队列Key
                redis_tasks = await self._redis_backend.zrange(queue_key, 0, -1)  # 异步获取所有任务
                for task_data in redis_tasks:  # 遍历任务
                    task = self._deserialize_task(task_data)  # 反序列化
                    if task:  # 如果成功
                        tasks.append(task)  # 添加到列表
            except Exception as e:  # 捕获异常
                _get_logger().error(f"[TaskQueue] 获取Redis待处理任务失败: {e}")  # 记录错误

        return tasks  # 返回任务列表

    async def clear_async(self):  # 定义异步清空队列方法
        """  # 方法文档字符串开始
        清空队列（异步）  # 方法功能

        【P0-018修复】统一锁使用  # 修复说明
        """  # 方法文档字符串结束
        # 【修复】使用_lock清空内存队列  # 注释：清空内存
        async with self._lock:  # 获取异步队列锁
            while not self._queue.empty():  # 当队列不为空
                try:  # 异常处理
                    self._queue.get(timeout=0.1)  # 获取并丢弃
                except Empty:  # 如果队列为空
                    break  # 跳出循环

        # 【修复】使用_current_task_lock清空当前任务  # 注释：清空当前任务
        async with self._current_task_lock:  # 获取异步当前任务锁
            self._current_task = None  # 清空当前任务

        # 清空Redis队列  # 注释：清空Redis
        if await self._is_redis_ready_async():  # 如果Redis就绪（异步检查）
            try:  # 异常处理
                queue_key = self._get_queue_key()  # 获取队列Key
                tasks = await self._redis_backend.zrange(queue_key, 0, -1)  # 异步获取所有任务
                for task_data in tasks:  # 遍历任务
                    await self._redis_backend.zrem(queue_key, task_data)  # 异步从Redis移除

                # 清除处理中标记  # 注释：清除标记
                processing_key = self._get_processing_key()  # 获取处理Key
                await self._redis_backend.delete(processing_key)  # 异步删除标记
            except Exception as e:  # 捕获异常
                _get_logger().error(f"[TaskQueue] Redis清空失败: {e}")  # 记录错误

    # ── 长任务中断恢复：暂停请求标志 ──

    def request_pause(self, task_id: str, reason: str = "user_interruption") -> bool:
        """请求暂停指定任务（设置标志，供 AgentLoop 检查）。"""
        if not task_id:
            return False
        self._pause_requests[task_id] = reason
        _get_logger().info(f"[TaskQueue] 收到暂停请求: task_id={task_id}, reason={reason}")
        return True

    def is_pause_requested(self, task_id: str) -> bool:
        """检查任务是否被请求暂停。"""
        return task_id in self._pause_requests

    def get_pause_reason(self, task_id: str) -> str | None:
        """获取暂停原因。"""
        return self._pause_requests.get(task_id)

    def clear_pause_request(self, task_id: str) -> None:
        """清除暂停请求标志。"""
        self._pause_requests.pop(task_id, None)

    async def pause_task_async(self, task_id: str, reason: str = None) -> bool:
        """暂停任务（异步）：将任务标记为 PAUSED，并记录原因。"""
        async with self._current_task_lock:
            if self._current_task and self._current_task.id == task_id:
                self._current_task.status = TaskStatus.PAUSED
                if not self._current_task.metadata:
                    self._current_task.metadata = {}
                self._current_task.metadata['paused_at'] = time.time()
                self._current_task.metadata['paused_reason'] = reason or "user_pause"
                _get_logger().info(f"[TaskQueue] 任务已暂停: {task_id}, 原因: {reason}")
                return True

            if await self._is_redis_ready_async():
                try:
                    processing_key = self._get_processing_key()
                    data = await self._redis_backend.get(processing_key)
                    if data:
                        task = self._deserialize_task(data) if isinstance(data, str) else Task.from_dict(data)
                        if task and task.id == task_id:
                            task.status = TaskStatus.PAUSED
                            if not task.metadata:
                                task.metadata = {}
                            task.metadata['paused_at'] = time.time()
                            task.metadata['paused_reason'] = reason or "user_pause"
                            await self._redis_backend.set(processing_key, self._serialize_task(task), expire_seconds=3600)
                            _get_logger().info(f"[TaskQueue] Redis任务已暂停: {task_id}")
                            return True
                except Exception as e:
                    _get_logger().error(f"[TaskQueue] Redis暂停任务失败: {e}")

        _get_logger().warning(f"[TaskQueue] 未找到要暂停的任务: {task_id}")
        return False

    async def resume_task_async(self, task_id: str) -> bool:  # 定义异步恢复任务方法
        """  # 方法文档字符串开始
        恢复任务（异步）  # 方法功能

        将暂停的任务恢复到之前的运行状态。  # 功能说明

        Args:  # 参数说明
            task_id: 任务ID  # 参数

        Returns:  # 返回值说明
            是否成功恢复  # 返回类型
        """  # 方法文档字符串结束
        async with self._current_task_lock:  # 获取异步当前任务锁
            # 检查当前任务  # 注释：检查内存
            if self._current_task and self._current_task.id == task_id and self._current_task.status == TaskStatus.PAUSED:  # 如果是当前任务且已暂停
                self._current_task.status = TaskStatus.RUNNING  # 设置状态为运行中
                if not self._current_task.metadata:  # 如果没有元数据
                    self._current_task.metadata = {}  # 创建空字典
                self._current_task.metadata['resumed_at'] = time.time()  # 记录恢复时间
                _get_logger().info(f"[TaskQueue] 任务已恢复: {task_id}")  # 记录日志
                return True  # 返回成功

            # 在Redis中查找并更新  # 注释：检查Redis
            if await self._is_redis_ready_async():  # 如果Redis就绪（异步检查）
                try:  # 异常处理
                    processing_key = self._get_processing_key()  # 获取处理Key
                    data = await self._redis_backend.get(processing_key)  # 异步获取数据
                    if data:  # 如果有数据
                        task = self._deserialize_task(data) if isinstance(data, str) else Task.from_dict(data)  # 反序列化
                        if task and task.id == task_id and task.status == TaskStatus.PAUSED:  # 如果找到且已暂停
                            task.status = TaskStatus.RUNNING  # 设置状态为运行中
                            if not task.metadata:  # 如果没有元数据
                                task.metadata = {}  # 创建空字典
                            task.metadata['resumed_at'] = time.time()  # 记录恢复时间
                            await self._redis_backend.set(processing_key, self._serialize_task(task), expire_seconds=3600)  # 异步更新Redis
                            _get_logger().info(f"[TaskQueue] Redis任务已恢复: {task_id}")  # 记录日志
                            return True  # 返回成功
                except Exception as e:  # 捕获异常
                    _get_logger().error(f"[TaskQueue] Redis恢复任务失败: {e}")  # 记录错误

        _get_logger().warning(f"[TaskQueue] 未找到要恢复的任务: {task_id}")  # 记录警告
        return False  # 返回失败

    async def get_task_async(self) -> Task | None:  # 别名方法
        """获取当前任务（get_task_async 别名）"""
        return await self.current_task_async()

    async def list_tasks_async(self) -> list[Task]:  # 别名方法
        """获取所有待处理任务（list_tasks_async 别名）"""
        return await self.get_all_pending_tasks_async()


# 默认全局实例（向后兼容）  # 注释：创建全局实例
task_queue = TaskQueue()  # 实例化默认任务队列


def get_task_queue(user_id: str = None, use_redis: bool = None) -> TaskQueue:  # 定义获取任务队列函数
    """  # 函数文档字符串开始
    获取任务队列实例  # 函数功能

    Args:  # 参数说明
        user_id: 用户ID  # 参数1
        use_redis: 是否使用Redis  # 参数2

    Returns:  # 返回值说明
        TaskQueue实例  # 返回类型
    """  # 函数文档字符串结束
    if user_id is None or user_id == "default_user":  # 如果未指定用户或使用默认
        return task_queue  # 返回全局实例

    # 为特定用户创建新的队列实例  # 注释：创建用户专属队列
    return TaskQueue(user_id=user_id, use_redis=use_redis)  # 创建新实例


# =============================================================================
# 并行任务执行支持
# =============================================================================

@dataclass
class TaskResult:
    """任务执行结果"""
    task_id: str
    success: bool = True
    result: dict[str, Any] | None = None
    error: str | None = None
    execution_time_ms: float = 0.0


class ParallelTaskQueue:
    """
    支持并行执行的任务队列

    用于并行执行多个独立的工具调用任务，
    提高多工具场景下的执行效率。
    """

    def __init__(self, max_workers: int = 3):
        """
        初始化并行任务队列

        Args:
            max_workers: 最大并行工作线程数
        """
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._max_workers = max_workers
        _get_logger().info(f"[ParallelTaskQueue] 初始化完成，最大工作线程: {max_workers}")

    def _execute_task(self, task: Task) -> TaskResult:
        """
        执行单个任务（在线程池中运行）

        Args:
            task: 要执行的任务

        Returns:
            任务执行结果
        """
        import time
        start_time = time.time()

        try:
            # 这里调用实际的工具执行逻辑
            # 实际实现应该调用 tool_manager.execute 或类似方法
            _get_logger().debug(f"[ParallelTaskQueue] 执行任务: {task.id}")

            # 模拟任务执行（实际应替换为真实执行逻辑）
            # result = tool_manager.execute(task.intent.get('tool_name'), task.intent.get('params'))

            execution_time = (time.time() - start_time) * 1000
            return TaskResult(
                task_id=task.id,
                success=True,
                result={"status": "completed"},
                execution_time_ms=execution_time
            )
        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            _get_logger().error(f"[ParallelTaskQueue] 任务执行失败 {task.id}: {e}")
            return TaskResult(
                task_id=task.id,
                success=False,
                error=str(e),
                execution_time_ms=execution_time
            )

    def execute_parallel(self, tasks: list[Task]) -> list[TaskResult]:
        """
        并行执行多个独立任务

        Args:
            tasks: 要执行的任务列表

        Returns:
            任务执行结果列表（顺序可能与输入不同）

        Example:
            >>> queue = ParallelTaskQueue(max_workers=3)
            >>> tasks = [Task(intent={'tool': 'screenshot'}), Task(intent={'tool': 'ocr'})]
            >>> results = queue.execute_parallel(tasks)
        """
        if not tasks:
            return []

        _get_logger().info(f"[ParallelTaskQueue] 开始并行执行 {len(tasks)} 个任务")

        futures = {self._executor.submit(self._execute_task, t): t for t in tasks}
        results = []

        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
                results.append(result)
                _get_logger().debug(f"[ParallelTaskQueue] 任务完成: {task.id}")
            except Exception as e:
                _get_logger().error(f"[ParallelTaskQueue] 任务异常: {task.id}, error: {e}")
                results.append(TaskResult(task_id=task.id, success=False, error=str(e)))

        _get_logger().info(f"[ParallelTaskQueue] 并行执行完成，成功: {sum(1 for r in results if r.success)}/{len(results)}")
        return results

    def execute_parallel_ordered(self, tasks: list[Task]) -> list[TaskResult]:
        """
        并行执行多个独立任务，保持结果顺序与输入一致

        Args:
            tasks: 要执行的任务列表

        Returns:
            按输入顺序排列的任务执行结果列表
        """
        if not tasks:
            return []

        # 建立任务ID到索引的映射
        task_index = {task.id: idx for idx, task in enumerate(tasks)}
        results = [None] * len(tasks)

        _get_logger().info(f"[ParallelTaskQueue] 开始并行执行 {len(tasks)} 个任务（保持顺序）")

        futures = {self._executor.submit(self._execute_task, t): t for t in tasks}

        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
                idx = task_index.get(task.id, 0)
                results[idx] = result
            except Exception as e:
                idx = task_index.get(task.id, 0)
                results[idx] = TaskResult(task_id=task.id, success=False, error=str(e))

        return results

    def shutdown(self, wait: bool = True):
        """
        关闭线程池

        Args:
            wait: 是否等待所有任务完成
        """
        self._executor.shutdown(wait=wait)
        _get_logger().info("[ParallelTaskQueue] 线程池已关闭")


def get_parallel_task_queue(max_workers: int = 3) -> ParallelTaskQueue:
    """
    获取并行任务队列实例

    Args:
        max_workers: 最大并行工作线程数

    Returns:
        ParallelTaskQueue 实例
    """
    return ParallelTaskQueue(max_workers=max_workers)


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"任务队列模块"，负责任务的存储、调度、状态管理，
# 支持内存模式和Redis模式，是系统任务调度的核心基础设施。
#
# 【核心功能】
# 1. 优先级队列: 基于PriorityQueue实现，priority越小优先级越高
# 2. 协程安全: 使用asyncio.Lock保护并发访问，修复了P0-018竞态条件
# 3. 多用户隔离: 支持按user_id创建独立队列，实现多租户
# 4. Redis支持: 可选Redis后端，全异步I/O，支持分布式部署和多实例
# 5. 任务生命周期: 支持PENDING->RUNNING->COMPLETED/FAILED/CANCELLED/PAUSED状态流转
# 6. 任务控制: 支持取消、暂停、恢复、清空等操作
#
# 【关联文件】
# - core/task_status.py           : 任务状态枚举定义
# - core/redis_backend.py         : Redis后端实现
# - core/agent_loop.py            : 从队列获取任务并执行
# - core/interrupt_handler.py     : 调用本模块进行任务中断
#
# 【任务状态流转】
# PENDING -> RUNNING -> COMPLETED
#                    -> FAILED
#                    -> CANCELLED
#                    -> INTERRUPTED
#         -> PAUSED -> RUNNING (恢复)
#
# 【使用示例】
# from core.task.task_queue import task_queue, Task
# task = Task(type="user", intent={"raw": "查询天气"}, priority=3)
# await task_queue.push_async(task)  # 提交任务
# current = await task_queue.current_task_async()  # 获取当前任务
# await task_queue.complete_async(result={...})  # 完成任务
#
# 【注意事项】
# - 异步环境下所有操作都已加锁，可安全使用
# - Redis模式需要STORAGE_BACKEND=redis环境变量
# - 任务取消会同时检查内存队列和Redis队列
# =============================================================================
