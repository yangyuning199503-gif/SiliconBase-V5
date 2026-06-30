#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
会话持久化管理器 - 支持24小时持续执行 V5.2  # 模块功能概述
- JSONL格式持久化（类似OpenClaw）  # 特性1
- Checkpoint机制（定期保存状态）  # 特性2
- Memory Flush（关键信息保存到长期记忆）  # 特性3
- Redis支持（云端多实例共享）  # 特性4

Redis Key规范：  # Redis规范
- session_data:{user_id}:{session_id} -> Hash (会话完整数据)  # Key格式1
- session_checkpoint:{user_id}:{session_id} -> String (检查点JSON)  # Key格式2
"""  # 文档字符串结束
import contextlib
import json  # 导入JSON模块
import os  # 导入操作系统模块
import time  # 导入时间模块
from dataclasses import asdict, dataclass  # 导入数据类装饰器和工具
from datetime import datetime  # 导入日期时间类
from pathlib import Path  # 导入路径类
from typing import Any  # 导入类型注解

from core.exceptions import CheckpointError  # 从统一异常模块导入
from core.logger import logger  # 导入日志记录器

# 使用依赖管理工具处理可选依赖  # 依赖管理
from ..utils.dependency_utils import redis_dep  # 导入Redis依赖

# Redis支持  # Redis支持
if redis_dep.available:  # 如果Redis依赖可用
    try:  # 异常处理
        from core.redis_backend import RedisKeyBuilder, RedisStorageBackend, is_redis_available  # 导入Redis后端
        REDIS_AVAILABLE = True  # 标记Redis可用
    except ImportError:  # 导入失败
        REDIS_AVAILABLE = False  # 标记Redis不可用
else:  # 依赖不可用
    REDIS_AVAILABLE = False  # 标记Redis不可用

# 避免循环导入  # 循环导入处理
try:  # 异常处理
    from core.memory.memory_service import get_memory_service  # 【P1-迁移】使用新 MemoryService
    from core.memory.memory_source import MemorySource  # Agent-4: 导入MemorySource枚举
    MEMORY_AVAILABLE = True  # 标记记忆可用
except ImportError:  # 导入失败
    MEMORY_AVAILABLE = False  # 标记记忆不可用
    MemorySource = None  # 置空


@dataclass  # 数据类装饰器
class SessionCheckpoint:  # 定义会话检查点数据类
    """检查点 - 保存某一时刻的完整状态"""  # 类文档字符串
    timestamp: float  # 时间戳字段
    task_id: str  # 任务ID字段
    session_id: str  # 会话ID字段
    messages: list[dict]  # 当前消息列表字段
    working_memory: dict  # 工作记忆状态字段
    execution_history: list[dict]  # 执行历史字段
    summary: str  # 自动生成的摘要字段

    def to_dict(self) -> dict:  # 转换为字典方法
        """转换为字典"""  # 方法文档字符串
        return asdict(self)  # 使用asdict转换

    @classmethod  # 类方法装饰器
    def from_dict(cls, data: dict):  # 从字典创建方法
        """从字典创建"""  # 方法文档字符串
        return cls(**data)  # 解包创建实例


class SessionPersistence:  # 定义会话持久化管理器类
    """
    会话持久化管理器  # 类文档字符串
    使用JSONL格式，每行一条消息，追加写入  # 存储格式
    支持Redis后端用于云端多实例部署  # 后端支持
    """

    # 状态数据必填字段
    REQUIRED_CHECKPOINT_FIELDS = ['timestamp', 'task_id', 'session_id', 'messages', 'working_memory', 'execution_history', 'summary']

    def __init__(self, base_dir: Path = None, use_redis: bool = None):  # 初始化方法
        """
        初始化会话持久化管理器  # 方法文档字符串

        Args:  # 参数说明
            base_dir: 本地存储目录  # 参数1
            use_redis: 是否使用Redis，None则自动检测  # 参数2
        """
        if base_dir is None:  # 如果未指定目录
            base_dir = Path(__file__).parent.parent / "data" / "sessions"  # 使用默认目录
        self.base_dir = base_dir  # 保存基础目录
        self.base_dir.mkdir(parents=True, exist_ok=True)  # 确保目录存在

        # 内存缓存  # 缓存机制
        self._session_cache: dict[str, list[dict]] = {}  # 会话缓存字典
        self._checkpoint_cache: dict[str, list[SessionCheckpoint]] = {}  # 检查点缓存字典

        # Redis配置  # Redis配置
        self._use_redis = use_redis  # 保存Redis配置
        if self._use_redis is None:  # 如果未指定
            # 优先从配置文件读取，其次环境变量
            try:
                from core.config import config
                redis_backend = config.get("services.redis.backend", "redis")
                self._use_redis = redis_backend == "redis"
                logger.info(f"[SessionPersistence] 从配置读取存储后端: {redis_backend}")
            except Exception:
                # 回退到环境变量（向后兼容）
                self._use_redis = os.getenv("STORAGE_BACKEND", "redis") == "redis"

        self._redis_backend: RedisStorageBackend | None = None  # Redis后端引用
        if self._use_redis and REDIS_AVAILABLE:  # 如果启用且可用
            try:  # 异常处理
                self._redis_backend = RedisStorageBackend()  # 创建Redis后端
                logger.info("[SessionPersistence] Redis后端已启用")  # 记录日志
            except Exception as e:  # 捕获异常
                logger.error(f"[SessionPersistence] Redis初始化失败: {e}")  # 记录错误
                self._use_redis = False  # 禁用Redis

        if not self._use_redis:  # 如果不使用Redis
            logger.info("[SessionPersistence] 使用本地文件存储")  # 记录信息

    async def _is_redis_ready_async(self) -> bool:  # 检查Redis就绪方法
        """检查Redis是否就绪"""  # 方法文档字符串
        if not self._use_redis or not self._redis_backend:  # 如果未启用或未初始化
            return False  # 返回未就绪
        return await is_redis_available()  # 返回Redis可用性

    def _get_session_key(self, user_id: str, session_id: str) -> str:  # 获取会话Key方法
        """生成Redis会话数据key"""  # 方法文档字符串
        if REDIS_AVAILABLE:  # 如果Redis可用
            return f"{RedisKeyBuilder.PREFIX}:session_data:{user_id}:{session_id}"  # 使用前缀
        return f"session_data:{user_id}:{session_id}"  # 不使用前缀

    def _get_checkpoint_key(self, user_id: str, session_id: str) -> str:  # 获取检查点Key方法
        """生成Redis检查点key"""  # 方法文档字符串
        if REDIS_AVAILABLE:  # 如果Redis可用
            return f"{RedisKeyBuilder.PREFIX}:session_checkpoint:{user_id}:{session_id}"  # 使用前缀
        return f"session_checkpoint:{user_id}:{session_id}"  # 不使用前缀

    def _get_session_path(self, session_id: str) -> Path:  # 获取会话文件路径方法
        """获取会话文件路径"""  # 方法文档字符串
        session_dir = self.base_dir / session_id[:2]  # 按前2字符分目录
        session_dir.mkdir(exist_ok=True)  # 确保目录存在
        return session_dir / f"{session_id}.jsonl"  # 返回文件路径

    def _get_checkpoint_path(self, session_id: str) -> Path:  # 获取检查点路径方法
        """获取检查点文件路径"""  # 方法文档字符串
        return self.base_dir / f"{session_id}_checkpoints.json"  # 返回路径

    def _get_user_session_path(self, user_id: str, session_id: str) -> Path:  # 获取用户会话路径方法
        """获取用户隔离的会话文件路径"""  # 方法文档字符串
        user_dir = self.base_dir / user_id  # 构建用户目录
        user_dir.mkdir(exist_ok=True)  # 确保目录存在
        return user_dir / f"{session_id}.jsonl"  # 返回文件路径

    async def append_message(self, session_id: str, message: dict, user_id: str = None):  # 追加消息方法
        """
        追加消息到会话（核心方法）  # 方法文档字符串
        使用JSONL格式，追加写入，损坏行不影响其他数据  # 格式说明

        Args:  # 参数说明
            session_id: 会话ID  # 参数1
            message: 消息字典  # 参数2
            user_id: 用户ID（可选，用于用户隔离）  # 参数3
        """
        user_id = user_id or "default_user"  # 默认用户

        # 1. 内存缓存立即更新  # 内存更新
        cache_key = f"{user_id}:{session_id}"  # 构建缓存Key
        if cache_key not in self._session_cache:  # 如果不存在
            self._session_cache[cache_key] = []  # 创建列表
        self._session_cache[cache_key].append(message)  # 追加消息

        # 2. 写入Redis（如果可用）  # Redis写入
        if await self._is_redis_ready_async():  # 如果Redis就绪
            try:  # 异常处理
                redis_key = self._get_session_key(user_id, session_id)  # 获取Redis Key
                line = json.dumps(message, ensure_ascii=False)  # JSON序列化
                await self._redis_backend.lpush(redis_key, line, max_len=1000)  # 写入Redis列表
            except Exception as e:  # 捕获异常
                logger.error(f"[SessionPersistence] Redis写入失败: {e}")  # 记录错误

        # 3. 追加写入磁盘（O(1)操作）  # 磁盘写入
        file_path = self._get_user_session_path(user_id, session_id)  # 获取文件路径
        try:  # 异常处理
            line = json.dumps(message, ensure_ascii=False)  # JSON序列化
            import asyncio
            def _append_session():
                with open(file_path, "a", encoding="utf-8") as f:  # 追加模式打开
                    f.write(line + "\n")  # 写入并换行
            await asyncio.to_thread(_append_session)
        except Exception as e:  # 捕获异常
            logger.error(f"[SessionPersistence] 会话持久化失败: {e}")  # 记录错误

    async def load_session(self, session_id: str, user_id: str = None) -> list[dict]:  # 加载会话方法
        """
        加载完整会话历史  # 方法文档字符串
        损坏的行会被跳过  # 容错说明

        Args:  # 参数说明
            session_id: 会话ID  # 参数1
            user_id: 用户ID（可选）  # 参数2

        Returns:  # 返回值说明
            消息列表  # 返回类型
        """
        user_id = user_id or "default_user"  # 默认用户
        cache_key = f"{user_id}:{session_id}"  # 构建缓存Key

        # 1. 优先从内存缓存读取  # 内存优先
        if cache_key in self._session_cache:  # 如果缓存存在
            return self._session_cache[cache_key].copy()  # 返回副本

        # 2. 尝试从Redis读取  # Redis读取
        if await self._is_redis_ready_async():  # 如果Redis就绪
            try:  # 异常处理
                redis_key = self._get_session_key(user_id, session_id)  # 获取Redis Key
                lines = await self._redis_backend.lrange(redis_key, 0, -1)  # 获取所有行
                if lines:  # 如果有数据
                    messages = []  # 消息列表
                    for line in reversed(lines):  # Redis LPUSH导致顺序反转，需倒序
                        try:  # 异常处理
                            msg = json.loads(line)  # JSON解析
                            messages.insert(0, msg)  # 插入头部恢复顺序
                        except json.JSONDecodeError:  # JSON解析错误
                            continue  # 跳过损坏行
                    if messages:  # 如果有消息
                        self._session_cache[cache_key] = messages  # 更新缓存
                        return messages.copy()  # 返回副本
            except Exception as e:  # 捕获异常
                logger.error(f"[SessionPersistence] Redis读取失败: {e}")  # 记录错误

        # 3. 从磁盘加载  # 磁盘加载
        file_path = self._get_user_session_path(user_id, session_id)  # 获取文件路径
        messages = []  # 消息列表

        if file_path.exists():  # 如果文件存在
            import asyncio
            def _load_session_file():
                _messages = []
                with open(file_path, encoding="utf-8") as f:  # 读取模式打开
                    for line_num, line in enumerate(f, 1):  # 遍历行
                        line = line.strip()  # 去除空白
                        if not line:  # 如果是空行
                            continue  # 跳过
                        try:  # 异常处理
                            msg = json.loads(line)  # JSON解析
                            _messages.append(msg)  # 添加消息
                        except json.JSONDecodeError:  # JSON解析错误
                            logger.warning(f"[SessionPersistence] 会话文件损坏行 {line_num}，已跳过")  # 记录警告
                return _messages
            messages = await asyncio.to_thread(_load_session_file)

        self._session_cache[cache_key] = messages  # 更新缓存
        return messages.copy()  # 返回副本

    async def create_checkpoint(self,  # 创建检查点方法
                         session_id: str,  # 会话ID参数
                         task_id: str,  # 任务ID参数
                         messages: list[dict],  # 消息列表参数
                         working_memory: dict,  # 工作记忆参数
                         execution_history: list[dict],  # 执行历史参数
                         user_id: str = None) -> SessionCheckpoint:  # 用户ID参数和返回类型
        """
        创建检查点  # 方法文档字符串
        用于长任务的中断恢复  # 用途说明

        Args:  # 参数说明
            session_id: 会话ID  # 参数1
            task_id: 任务ID  # 参数2
            messages: 当前消息列表  # 参数3
            working_memory: 工作记忆状态  # 参数4
            execution_history: 执行历史  # 参数5
            user_id: 用户ID（可选）  # 参数6

        Returns:  # 返回值说明
            SessionCheckpoint对象  # 返回类型

        Raises:
            CheckpointError: 检查点保存失败
        """
        user_id = user_id or "default_user"  # 默认用户

        # 生成摘要  # 摘要生成
        summary = self._generate_summary(messages, execution_history)  # 调用生成方法

        checkpoint = SessionCheckpoint(  # 创建检查点
            timestamp=time.time(),  # 当前时间戳
            task_id=task_id,  # 任务ID
            session_id=session_id,  # 会话ID
            messages=messages[-20:] if len(messages) > 20 else messages.copy(),  # 保留最近20条
            working_memory=working_memory.copy(),  # 复制工作记忆
            execution_history=execution_history[-10:] if len(execution_history) > 10 else execution_history.copy(),  # 保留最近10条
            summary=summary  # 摘要
        )

        # 保存到缓存  # 缓存保存
        cache_key = f"{user_id}:{session_id}"  # 构建缓存Key
        if cache_key not in self._checkpoint_cache:  # 如果不存在
            self._checkpoint_cache[cache_key] = []  # 创建列表
        self._checkpoint_cache[cache_key].append(checkpoint)  # 追加检查点

        # 只保留最近10个检查点  # 限制数量
        if len(self._checkpoint_cache[cache_key]) > 10:  # 如果超过10个
            self._checkpoint_cache[cache_key].pop(0)  # 移除最早的

        # 持久化到Redis（如果可用）- 失败不抛异常，降级到本地存储
        if await self._is_redis_ready_async():  # 如果Redis就绪
            try:
                await self._save_checkpoint_to_redis_async(user_id, session_id, checkpoint)  # 保存到Redis
            except CheckpointError:
                logger.warning("[SessionPersistence] Redis保存失败，将使用本地存储")

        # 持久化到磁盘 - 必须成功
        await self._save_checkpoints(user_id, session_id)  # 保存检查点

        logger.info(f"[SessionPersistence] 创建检查点: session={session_id}, task={task_id}")  # 记录日志

        return checkpoint  # 返回检查点

    async def _save_checkpoint_to_redis_async(self, user_id: str, session_id: str, checkpoint: SessionCheckpoint):  # 保存到Redis方法
        """
        保存检查点到Redis

        Raises:
            CheckpointError: Redis保存失败
        """
        if not await self._is_redis_ready_async():  # 如果Redis未就绪
            return  # 直接返回

        try:  # 异常处理
            redis_key = self._get_checkpoint_key(user_id, session_id)  # 获取Redis Key
            # 获取现有检查点列表  # 获取现有
            existing = await self._redis_backend.get(redis_key)  # 从Redis获取
            checkpoints = []  # 检查点列表
            if existing:  # 如果有数据
                with contextlib.suppress(Exception):  # 异常处理
                    checkpoints = json.loads(existing)  # JSON解析

            checkpoints.append(checkpoint.to_dict())  # 追加新检查点

            # 只保留最近10个  # 限制数量
            if len(checkpoints) > 10:  # 如果超过10个
                checkpoints = checkpoints[-10:]  # 保留后10个

            await self._redis_backend.set(redis_key, checkpoints, expire_seconds=86400 * 7)  # 保存到Redis，7天过期
        except Exception as e:  # 捕获异常
            logger.error(f"[SILENT_FAILURE_BLOCKED] Redis检查点保存失败: {e}")
            raise CheckpointError(f"无法保存检查点到Redis: {e}") from e

    def _generate_summary(self, messages: list[dict], execution_history: list[dict]) -> str:  # 生成摘要方法
        """生成会话摘要"""  # 方法文档字符串
        # 提取关键信息  # 信息提取
        tool_calls = []  # 工具调用列表
        key_events = []  # 关键事件列表

        for hist in execution_history[-5:]:  # 遍历最近5条历史
            tool = hist.get("tool", "unknown")  # 获取工具名
            success = "成功" if hist.get("success") else "失败"  # 判断成功
            tool_calls.append(f"{tool}({success})")  # 添加到列表

        # 从消息中提取最终状态  # 状态提取
        if messages:  # 如果有消息
            last_msg = messages[-1]  # 获取最后一条
            content = last_msg.get("content", "")  # 获取内容
            if len(content) > 100:  # 如果超过100字符
                content = content[:100] + "..."  # 截断
            key_events.append(f"最后: {content}")  # 添加到事件

        summary = f"已执行: {', '.join(tool_calls)} | {'; '.join(key_events)}"  # 构建摘要
        return summary[:200]  # 限制200字符

    async def _save_checkpoints(self, user_id: str, session_id: str):  # 保存检查点方法（异步化）
        """
        保存检查点到磁盘

        Raises:
            CheckpointError: 保存失败
        """
        cache_key = f"{user_id}:{session_id}"  # 构建缓存Key
        checkpoints = self._checkpoint_cache.get(cache_key, [])  # 获取检查点

        file_path = self._get_user_checkpoint_path(user_id, session_id)  # 获取文件路径
        temp_path = file_path.with_suffix('.json.tmp')  # 临时文件路径

        try:  # 异常处理
            # 原子写入：先写入临时文件，再重命名
            data = [cp.to_dict() for cp in checkpoints]

            # 验证数据完整性
            if checkpoints and not isinstance(data, list):
                raise ValueError(f"检查点数据格式错误: 期望list, 实际{type(data)}")

            def _atomic_write_checkpoint():
                with open(temp_path, "w", encoding="utf-8") as f:  # 写入模式打开
                    json.dump(data, f, ensure_ascii=False, indent=2)  # JSON写入
                    f.flush()
                    os.fsync(f.fileno())
                # 原子重命名
                os.replace(temp_path, file_path)
            import asyncio
            await asyncio.to_thread(_atomic_write_checkpoint)

            # 验证写入成功
            if not file_path.exists():
                raise OSError("文件写入验证失败")

        except Exception as e:  # 捕获异常
            logger.error(f"[SILENT_FAILURE_BLOCKED] 保存检查点失败 {session_id}: {e}")
            # 清理临时文件
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError as e:
                    logger.error(f"[SessionPersistence] 临时文件清理失败: {e}", exc_info=True)
            raise CheckpointError(f"无法保存检查点 {session_id}: {e}") from e

    def _get_user_checkpoint_path(self, user_id: str, session_id: str) -> Path:  # 获取用户检查点路径方法
        """获取用户检查点文件路径"""  # 方法文档字符串
        user_dir = self.base_dir / user_id  # 构建用户目录
        user_dir.mkdir(exist_ok=True)  # 确保目录存在
        return user_dir / f"{session_id}_checkpoints.json"  # 返回文件路径

    async def load_latest_checkpoint(self, session_id: str, user_id: str = None) -> SessionCheckpoint | None:  # 加载最新检查点方法
        """
        加载最新的检查点  # 方法文档字符串

        Args:  # 参数说明
            session_id: 会话ID  # 参数1
            user_id: 用户ID（可选）  # 参数2

        Returns:  # 返回值说明
            SessionCheckpoint对象或None（状态不存在）

        Raises:
            CheckpointError: 状态加载失败（文件存在但读取/解析失败）
        """
        user_id = user_id or "default_user"  # 默认用户
        cache_key = f"{user_id}:{session_id}"  # 构建缓存Key

        # 优先从缓存读取  # 缓存优先
        if cache_key in self._checkpoint_cache and self._checkpoint_cache[cache_key]:  # 如果缓存有数据
            return self._checkpoint_cache[cache_key][-1]  # 返回最后一个

        # 尝试从Redis读取  # Redis读取
        if await self._is_redis_ready_async():  # 如果Redis就绪
            try:  # 异常处理
                redis_key = self._get_checkpoint_key(user_id, session_id)  # 获取Redis Key
                data = await self._redis_backend.get(redis_key)  # 从Redis获取
                if data:  # 如果有数据
                    checkpoints = json.loads(data) if isinstance(data, str) else data  # 解析JSON
                    if checkpoints:  # 如果有检查点
                        # 验证数据完整性
                        self._validate_checkpoint_data(checkpoints)
                        checkpoint = SessionCheckpoint.from_dict(checkpoints[-1])  # 创建对象
                        # 更新缓存  # 缓存更新
                        self._checkpoint_cache[cache_key] = [  # 更新缓存
                            SessionCheckpoint.from_dict(c) for c in checkpoints  # 转换所有
                        ]
                        return checkpoint  # 返回检查点
            except Exception as e:  # 捕获异常
                logger.error(f"[SILENT_FAILURE_BLOCKED] Redis检查点加载失败: {e}")
                raise CheckpointError(f"无法从Redis加载检查点: {e}") from e

        # 从磁盘加载  # 磁盘加载
        file_path = self._get_user_checkpoint_path(user_id, session_id)  # 获取文件路径

        # 状态不存在 - 正常返回None
        if not file_path.exists():  # 如果文件不存在
            return None  # 返回None

        try:  # 异常处理
            def _load_checkpoint_file():
                with open(file_path, encoding="utf-8") as f:  # 读取模式打开
                    return json.load(f)  # JSON加载
            import asyncio
            data = await asyncio.to_thread(_load_checkpoint_file)

            # 验证数据完整性
            self._validate_checkpoint_data(data)

            if data:  # 如果有数据
                checkpoints = [SessionCheckpoint.from_dict(d) for d in data]  # 转换所有
                self._checkpoint_cache[cache_key] = checkpoints  # 更新缓存
                return checkpoints[-1]  # 返回最后一个

        except Exception as e:  # 捕获异常
            logger.error(f"[SILENT_FAILURE_BLOCKED] 加载检查点失败 {session_id}: {e}")
            raise CheckpointError(f"无法加载检查点 {session_id}: {e}") from e

        return None  # 无检查点返回None

    def _validate_checkpoint_data(self, data: Any) -> None:
        """
        验证检查点数据完整性

        Args:
            data: 检查点数据

        Raises:
            CheckpointError: 数据验证失败
        """
        if not isinstance(data, list):
            raise CheckpointError(f"检查点数据格式错误: 期望list, 实际{type(data)}")

        for i, checkpoint in enumerate(data):
            if not isinstance(checkpoint, dict):
                raise CheckpointError(f"检查点[{i}]格式错误: 期望dict, 实际{type(checkpoint)}")

            missing = [f for f in self.REQUIRED_CHECKPOINT_FIELDS if f not in checkpoint]
            if missing:
                raise CheckpointError(f"检查点[{i}]缺少必填字段: {missing}")

    async def memory_flush(self, session_id: str, task_description: str, key_learnings: list[str], user_id: str = None):  # 记忆刷新方法
        """
        Memory Flush - 将关键信息保存到长期记忆  # 方法文档字符串
        类似于OpenClaw的compaction前flush  # 类比说明

        Args:  # 参数说明
            session_id: 会话ID  # 参数1
            task_description: 任务描述  # 参数2
            key_learnings: 关键收获列表  # 参数3
            user_id: 用户ID（可选）  # 参数4

        Raises:
            CheckpointError: 所有保存方式都失败时抛出
        """
        if not key_learnings:  # 如果没有关键收获
            return  # 直接返回

        user_id = user_id or "default_user"  # 默认用户

        # 构建flush内容  # 内容构建
        flush_content = f"""## 会话总结: {task_description}
**用户**: {user_id}
**时间**: {datetime.now().strftime("%Y-%m-%d %H:%M")}
**会话ID**: {session_id}

### 关键收获
"""
        for i, learning in enumerate(key_learnings, 1):  # 遍历收获
            flush_content += f"{i}. {learning}\n"  # 添加编号和内容

        saved_successfully = False  # 标记是否有保存成功
        last_error = None  # 记录最后一个错误

        # 如果Redis可用，保存到Redis  # Redis保存
        if await self._is_redis_ready_async():  # 如果Redis就绪
            try:  # 异常处理
                redis_key = f"{RedisKeyBuilder.PREFIX}:memory_flush:{user_id}:{session_id}"  # 构建Key
                await self._redis_backend.set(redis_key, {  # 保存到Redis
                    "content": flush_content,  # 内容
                    "timestamp": time.time(),  # 时间戳
                    "task_description": task_description,  # 任务描述
                    "key_learnings": key_learnings  # 关键收获
                }, expire_seconds=86400 * 30)  # 30天过期
                saved_successfully = True
            except Exception as e:  # 捕获异常
                last_error = e
                logger.error(f"[SILENT_FAILURE_BLOCKED] Redis Memory Flush失败: {e}")

        # 保存到本地记忆系统  # 本地保存
        if MEMORY_AVAILABLE:  # 如果记忆可用
            try:  # 异常处理
                ms = await get_memory_service()
                await ms.add_memory(  # 添加到记忆
                    user_id=user_id or "default_user",
                    content=flush_content,  # 内容
                    memory_type="session_summary",  # 会话总结类型
                    layer="evolve",  # 进化层
                    scene="long_running_session",  # 场景
                    rating=1,  # 评分
                    source=MemorySource.SYSTEM  # Agent-4: 系统写入
                )
                saved_successfully = True
                logger.info(f"[SessionPersistence] Memory Flush完成: session={session_id}, 记录了{len(key_learnings)}条关键信息")  # 记录日志
            except Exception as e:  # 捕获异常
                last_error = e
                logger.error(f"[SILENT_FAILURE_BLOCKED] Memory Flush失败: {e}")

        # 保存到本地文件作为备份  # 文件备份
        try:  # 异常处理
            memory_dir = self.base_dir.parent / "memory_flush"  # 构建目录
            memory_dir.mkdir(exist_ok=True)  # 确保目录存在
            user_dir = memory_dir / user_id  # 构建用户目录
            user_dir.mkdir(exist_ok=True)  # 确保目录存在

            file_path = user_dir / f"{session_id}_{int(time.time())}.md"  # 构建文件路径
            def _write_flush_backup():
                with open(file_path, "w", encoding="utf-8") as f:  # 写入模式打开
                    f.write(flush_content)  # 写入内容
            import asyncio
            await asyncio.to_thread(_write_flush_backup)
            saved_successfully = True
            logger.info(f"[SessionPersistence] Memory Flush已保存到文件: {file_path}")  # 记录日志
        except Exception as e:  # 捕获异常
            last_error = e
            logger.error(f"[SILENT_FAILURE_BLOCKED] Memory Flush文件保存失败: {e}")

        # 如果所有保存方式都失败，抛出异常
        if not saved_successfully:
            error_msg = f"Memory Flush所有保存方式均失败: {last_error}"
            logger.error(f"[SILENT_FAILURE_BLOCKED] {error_msg}")
            raise CheckpointError(error_msg)

    def cleanup_old_sessions(self, max_age_days: int = 7, user_id: str = None):  # 清理旧会话方法
        """
        清理旧会话文件  # 方法文档字符串

        Args:  # 参数说明
            max_age_days: 最大保留天数  # 参数1
            user_id: 用户ID（可选，为None则清理所有用户）  # 参数2
        """
        now = time.time()  # 当前时间
        deleted = 0  # 删除计数

        if user_id:  # 如果指定了用户
            # 清理特定用户的会话  # 用户清理
            user_dir = self.base_dir / user_id  # 构建用户目录
            if user_dir.exists():  # 如果目录存在
                for file_path in user_dir.rglob("*.jsonl"):  # 遍历会话文件
                    if now - file_path.stat().st_mtime > max_age_days * 86400:  # 如果过期
                        file_path.unlink()  # 删除文件
                        deleted += 1  # 计数增加

                for file_path in user_dir.glob("*_checkpoints.json"):  # 遍历检查点文件
                    if now - file_path.stat().st_mtime > max_age_days * 86400:  # 如果过期
                        file_path.unlink()  # 删除文件
                        deleted += 1  # 计数增加
        else:  # 未指定用户
            # 清理所有用户的会话  # 全部清理
            for file_path in self.base_dir.rglob("*.jsonl"):  # 遍历所有会话文件
                if now - file_path.stat().st_mtime > max_age_days * 86400:  # 如果过期
                    file_path.unlink()  # 删除文件
                    deleted += 1  # 计数增加

            for file_path in self.base_dir.glob("*_checkpoints.json"):  # 遍历所有检查点文件
                if now - file_path.stat().st_mtime > max_age_days * 86400:  # 如果过期
                    file_path.unlink()  # 删除文件
                    deleted += 1  # 计数增加

        if deleted > 0:  # 如果有删除
            logger.info(f"[SessionPersistence] 清理旧会话文件 {deleted} 个")  # 记录日志

    async def get_storage_status(self) -> dict:  # 获取存储状态方法
        """获取存储状态信息"""  # 方法文档字符串
        return {  # 返回状态字典
            "use_redis": self._use_redis,  # 是否使用Redis
            "redis_available": await self._is_redis_ready_async(),  # Redis是否就绪
            "base_dir": str(self.base_dir),  # 基础目录
            "cache_size": len(self._session_cache)  # 缓存大小
        }


# 全局实例（自动检测Redis配置）  # 全局实例注释
_session_persistence = SessionPersistence()  # 创建全局实例


def get_session_persistence() -> SessionPersistence:  # 获取会话持久化函数
    """获取全局会话持久化实例"""  # 函数文档字符串
    return _session_persistence  # 返回全局实例


def create_session_persistence(use_redis: bool = None) -> SessionPersistence:  # 创建会话持久化函数
    """
    创建新的会话持久化实例  # 函数文档字符串

    Args:  # 参数说明
        use_redis: 是否使用Redis  # 参数1

    Returns:  # 返回值说明
        SessionPersistence实例  # 返回类型
    """
    return SessionPersistence(use_redis=use_redis)  # 创建并返回实例


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"会话持久化管理器"，负责会话消息的持久化存储。
# 支持24小时长任务的断点续传，是AgentLoop长期运行的基础保障。
#
# 【架构设计】
# - JSONL格式: 每行一条消息，追加写入，损坏行不影响其他数据
# - 三级存储: 内存缓存 -> Redis -> 本地文件
# - 检查点机制: 定期保存完整状态，支持中断后恢复
# - Memory Flush: 将关键收获保存到长期记忆(L4层)
# - 用户隔离: 按用户ID分目录存储
#
# 【关联文件】
# - core/agent_loop.py             : Agent主循环，调用本模块保存会话
# - core/state_snapshot.py         : 状态快照管理器，与本模块协同工作
# - core/redis_backend.py          : Redis后端实现
# - core/memory.py                 : 五层记忆系统，接收Memory Flush数据
# - core/pause_confirmation_state_machine.py : 长任务状态机
#
# 【核心功能效果】
# 1. 消息持久化: 使用JSONL格式持久化每条消息，支持增量追加
# 2. 检查点机制: 定期保存完整会话状态，支持中断恢复
# 3. 多级存储: 内存缓存+Redis+本地文件，保证数据安全
# 4. Memory Flush: 长任务结束时将关键收获保存到长期记忆
# 5. 自动清理: 支持按时间清理过期会话文件
# 6. 容错处理: 损坏的JSON行会被跳过，不影响其他数据
#
# 【使用场景】
# - 长任务执行: 24小时持续任务的消息记录和状态保存
# - 对话历史: 保存用户与AI的多轮对话历史
# - 故障恢复: 系统重启后从检查点恢复会话
# - 云端部署: Redis支持多实例共享会话数据
# =============================================================================
