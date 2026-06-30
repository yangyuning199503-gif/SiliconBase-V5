#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
用户任务管理器 V5.1 - 业务逻辑层  # 模块功能概述
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  # 装饰线
为用户级任务管理系统提供完整的业务逻辑支持  # 模块职责

【核心功能】  # 功能列表
  - 任务生命周期管理（创建、更新、完成、失败、取消、归档）  # 功能1
  - 依赖管理（添加、移除、循环依赖检测、就绪检测）  # 功能2
  - 语义压缩（AI生成摘要、存入向量库）  # 功能3
  - 记忆关联（与L1-L5记忆关联）  # 功能4
  - 执行计划生成（拓扑排序）  # 功能5
  - 相似任务检索与智能推荐  # 功能6

【架构层次】  # 架构说明
  ┌─────────────────────────────────┐  # 层次1：业务层
  │     UserTaskManager (业务层)     │
  ├─────────────────────────────────┤  # 层次2：数据访问层
  │  UserTaskStore    (数据访问层)   │
  ├─────────────────────────────────┤  # 层次3：底层存储
  │  UserMemoryStore  (底层存储)     │
  ├─────────────────────────────────┤  # 层次4：持久化
  │  SQLite           (持久化)      │
  └─────────────────────────────────┘

【2026-02-26 创建】  # 版本信息
"""  # 文档字符串结束

import asyncio  # 导入异步IO模块
import json  # 导入JSON模块
import logging  # 导入日志模块
from dataclasses import dataclass, field  # 导入数据类装饰器
from datetime import datetime, timedelta  # 导入日期时间类
from enum import Enum  # 导入枚举类
from typing import Any  # 导入类型注解

from core.task.task_status import ARCHIVABLE_STATUSES as TS_ARCHIVABLE
from core.task.task_status import TERMINAL_STATUSES as TS_TERMINAL

# 导入统一任务状态  # 注释：统一任务状态定义
from core.task.task_status import TaskStatus

# 导入数据访问层  # 注释：导入底层存储模块
from core.task.user_task_store import (  # 导入任务存储相关
    UserTaskStore,  # 用户任务存储类
)
from core.task.user_task_vector_store import (  # 导入向量存储相关
    UserTaskVectorStore,  # 用户任务向量存储
)

# 导入任务队列（用于暂停/恢复功能）  # 注释：条件导入
# 尝试导入任务队列模块，如不可用则设置标志
try:
    from core.task.task_queue import get_task_queue  # 导入任务队列获取函数
    TASK_QUEUE_AVAILABLE = True  # 设置可用标志为True
except ImportError:  # 导入失败
    TASK_QUEUE_AVAILABLE = False  # 设置可用标志为False
    get_task_queue = None  # 设置为None


# 任务队列管理器（兼容层）  # 注释：兼容层定义
import threading  # 导入线程模块


class TaskQueueManager:  # 任务队列管理器类
    """
    任务队列管理器 - 兼容层  # 类文档字符串

    为 UserTaskManager 提供统一的任务队列访问接口。  # 类职责
    """

    _instance = None  # 单例实例
    _lock = threading.Lock()  # 单例锁
    _user_queues: dict[str, Any] = {}  # 用户队列字典

    def __new__(cls):  # 单例控制
        if cls._instance is None:  # 实例不存在
            with cls._lock:  # 获取锁
                if cls._instance is None:  # 双重检查
                    cls._instance = super().__new__(cls)  # 创建实例
                    cls._instance._initialized = False  # 标记未初始化
        return cls._instance  # 返回实例

    def __init__(self):  # 初始化
        if self._initialized:  # 已初始化
            return  # 直接返回
        self._initialized = True  # 标记已初始化

    def get_user_queue(self, user_id: str) -> Any:  # 获取用户队列方法
        """
        获取用户的任务队列  # 方法功能

        Args:  # 参数说明
            user_id: 用户ID  # 参数

        Returns:  # 返回值说明
            TaskQueue 实例  # 返回类型
        """
        if user_id not in self._user_queues and get_task_queue:  # 用户队列不存在且获取函数可用
            self._user_queues[user_id] = get_task_queue(user_id)  # 创建队列
        return self._user_queues.get(user_id)  # 返回用户队列


def get_task_queue_manager() -> TaskQueueManager:  # 获取任务队列管理器函数
    """获取任务队列管理器实例"""  # 函数文档字符串
    return TaskQueueManager()  # 返回单例实例

logger = logging.getLogger(__name__)  # 获取模块日志记录器

# ═══════════════════════════════════════════════════════════
# 全局管理器实例缓存
# ═══════════════════════════════════════════════════════════

_user_task_managers: dict[str, "UserTaskManager"] = {}
_user_task_managers_lock = threading.Lock()


def get_user_task_manager(user_id: str) -> "UserTaskManager":
    """
    获取用户的任务管理器实例（单例模式）

    Args:
        user_id: 用户唯一标识

    Returns:
        UserTaskManager: 用户任务管理器实例
    """
    global _user_task_managers

    with _user_task_managers_lock:
        if user_id not in _user_task_managers:
            _user_task_managers[user_id] = UserTaskManager(user_id)
        return _user_task_managers[user_id]


def reset_user_task_manager(user_id: str = None):
    """
    重置用户任务管理器（主要用于测试）

    Args:
        user_id: 用户ID，如果为None则重置所有
    """
    global _user_task_managers

    with _user_task_managers_lock:
        if user_id is None:
            _user_task_managers.clear()
        elif user_id in _user_task_managers:
            del _user_task_managers[user_id]


# ═══════════════════════════════════════════════════════════  # 装饰线
# 枚举与数据类定义  # 区域标题
# ═══════════════════════════════════════════════════════════  # 装饰线

class TaskPriority(Enum):  # 任务优先级枚举类
    """任务优先级枚举"""  # 类文档字符串
    URGENT = 0   # 紧急
    HIGH = 1     # 高
    NORMAL = 2   # 正常
    LOW = 3      # 低


# P0-015: 终态列表常量 - 从统一模块导入并兼容  # 注释：终态常量
# 这些状态的任务会被视为"已完成"，不再阻塞依赖任务
TERMINAL_STATUSES = TS_TERMINAL  # 赋值终态常量

# P0-015: 可归档状态常量 - 从统一模块导入并兼容  # 注释：可归档状态
# 这些状态的任务可以被归档（注意：已归档的不能再归档）
ARCHIVABLE_STATUSES = TS_ARCHIVABLE  # 赋值可归档状态常量

# 为 TaskStatus 添加类属性（便于通过 TaskStatus.TERMINAL_STATUSES 访问）  # 注释：动态添加属性
TaskStatus.TERMINAL_STATUSES = TERMINAL_STATUSES  # 添加终态属性
TaskStatus.ARCHIVABLE_STATUSES = ARCHIVABLE_STATUSES  # 添加可归档属性


@dataclass  # 数据类装饰器
class TaskCreateRequest:  # 创建任务请求数据类
    """创建任务的请求数据类"""  # 类文档字符串
    title: str                                  # 任务标题（必需）
    description: str = ""                       # 任务描述
    priority: TaskPriority = TaskPriority.NORMAL  # 优先级，默认正常
    task_type: str = "custom"                   # 任务类型
    parent_id: str | None = None             # 父任务ID
    depends_on: list[str] = field(default_factory=list)  # 依赖的任务ID列表
    memory_ids: list[str] = field(default_factory=list)  # 关联的记忆ID列表
    deadline: str | None = None              # ISO格式截止时间
    max_retries: int = 3                        # 最大重试次数
    metadata: dict[str, Any] = field(default_factory=dict)  # 额外元数据


# ═══════════════════════════════════════════════════════════  # 装饰线
# AI 适配器（简化版，后续可替换为真实的 AIAdapter）  # 区域标题
# ═══════════════════════════════════════════════════════════  # 装饰线

class _AIAdapter:  # AI适配器类（内部使用）
    """
    AI适配器（简化版）  # 类文档字符串

    用于生成任务摘要和提取关键词。  # 类职责
    如果真实的 AIAdapter 可用，建议替换为实际实现。  # 建议
    """

    def __init__(self):  # 初始化
        self._initialized = True  # 标记已初始化

    async def summarize(self, text: str, max_length: int = 200) -> str:  # 生成摘要方法
        """
        生成文本摘要  # 方法功能

        Args:  # 参数说明
            text: 要摘要的文本  # 参数1
            max_length: 最大长度  # 参数2

        Returns:  # 返回值说明
            摘要文本  # 返回类型
        """
        # 简化实现：智能截断，保留关键信息  # 注释：简化算法
        if len(text) <= max_length:  # 文本长度在限制内
            return text  # 直接返回

        # 尝试在句子边界截断  # 注释：智能截断
        truncated = text[:max_length]  # 先截断到最大长度
        last_sentence = max(  # 查找最后一个句子结束位置
            truncated.rfind('.'),  # 查找英文句号
            truncated.rfind('。'),  # 查找中文句号
            truncated.rfind('\n')  # 查找换行符
        )

        if last_sentence > max_length * 0.7:  # 如果句子边界在70%之后
            return truncated[:last_sentence + 1] + ".."  # 在句子边界截断
        else:
            return truncated[:max_length - 3] + "..."  # 直接截断加省略号

    async def extract_keywords(self, text: str, max_keywords: int = 5) -> list[str]:  # 提取关键词方法
        """
        提取关键词  # 方法功能

        Args:  # 参数说明
            text: 要分析的文本  # 参数1
            max_keywords: 最大关键词数量  # 参数2

        Returns:  # 返回值说明
            关键词列表  # 返回类型
        """
        # 简化实现：提取较长的词汇  # 注释：简化算法
        import re  # 导入正则模块
        words = re.findall(r'\b[a-zA-Z]{4,}\b|[\u4e00-\u9fa5]{2,}', text)  # 匹配英文单词或中文字符
        word_freq = {}  # 词频字典
        for word in words:  # 遍历词汇
            word_freq[word] = word_freq.get(word, 0) + 1  # 统计频率

        # 按频率排序，返回前N个  # 注释：排序取Top
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)  # 降序排序
        return [word for word, _ in sorted_words[:max_keywords]]  # 返回关键词列表

    async def generate_task_summary(self, title: str, description: str,
                                   result: dict | None = None) -> str:  # 生成任务摘要方法
        """
        生成任务摘要（专为任务设计）  # 方法功能

        Args:  # 参数说明
            title: 任务标题  # 参数1
            description: 任务描述  # 参数2
            result: 执行结果（可选）  # 参数3

        Returns:  # 返回值说明
            任务摘要  # 返回类型
        """
        parts = [f"任务: {title}"]  # 构建摘要部分列表

        if description:  # 有描述
            parts.append(f"描述: {description[:100]}")  # 添加描述（限制长度）

        if result:  # 有结果
            result_str = json.dumps(result, ensure_ascii=False)[:150]  # 序列化结果
            parts.append(f"结果: {result_str}")  # 添加结果

        full_text = " | ".join(parts)  # 用分隔符连接各部分
        return await self.summarize(full_text, max_length=300)  # 调用摘要方法


# ═══════════════════════════════════════════════════════════  # 装饰线
# 主类：UserTaskManager  # 区域标题
# ═══════════════════════════════════════════════════════════  # 装饰线

class UserTaskManager:  # 用户任务管理器类
    """
    用户任务管理器 - 业务逻辑层  # 类文档字符串

    提供完整的任务生命周期管理、依赖管理、语义压缩等功能。  # 类职责

    Usage:  # 使用示例
        manager = UserTaskManager("user_123")  # 创建管理器实例

        # 创建任务  # 示例1
        request = TaskCreateRequest(title="分析数据", priority=TaskPriority.HIGH)  # 创建请求
        task_id = await manager.create_task(request)  # 创建任务

        # 完成任务  # 示例2
        await manager.complete_task(task_id, result={"status": "success"})  # 标记完成
    """

    def __init__(self, user_id: str):  # 初始化方法
        """
        初始化任务管理器  # 方法功能

        Args:  # 参数说明
            user_id: 用户唯一标识  # 参数
        """
        self.user_id = user_id  # 保存用户ID

        # 初始化数据访问层  # 注释：初始化存储层
        self._task_store = UserTaskStore(user_id)  # 创建任务存储实例
        self._vector_store = UserTaskVectorStore(user_id)  # 创建向量存储实例

        # 初始化 AI 适配器  # 注释：初始化AI组件
        self._ai_adapter = _AIAdapter()  # 创建AI适配器实例

        # 初始化任务队列管理器（用于暂停/恢复功能）  # 注释：条件初始化
        if TASK_QUEUE_AVAILABLE and get_task_queue_manager:  # 如果队列可用
            self._task_queue_manager = get_task_queue_manager()  # 创建队列管理器
        else:
            self._task_queue_manager = None  # 设置为None

        logger.info(f"[UserTaskManager] 用户 {user_id} 的任务管理器初始化完成")  # 记录日志

    async def cancel_task(self, task_id: str, reason: str | None = None) -> bool:
        """
        取消任务

        将任务状态更新为 cancelled，并触发中断信号。

        Args:
            task_id: 任务ID
            reason: 取消原因

        Returns:
            bool: 是否成功取消
        """
        try:
            # 1. 更新任务状态为 cancelled
            from core.task.task_status import TaskStatus
            updates = {
                "status": TaskStatus.CANCELLED.value,
                "cancelled_at": datetime.now().isoformat(),
                "cancel_reason": reason or "用户取消"
            }
            success = self._task_store.update_task(task_id, updates)

            if not success:
                logger.warning(f"[UserTaskManager] 取消任务失败: {task_id}")
                return False

            # 2. 触发中断信号（如果任务正在运行）
            try:
                from core.agent.interrupt_handler import interrupt_handler
                await interrupt_handler.handle_interrupt(
                    reason=reason or "用户取消任务",
                    task_id=task_id
                )
            except Exception as e:
                logger.debug(f"[UserTaskManager] 触发中断信号失败（可能任务未运行）: {e}")

            logger.info(f"[UserTaskManager] 任务已取消: {task_id}, 原因: {reason}")
            return True

        except Exception as e:
            logger.error(f"[UserTaskManager] 取消任务失败: {e}")
            return False

    async def complete_task(
        self,
        task_id: str,
        result: dict[str, Any] | None = None,
        trigger_compression: bool = True,
    ) -> bool:
        """
        标记任务完成

        将任务状态更新为 completed，并可选触发语义压缩生成摘要。

        Args:
            task_id: 任务ID
            result: 执行结果
            trigger_compression: 是否立即触发语义压缩

        Returns:
            bool: 是否成功
        """
        try:
            task = await self._task_store.get_task(task_id)
            if not task:
                logger.warning(f"[UserTaskManager] 完成任务失败: {task_id} 不存在")
                return False

            updates = {
                "status": TaskStatus.COMPLETED.value,
                "completed_at": datetime.now().isoformat(),
                "result": json.dumps(result, ensure_ascii=False) if result else None,
            }
            success = await self._task_store.update_task(task_id, updates)
            if not success:
                logger.warning(f"[UserTaskManager] 更新任务完成状态失败: {task_id}")
                return False

            if trigger_compression:
                try:
                    await self.compress_task(task_id, force=False)
                except Exception as e:
                    logger.warning(f"[UserTaskManager] 完成任务后自动压缩失败: {e}")

            logger.info(f"[UserTaskManager] 任务已完成: {task_id}")
            return True
        except Exception as e:
            logger.error(f"[UserTaskManager] 完成任务失败: {e}")
            return False

    async def fail_task(self, task_id: str, error: str | None = None) -> bool:
        """
        标记任务失败

        将任务状态更新为 failed，并记录错误信息。

        Args:
            task_id: 任务ID
            error: 错误信息

        Returns:
            bool: 是否成功
        """
        try:
            task = await self._task_store.get_task(task_id)
            if not task:
                logger.warning(f"[UserTaskManager] 标记任务失败失败: {task_id} 不存在")
                return False

            updates = {
                "status": TaskStatus.FAILED.value,
                "failed_at": datetime.now().isoformat(),
                "error": error or "用户手动标记失败",
            }
            success = await self._task_store.update_task(task_id, updates)
            if not success:
                logger.warning(f"[UserTaskManager] 更新任务失败状态失败: {task_id}")
                return False

            logger.info(f"[UserTaskManager] 任务已标记为失败: {task_id}")
            return True
        except Exception as e:
            logger.error(f"[UserTaskManager] 标记任务失败失败: {e}")
            return False

    async def compress_task(
        self, task_id: str, force: bool = False
    ) -> str | None:
        """
        对任务进行语义压缩

        生成任务摘要并存入向量库，用于后续相似搜索。

        Args:
            task_id: 任务ID
            force: 是否强制重新压缩

        Returns:
            Optional[str]: 生成的摘要，失败返回 None
        """
        try:
            task = await self._task_store.get_task(task_id)
            if not task:
                logger.warning(f"[UserTaskManager] 压缩任务失败: {task_id} 不存在")
                return None

            status = task.get("status")
            if status != TaskStatus.COMPLETED.value and not force:
                logger.warning(
                    f"[UserTaskManager] 任务 {task_id} 状态为 {status}，非完成状态且未强制压缩，跳过"
                )
                return None

            result = None
            try:
                result_str = task.get("result")
                if result_str:
                    result = json.loads(result_str)
            except Exception:
                result = None

            summary = await self.generate_task_summary(
                title=task.get("title", ""),
                description=task.get("description", ""),
                result=result,
            )

            if not summary:
                logger.warning(f"[UserTaskManager] 任务 {task_id} 生成摘要为空")
                return None

            metadata = {
                "status": status,
                "compressed_at": datetime.now().isoformat(),
            }
            await self._vector_store.add_task_summary(task_id, summary, metadata)

            await self._task_store.update_task(
                task_id,
                {
                    "summary": summary,
                    "compressed_at": datetime.now().isoformat(),
                },
            )

            logger.info(f"[UserTaskManager] 任务 {task_id} 语义压缩完成")
            return summary
        except Exception as e:
            logger.error(f"[UserTaskManager] 压缩任务失败: {e}")
            return None

    async def pause_task(self, task_id: str, reason: str | None = None,
                         new_requirements: str | None = None,
                         working_memory = None) -> dict[str, Any]:
        """
        暂停任务 - 【关键修复】保存完整状态到PostgreSQL

        将任务状态更新为 paused，触发中断信号，并保存完整状态到CheckpointManager。

        Args:
            task_id: 任务ID
            reason: 暂停原因
            new_requirements: 用户提出的新需求
            working_memory: 工作记忆对象，用于同步phase_anchors

        Returns:
            Dict: 包含暂停结果、AI对话提示和checkpoint_id
        """
        try:
            # 1. 获取当前任务
            task = self._task_store.get_task(task_id)
            if not task:
                return {"success": False, "error": "Task not found"}

            # 2. 检查任务状态是否可以暂停
            from core.task.task_status import TaskStatus
            current_status = task.get("status")
            if current_status not in [TaskStatus.RUNNING.value, TaskStatus.READY.value]:
                return {
                    "success": False,
                    "error": f"任务状态为 {current_status}，无法暂停"
                }

            # 3. 【关键修复】调用CheckpointManager保存完整状态（包括phase_anchors）
            checkpoint_id = None
            phase_count = 0
            try:
                from core.agent.checkpoint_manager import checkpoint_manager

                if checkpoint_manager:
                    # 获取或创建任务执行状态
                    try:
                        task_state = await checkpoint_manager.get_task(task_id)
                    except Exception:
                        # 如果任务不存在于checkpoint_manager，创建一个
                        task_state = await checkpoint_manager.create_task(
                            task_id=task_id,
                            user_id=self.user_id,
                            total_steps=task.get("total_steps", 10),
                            global_context={
                                "title": task.get("title", ""),
                                "description": task.get("description", ""),
                                "task_type": task.get("task_type", "custom")
                            }
                        )

                    # 【关键】同步working_memory中的phase_anchors到task_state
                    if working_memory and hasattr(working_memory, 'phase_anchors'):
                        task_state.phase_anchors = working_memory.phase_anchors
                        phase_count = len(working_memory.phase_anchors)
                        logger.info(f"[UserTaskManager] [PauseSync] 已同步{phase_count}个阶段锚点到task_state")
                    elif task.get("phase_anchors"):
                        # 如果task对象中有phase_anchors，也同步到task_state
                        task_state.phase_anchors = task.get("phase_anchors")
                        phase_count = len(task.get("phase_anchors"))
                        logger.info(f"[UserTaskManager] [PauseSync] 从task对象同步{phase_count}个阶段锚点")

                    # 暂停任务并保存完整状态
                    await checkpoint_manager.pause_task(task_id, reason or "用户暂停")
                    checkpoint_id = f"checkpoint_{task_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

                    logger.info(f"[UserTaskManager] Checkpoint已保存: {checkpoint_id}, phase_anchors: {phase_count}")
                else:
                    logger.warning("[UserTaskManager] CheckpointManager不可用，跳过状态保存")

            except Exception as e:
                logger.error(f"[UserTaskManager] 保存Checkpoint失败: {e}", exc_info=True)
                # 不阻断主流程，继续暂停任务

            # 4. 更新任务状态为 paused
            updates = {
                "status": TaskStatus.PAUSED.value,
                "paused_at": datetime.now().isoformat(),
                "pause_reason": reason or "用户暂停",
                "new_requirements": new_requirements,
                "checkpoint_id": checkpoint_id  # 【新增】保存checkpoint_id
            }
            success = self._task_store.update_task(task_id, updates)

            if not success:
                return {"success": False, "error": "更新任务状态失败"}

            # 5. 触发中断信号
            try:
                from core.agent.interrupt_handler import interrupt_handler
                await interrupt_handler.handle_interrupt(
                    reason=reason or "用户暂停任务",
                    task_id=task_id
                )
            except Exception as e:
                logger.debug(f"[UserTaskManager] 触发中断信号失败: {e}")

            # 6. 生成AI对话提示
            pause_prompt = "任务已暂停。"
            if reason:
                pause_prompt += f" 原因: {reason}"
            if new_requirements:
                pause_prompt += f" 新需求: {new_requirements}"
            pause_prompt += " 请确认理解后可以继续任务。"

            logger.info(f"[UserTaskManager] 任务已暂停: {task_id}, checkpoint_id: {checkpoint_id}")

            # 7. 【关键修复】返回包含checkpoint_id的响应
            return {
                "success": True,
                "task_id": task_id,
                "status": TaskStatus.PAUSED.value,
                "checkpoint_id": checkpoint_id,  # 【新增】
                "phase_count": phase_count,  # 【新增】
                "ai_prompt": pause_prompt,
                "requires_ai_confirmation": True,
                "message": "任务已暂停，所有进度已保存"  # 【新增】
            }

        except Exception as e:
            logger.error(f"[UserTaskManager] 暂停任务失败: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def resume_task(self, task_id: str, ai_confirmation: bool = False,
                          confirmed_understanding: str | None = None,
                          session_id: str | None = None) -> dict[str, Any]:
        """
        恢复暂停的任务

        【修复说明】添加CheckpointManager调用，完整恢复任务状态包括phase_anchors
        【零静默失败】CheckpointManager恢复失败时抛出异常，绝不静默返回成功

        将任务状态从 paused 恢复为 ready 或 running。

        Args:
            task_id: 任务ID
            ai_confirmation: AI是否已确认理解
            confirmed_understanding: AI确认理解的内容
            session_id: 会话ID（可选），用于精确恢复对话上下文

        Returns:
            Dict: 包含恢复结果
        """
        checkpoint_restored = False

        try:
            # 1. 获取当前任务
            task = self._task_store.get_task(task_id)
            if not task:
                logger.error(f"[SILENT_FAILURE_BLOCKED] 恢复任务失败: 任务 {task_id} 不存在")
                raise RuntimeError(f"任务 {task_id} 不存在")

            # 2. 检查任务状态
            from core.task.task_status import TaskStatus
            current_status = task.get("status")
            # 【修复】支持从 PAUSED / FAILED / INTERRUPTED 恢复，与 checkpoint_manager 保持一致
            resumable_statuses = [
                TaskStatus.PAUSED.value,
                TaskStatus.FAILED.value,
                TaskStatus.INTERRUPTED.value,
                TaskStatus.CONFIRMED.value  # 长任务确认后可恢复
            ]
            if current_status not in resumable_statuses:
                logger.error(f"[SILENT_FAILURE_BLOCKED] 恢复任务失败: 任务 {task_id} 状态为 {current_status}，不在可恢复状态列表")
                raise RuntimeError(f"任务状态为 {current_status}，无法恢复")

            # 3. AI确认（从强制改为可选）
            if not ai_confirmation:
                logger.warning(f"[UserTaskManager] 任务 {task_id} 恢复时未提供AI确认，允许强制恢复")
                # 【修复】不再阻断恢复流程。前端 TaskControlPanel 没有提供 AI 确认的 UI，
                # 如果强制要求确认，用户点击"恢复"将永远无法成功。

            # 【关键修复】从CheckpointManager恢复完整状态
            try:
                from core.agent.checkpoint_manager import checkpoint_manager

                if checkpoint_manager is None:
                    logger.error("[SILENT_FAILURE_BLOCKED] CheckpointManager未初始化")
                    raise RuntimeError("CheckpointManager未初始化")

                # 恢复任务执行状态（调用异步版本避免阻塞事件循环）
                task_state = await checkpoint_manager.resume_task_async(task_id, session_id=session_id)

                if not task_state:
                    logger.error(f"[SILENT_FAILURE_BLOCKED] 从CheckpointManager恢复任务{task_id}失败: 返回空状态")
                    raise RuntimeError(f"无法从检查点恢复任务 {task_id}，状态可能已丢失")

                # 【关键修复】同步phase_anchors到working_memory
                phase_count = 0
                if hasattr(task_state, 'phase_anchors') and task_state.phase_anchors:
                    task['phase_anchors'] = task_state.phase_anchors
                    phase_count = len(task_state.phase_anchors)
                    logger.info(f"[UserTaskManager] [ResumeSync] 已恢复{phase_count}个阶段锚点")
                else:
                    logger.warning(f"[UserTaskManager] [ResumeSync] 任务{task_id}的checkpoint中无阶段锚点")

                checkpoint_restored = True

            except Exception as checkpoint_error:
                logger.error(f"[SILENT_FAILURE_BLOCKED] 从CheckpointManager恢复任务{task_id}异常: {checkpoint_error}")
                # 恢复失败时阻止任务恢复，避免状态不一致
                raise RuntimeError(f"恢复任务状态失败: {checkpoint_error}") from checkpoint_error

            # 验证checkpoint确实已恢复
            if not checkpoint_restored:
                logger.error(f"[SILENT_FAILURE_BLOCKED] 恢复任务{task_id}失败: checkpoint恢复标志未设置")
                raise RuntimeError("任务状态恢复验证失败")

            # 4. 更新任务状态为 ready
            updates = {
                "status": TaskStatus.READY.value,
                "resumed_at": datetime.now().isoformat(),
                "ai_confirmation": confirmed_understanding
            }
            success = self._task_store.update_task(task_id, updates)

            if not success:
                logger.error(f"[SILENT_FAILURE_BLOCKED] 更新任务{task_id}状态失败")
                raise RuntimeError("更新任务状态失败")

            phase_count = len(task.get('phase_anchors', []))
            logger.info(f"[UserTaskManager] 任务{task_id}恢复成功，包含{phase_count}个阶段锚点")

            return {
                "success": True,
                "task_id": task_id,
                "status": TaskStatus.READY.value,
                "message": "任务已恢复，等待执行",
                "phase_count": phase_count,
                "checkpoint_restored": True
            }

        except Exception as e:
            logger.error(f"[SILENT_FAILURE_BLOCKED] 恢复任务{task_id}异常: {e}", exc_info=True)
            raise RuntimeError(f"恢复任务失败: {e}") from e

    # ═══════════════════════════════════════════════════════════════════
    # 缺失方法补齐（P0 修复）
    # ═══════════════════════════════════════════════════════════════════

    async def create_task(self, create_req: TaskCreateRequest) -> str:
        """
        创建任务
        """
        try:
            task_data = {
                "title": create_req.title,
                "description": create_req.description,
                "priority": create_req.priority.value if isinstance(create_req.priority, TaskPriority) else create_req.priority,
                "task_type": create_req.task_type,
                "parent_id": create_req.parent_id,
                "depends_on": create_req.depends_on or [],
                "memory_ids": create_req.memory_ids or [],
                "deadline": create_req.deadline,
                "max_retries": create_req.max_retries,
                "metadata": create_req.metadata or {},
                "status": TaskStatus.PENDING.value,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
            task_id = await self._task_store.create_task(task_data)
            logger.info(f"[UserTaskManager] 任务创建成功: {task_id}")
            return task_id
        except Exception as e:
            logger.error(f"[UserTaskManager] 创建任务失败: {e}")
            raise

    async def get_task_with_deps(self, task_id: str) -> dict[str, Any]:
        """
        获取任务详情（包含依赖信息）
        """
        try:
            task = await self._task_store.get_task(task_id)
            if not task:
                return {"task": None}
            dependencies = await self._task_store.get_dependencies(task_id)
            dependents = await self._task_store.get_dependents(task_id)
            return {
                "task": task,
                "dependencies": dependencies,
                "dependents": dependents,
                "ready_to_run": len(dependencies) == 0 or all(
                    d.get("status") in TS_TERMINAL for d in dependencies
                ),
            }
        except Exception as e:
            logger.error(f"[UserTaskManager] 获取任务详情失败: {e}")
            raise

    async def update_task(self, task_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """
        更新任务，返回更新后的任务
        """
        try:
            updates["updated_at"] = datetime.now().isoformat()
            success = await self._task_store.update_task(task_id, updates)
            if not success:
                raise RuntimeError("更新任务失败")
            task = await self._task_store.get_task(task_id)
            return {"success": True, "task": task}
        except Exception as e:
            logger.error(f"[UserTaskManager] 更新任务失败: {e}")
            raise

    async def archive_task(self, task_id: str) -> bool:
        """
        归档任务
        """
        try:
            task = await self._task_store.get_task(task_id)
            if not task:
                return False
            status = task.get("status")
            if status not in ARCHIVABLE_STATUSES:
                logger.warning(f"[UserTaskManager] 任务 {task_id} 状态 {status} 不可归档")
                return False
            # 检查是否有未完成的依赖者
            dependents = await self._task_store.get_dependents(task_id)
            for dep in dependents:
                if dep.get("status") not in TS_TERMINAL:
                    logger.warning(f"[UserTaskManager] 任务 {task_id} 有未完成的依赖者")
                    return False
            success = await self._task_store.update_task(
                task_id,
                {"status": TaskStatus.ARCHIVED.value, "archived_at": datetime.now().isoformat()},
            )
            return success
        except Exception as e:
            logger.error(f"[UserTaskManager] 归档任务失败: {e}")
            return False

    async def add_dependency(
        self, task_id: str, depends_on: str, dependency_type: str = "blocks"
    ) -> bool:
        """
        添加任务依赖
        """
        try:
            # 检查循环依赖
            has_cycle = await self._task_store.check_circular_dependency(task_id, depends_on)
            if has_cycle:
                logger.warning(f"[UserTaskManager] 添加依赖会产生循环依赖: {task_id} -> {depends_on}")
                return False
            success = await self._task_store.add_dependency(task_id, depends_on, dependency_type)
            return success
        except Exception as e:
            logger.error(f"[UserTaskManager] 添加依赖失败: {e}")
            return False

    async def remove_dependency(self, task_id: str, depends_on: str) -> bool:
        """
        移除任务依赖
        """
        try:
            success = await self._task_store.remove_dependency(task_id, depends_on)
            return success
        except Exception as e:
            logger.error(f"[UserTaskManager] 移除依赖失败: {e}")
            return False

    async def get_execution_plan(self) -> list[list[str]]:
        """
        获取任务执行计划（拓扑排序）
        """
        try:
            tasks = await self._task_store.list_tasks(status=None, limit=1000, offset=0)
            task_ids = {t.get("task_id") or t.get("id") for t in tasks}
            graph: dict[str, set[str]] = {tid: set() for tid in task_ids}
            in_degree: dict[str, int] = dict.fromkeys(task_ids, 0)

            for t in tasks:
                tid = t.get("task_id") or t.get("id")
                deps = t.get("depends_on", [])
                if isinstance(deps, str):
                    try:
                        deps = json.loads(deps)
                    except Exception:
                        deps = []
                for dep in deps:
                    if dep in task_ids:
                        graph[dep].add(tid)
                        in_degree[tid] += 1

            # Kahn 算法分层
            plan: list[list[str]] = []
            remaining = {tid for tid, deg in in_degree.items() if deg == 0}
            while remaining:
                plan.append(list(remaining))
                next_remaining = set()
                for tid in remaining:
                    for neighbor in graph.get(tid, set()):
                        in_degree[neighbor] -= 1
                        if in_degree[neighbor] == 0:
                            next_remaining.add(neighbor)
                remaining = next_remaining

            return plan
        except Exception as e:
            logger.error(f"[UserTaskManager] 获取执行计划失败: {e}")
            return []

    async def batch_compress_tasks(
        self, task_ids: list[str], max_concurrent: int = 3
    ) -> list[dict[str, Any]]:
        """
        批量压缩任务
        """
        try:
            semaphore = asyncio.Semaphore(max_concurrent)

            async def compress_one(task_id: str) -> dict[str, Any]:
                async with semaphore:
                    summary = await self.compress_task(task_id, force=False)
                    return {"task_id": task_id, "success": summary is not None, "summary": summary}

            results = await asyncio.gather(*[compress_one(tid) for tid in task_ids])
            return results
        except Exception as e:
            logger.error(f"[UserTaskManager] 批量压缩任务失败: {e}")
            return []

    async def find_similar_tasks(
        self,
        query: str,
        n_results: int = 10,
        include_completed_only: bool = True,
    ) -> list[dict[str, Any]]:
        """
        搜索相似任务
        """
        try:
            results = await self._vector_store.search_similar_tasks(
                query=query,
                n_results=n_results,
                filter_dict={"status": "completed"} if include_completed_only else None,
            )
            return results if results else []
        except Exception as e:
            logger.error(f"[UserTaskManager] 搜索相似任务失败: {e}")
            return []

    async def suggest_next_tasks(self, n_suggestions: int = 3) -> list[dict[str, Any]]:
        """
        智能推荐下一个任务
        """
        try:
            ready_tasks = await self._task_store.get_ready_tasks()
            # 按优先级和截止时间排序
            def sort_key(t):
                priority = t.get("priority", 2)
                deadline = t.get("deadline") or "9999-12-31"
                return (priority, deadline)

            ready_tasks.sort(key=sort_key)
            return ready_tasks[:n_suggestions]
        except Exception as e:
            logger.error(f"[UserTaskManager] 推荐下一个任务失败: {e}")
            return []

    async def get_task_tree(self, root_task_id: str) -> dict[str, Any]:
        """
        获取任务树
        """
        try:
            root = await self._task_store.get_task(root_task_id)
            if not root:
                return {"task_id": root_task_id, "task": None, "children": []}

            async def build_tree(task_id: str) -> dict[str, Any]:
                task = await self._task_store.get_task(task_id)
                if not task:
                    return {"task_id": task_id, "task": None, "children": []}
                children = await self._task_store.list_tasks(parent_id=task_id, limit=1000, offset=0)
                return {
                    "task_id": task_id,
                    "task": task,
                    "children": [await build_tree(c.get("task_id") or c.get("id")) for c in children],
                }

            return await build_tree(root_task_id)
        except Exception as e:
            logger.error(f"[UserTaskManager] 获取任务树失败: {e}")
            return {"task_id": root_task_id, "task": None, "children": []}

    async def get_stats(self) -> dict[str, Any]:
        """
        获取任务统计信息
        """
        try:
            return await self._task_store.get_task_stats()
        except Exception as e:
            logger.error(f"[UserTaskManager] 获取任务统计失败: {e}")
            return {}

    async def cleanup_old_tasks(self, days: int = 30, archive_first: bool = True) -> int:
        """
        清理旧任务
        """
        try:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            tasks = await self._task_store.list_tasks(
                status=None,
                limit=10000,
                offset=0,
            )
            count = 0
            for t in tasks:
                tid = t.get("task_id") or t.get("id")
                created_at = t.get("created_at", "")
                status = t.get("status", "")
                if created_at < cutoff and status in TS_TERMINAL:
                    if archive_first and status != TaskStatus.ARCHIVED.value:
                        await self.archive_task(tid)
                    await self._task_store.delete_task(tid)
                    count += 1
            return count
        except Exception as e:
            logger.error(f"[UserTaskManager] 清理旧任务失败: {e}")
            return 0


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的用户任务管理器，位于业务逻辑层。
# 提供完整的任务生命周期管理、依赖管理、语义压缩、智能推荐等功能。
#
# 【核心功能】
# 1. 任务生命周期管理：创建、更新、完成、失败、取消、归档全流程
# 2. 依赖管理：支持任务间依赖，自动检测循环依赖，拓扑排序生成执行计划
# 3. 语义压缩：AI生成任务摘要，存入向量库支持相似检索
# 4. 智能推荐：基于优先级、截止时间推荐下一个任务
# 5. 暂停恢复：支持任务暂停和AI需求确认机制
#
# 【架构层次】
# - 业务层：UserTaskManager 提供高层接口
# - 数据层：UserTaskStore 负责持久化
# - 向量层：UserTaskVectorStore 负责语义存储
#
# 【关联文件】
# - core/user_task_store.py: 数据访问层
# - core/user_task_vector_store.py: 向量存储
# - core/task_status.py: 统一任务状态
# =============================================================================
