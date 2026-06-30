#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
统一状态快照管理器  # 模块功能：任务状态快照的捕获和恢复
解决任务中断后无法正确恢复的状态爆炸问题  # 核心问题：状态恢复
与大纲长任务模式完美集成  # 集成特性
"""  # 文档字符串结束

import asyncio
import glob  # 导入glob模块，用于文件匹配
import json  # 导入JSON模块，用于序列化
import os  # 导入os模块，用于文件操作
import time  # 导入时间模块，用于时间戳
from dataclasses import dataclass  # 导入数据类和工具
from typing import Any  # 导入类型注解

from core.exceptions import SnapshotError  # 从统一异常模块导入
from core.logger import logger  # 导入日志记录器


@dataclass  # 数据类装饰器
class TaskStateSnapshot:  # 定义任务状态快照数据类
    """任务状态快照"""  # 类文档字符串
    task_id: str  # 任务ID字段
    timestamp: float  # 时间戳字段（Unix时间）
    session_id: str  # 会话ID字段
    user_id: str  # 用户ID字段

    # WorkingMemory状态  # 工作记忆状态
    working_memory_state: dict[str, Any]  # 工作记忆状态字典

    # AgentLoop状态  # Agent循环状态
    loop_round: int  # 循环轮次
    chat_count: int  # 聊天计数
    execution_history: list[dict]  # 执行历史列表

    # 对话上下文  # 对话上下文
    chat_history: list[dict[str, str]]  # 聊天历史列表

    # 长任务状态机状态  # 长任务状态
    long_task_state: str | None = None  # 长任务状态，可选
    user_requirements: list[dict] | None = None  # 用户需求列表，可选
    ai_understanding: str | None = None  # AI理解摘要，可选


class StateSnapshotManager:  # 定义状态快照管理器类
    """
    统一状态快照管理器  # 类文档字符串

    设计原则：  # 设计说明
    1. 不破坏原有状态容器，只添加快照/恢复能力  # 原则1
    2. 与LongTaskStateMachine集成，支持暂停/恢复  # 原则2
    3. 快照可序列化，支持持久化存储  # 原则3
    """  # 类文档字符串结束

    # 状态数据必填字段
    REQUIRED_SNAPSHOT_FIELDS = ['task_id', 'timestamp', 'session_id', 'user_id',
                                'working_memory_state', 'loop_round', 'chat_count',
                                'execution_history', 'chat_history']

    def __init__(self, storage_dir: str = "data/state_snapshots"):  # 初始化方法
        """初始化状态快照管理器"""  # 方法文档字符串
        self.storage_dir = storage_dir  # 设置存储目录
        self._memory_cache: dict[str, TaskStateSnapshot] = {}  # 内存缓存字典

        # 确保存储目录存在  # 目录创建
        os.makedirs(storage_dir, exist_ok=True)  # 创建目录（如果不存在）

    async def capture_snapshot(self, task_id: str,  # 捕获快照方法
                        working_memory,  # 工作记忆实例
                        loop_state,  # 循环状态实例
                        chat_history: list[dict],  # 聊天历史
                        session_id: str,  # 会话ID
                        user_id: str = "default",  # 用户ID，默认default
                        long_task_sm=None) -> TaskStateSnapshot:  # 长任务状态机，可选
        """
        捕获当前任务的所有状态快照（异步版本）  # 方法文档字符串

        Args:  # 参数说明
            task_id: 任务ID  # 参数1
            working_memory: WorkingMemory实例  # 参数2
            loop_state: LoopState实例  # 参数3
            chat_history: 聊天历史  # 参数4
            session_id: 会话ID  # 参数5
            user_id: 用户ID  # 参数6
            long_task_sm: 长任务状态机（可选）  # 参数7

        Returns:  # 返回值说明
            TaskStateSnapshot: 状态快照  # 返回类型

        Raises:
            SnapshotError: 快照捕获或保存失败
        """
        # 捕获WorkingMemory状态  # 捕获工作记忆
        wm_state = self._capture_working_memory(working_memory)  # 调用捕获方法

        # 捕获AgentLoop状态  # 捕获循环状态
        loop_state_data = self._capture_loop_state(loop_state)  # 调用捕获方法

        # 捕获长任务状态  # 捕获长任务状态
        long_task_state = None  # 初始化长任务状态
        user_requirements = None  # 初始化用户需求
        ai_understanding = None  # 初始化AI理解
        if long_task_sm:  # 如果提供了状态机
            long_task_state = long_task_sm.state.name if hasattr(long_task_sm.state, 'name') else str(long_task_sm.state)  # 获取状态名
            user_requirements = getattr(long_task_sm, 'user_requirements', None)  # 获取用户需求
            ai_understanding = getattr(long_task_sm, 'ai_understanding', None)  # 获取AI理解

        snapshot = TaskStateSnapshot(  # 创建快照对象
            task_id=task_id,  # 任务ID
            timestamp=time.time(),  # 当前时间戳
            session_id=session_id,  # 会话ID
            user_id=user_id,  # 用户ID
            working_memory_state=wm_state,  # 工作记忆状态
            loop_round=loop_state_data.get('round', 0),  # 循环轮次
            chat_count=loop_state_data.get('chat_count', 0),  # 聊天计数
            execution_history=loop_state_data.get('execution_history', []),  # 执行历史
            chat_history=chat_history[-50:] if chat_history else [],  # 保留最近50条聊天历史
            long_task_state=long_task_state,  # 长任务状态
            user_requirements=user_requirements,  # 用户需求
            ai_understanding=ai_understanding  # AI理解
        )

        # 缓存快照  # 内存缓存
        self._memory_cache[task_id] = snapshot  # 存入内存缓存

        # 持久化存储  # 磁盘存储
        await asyncio.to_thread(self._persist_snapshot, snapshot)  # 调用持久化方法

        logger.info(f"[StateSnapshot] 任务 {task_id} 状态快照已捕获")  # 记录日志

        return snapshot  # 返回快照对象

    async def restore_snapshot(self, task_id: str) -> TaskStateSnapshot | None:  # 恢复快照方法
        """
        恢复任务状态快照（异步版本）  # 方法文档字符串

        Args:  # 参数说明
            task_id: 任务ID  # 参数1

        Returns:  # 返回值说明
            TaskStateSnapshot: 状态快照，如果不存在返回None

        Raises:
            SnapshotError: 快照存在但加载/解析失败
        """
        # 优先从内存缓存恢复  # 内存恢复优先
        if task_id in self._memory_cache:  # 检查内存缓存
            logger.info(f"[StateSnapshot] 任务 {task_id} 从内存缓存恢复快照")  # 记录日志
            return self._memory_cache[task_id]  # 返回内存中的快照

        # 从持久化存储恢复  # 磁盘恢复
        snapshot = await asyncio.to_thread(self._load_snapshot, task_id)
        if snapshot is not None:
            # 缓存恢复的快照
            self._memory_cache[task_id] = snapshot
        return snapshot

    async def restore_to_working_memory(self, task_id: str, working_memory) -> bool:  # 恢复到工作记忆方法
        """
        将快照恢复到WorkingMemory实例（异步版本）  # 方法文档字符串

        Args:  # 参数说明
            task_id: 任务ID  # 参数1
            working_memory: WorkingMemory实例  # 参数2

        Returns:  # 返回值说明
            bool: 是否成功恢复（快照不存在返回False，加载失败抛出异常）

        Raises:
            SnapshotError: 快照存在但恢复失败
        """
        snapshot = await self.restore_snapshot(task_id)  # 恢复快照
        if not snapshot:  # 如果快照不存在
            logger.warning(f"[StateSnapshot] 无法恢复任务 {task_id}: 快照不存在")  # 记录警告
            return False  # 返回失败

        try:  # 异常处理
            # 恢复WorkingMemory状态  # 恢复工作记忆
            wm_state = snapshot.working_memory_state  # 获取工作记忆状态

            # 恢复关键属性  # 属性恢复
            if 'query_stage' in wm_state:  # 检查查询阶段
                working_memory.query_stage = wm_state['query_stage']  # 恢复查询阶段
            if 'current_category' in wm_state:  # 检查当前分类
                working_memory.current_category = wm_state['current_category']  # 恢复分类
            if 'current_tool' in wm_state:  # 检查当前工具
                working_memory.current_tool = wm_state['current_tool']  # 恢复工具
            if 'ai_plan_id' in wm_state:  # 检查计划ID
                working_memory.ai_plan_id = wm_state['ai_plan_id']  # 恢复计划ID
            if 'tool_results' in wm_state:  # 检查工具结果
                working_memory.tool_results = wm_state['tool_results']  # 恢复工具结果
            if 'layer_switch_count' in wm_state:  # 检查层级切换计数
                working_memory.layer_switch_count = wm_state['layer_switch_count']  # 恢复计数

            # 【修复BUG-6】恢复 _message_history 等核心字段
            if '_message_history' in wm_state:
                working_memory._message_history = wm_state['_message_history']
            if '_compression_stats' in wm_state:
                working_memory._compression_stats = wm_state['_compression_stats']
            if 'just_executed_tool' in wm_state:
                working_memory.just_executed_tool = wm_state['just_executed_tool']
            if 'last_tool_result' in wm_state:
                working_memory.last_tool_result = wm_state['last_tool_result']

            logger.info(f"[StateSnapshot] 任务 {task_id} 已恢复到WorkingMemory")  # 记录日志
            return True  # 返回成功

        except Exception as e:  # 捕获异常
            logger.error(f"[SILENT_FAILURE_BLOCKED] 恢复到WorkingMemory失败: {e}")
            raise SnapshotError(f"无法恢复快照到WorkingMemory: {e}") from e

    def _capture_working_memory(self, working_memory) -> dict[str, Any]:  # 捕获工作记忆（私有方法）
        """捕获WorkingMemory状态"""  # 方法文档字符串
        if working_memory is None:  # 检查是否为None
            return {}  # 返回空字典

        return {  # 返回工作记忆状态字典
            "query_stage": getattr(working_memory, 'query_stage', 'L1_OVERVIEW'),  # 查询阶段
            "current_category": getattr(working_memory, 'current_category', None),  # 当前分类
            "current_tool": getattr(working_memory, 'current_tool', None),  # 当前工具
            "ai_plan_id": getattr(working_memory, 'ai_plan_id', None),  # AI计划ID
            "tool_results": getattr(working_memory, 'tool_results', []),  # 工具结果
            "layer_switch_count": getattr(working_memory, 'layer_switch_count', 0),  # 层级切换计数
            "context": getattr(working_memory, 'context', {}),  # 上下文
            # 【修复BUG-5】补充捕获 _message_history 等核心字段
            "_message_history": getattr(working_memory, '_message_history', []),
            "_compression_stats": getattr(working_memory, '_compression_stats', {}),
            "just_executed_tool": getattr(working_memory, 'just_executed_tool', False),
            "last_tool_result": getattr(working_memory, 'last_tool_result', None),
        }

    def _capture_loop_state(self, loop_state) -> dict[str, Any]:  # 捕获循环状态（私有方法）
        """捕获AgentLoop状态"""  # 方法文档字符串
        if loop_state is None:  # 检查是否为None
            return {'round': 0, 'chat_count': 0, 'execution_history': []}  # 返回默认值

        return {  # 返回循环状态字典
            'round': getattr(loop_state, 'round_count', 0),  # 循环轮次
            'chat_count': getattr(loop_state, 'chat_count', 0),  # 聊天计数
            'execution_history': getattr(loop_state, 'execution_history', []),  # 执行历史
        }

    def _persist_snapshot(self, snapshot: TaskStateSnapshot):  # 持久化快照（私有方法）
        """
        持久化存储快照

        Raises:
            SnapshotError: 保存失败
        """
        filename = f"{self.storage_dir}/snapshot_{snapshot.task_id}_{int(snapshot.timestamp)}.json"
        temp_filename = filename + ".tmp"

        try:  # 异常处理
            # 转换为可序列化的字典  # 数据转换
            data = self._snapshot_to_dict(snapshot)  # 调用转换方法

            # 验证数据完整性
            missing = [f for f in self.REQUIRED_SNAPSHOT_FIELDS if f not in data]
            if missing:
                raise ValueError(f"快照数据缺少必填字段: {missing}")

            # 原子写入
            with open(temp_filename, 'w', encoding='utf-8') as f:  # 打开文件（写入模式）
                json.dump(data, f, ensure_ascii=False, indent=2)  # 写入JSON（带缩进）
                f.flush()
                os.fsync(f.fileno())

            # 重命名
            os.replace(temp_filename, filename)

            # 验证写入成功
            if not os.path.exists(filename):
                raise OSError("文件写入验证失败")

            logger.debug(f"[StateSnapshot] 快照已持久化: {filename}")  # 记录调试日志

        except Exception as e:  # 捕获异常
            logger.error(f"[SILENT_FAILURE_BLOCKED] 快照持久化失败: {e}")
            # 清理临时文件
            if os.path.exists(temp_filename):
                try:
                    os.remove(temp_filename)
                except OSError as e:
                    logger.error(f"[StateSnapshot] 临时文件清理失败: {e}", exc_info=True)
            raise SnapshotError(f"无法持久化快照: {e}") from e

    def _snapshot_to_dict(self, snapshot: TaskStateSnapshot) -> dict[str, Any]:  # 快照转字典（私有方法）
        """将快照转换为可序列化的字典"""  # 方法文档字符串
        def clean_value(v):  # 定义值清理函数（嵌套函数）
            """清理值，使其可JSON序列化"""  # 函数文档字符串
            if v is None:  # 如果为None
                return None  # 直接返回None
            elif isinstance(v, (str, int, float, bool)):  # 如果是基本类型
                return v  # 直接返回
            elif isinstance(v, dict):  # 如果是字典
                return {k: clean_value(val) for k, val in v.items()}  # 递归清理
            elif isinstance(v, list):  # 如果是列表
                return [clean_value(item) for item in v]  # 递归清理每个元素
            elif hasattr(v, '__dict__'):  # 如果是类实例
                # 对于Mock对象或其他类实例，尝试转换为字典  # 类实例处理
                try:  # 异常处理
                    return str(v)  # 转换为字符串
                except Exception:  # 捕获异常
                    return None  # 返回None
            else:  # 其他类型
                try:  # 异常处理
                    # 尝试JSON序列化  # 序列化测试
                    json.dumps(v)  # 尝试序列化
                    return v  # 成功则返回
                except (TypeError, ValueError):  # 序列化失败
                    return str(v)  # 转换为字符串

        return {  # 返回清理后的字典
            "task_id": snapshot.task_id,  # 任务ID
            "timestamp": snapshot.timestamp,  # 时间戳
            "session_id": snapshot.session_id,  # 会话ID
            "user_id": snapshot.user_id,  # 用户ID
            "working_memory_state": clean_value(snapshot.working_memory_state),  # 清理后的工作记忆状态
            "loop_round": snapshot.loop_round,  # 循环轮次
            "chat_count": snapshot.chat_count,  # 聊天计数
            "execution_history": clean_value(snapshot.execution_history),  # 清理后的执行历史
            "chat_history": clean_value(snapshot.chat_history),  # 清理后的聊天历史
            "long_task_state": snapshot.long_task_state,  # 长任务状态
            "user_requirements": clean_value(snapshot.user_requirements) if snapshot.user_requirements else None,  # 用户需求
            "ai_understanding": snapshot.ai_understanding,  # AI理解
        }

    def _load_snapshot(self, task_id: str) -> TaskStateSnapshot | None:  # 加载快照（私有方法）
        """
        从持久化存储加载快照

        Returns:
            TaskStateSnapshot: 状态快照，不存在返回None

        Raises:
            SnapshotError: 快照存在但读取/解析失败
        """
        try:  # 异常处理
            # 查找该任务的最新快照  # 文件查找
            pattern = f"{self.storage_dir}/snapshot_{task_id}_*.json"  # 构建匹配模式
            files = glob.glob(pattern)  # 查找匹配文件

            if not files:  # 如果没有找到文件
                return None  # 返回None（正常情况：状态不存在）

            # 按时间排序，取最新的  # 排序选择
            latest_file = max(files, key=os.path.getmtime)  # 获取最新文件

            with open(latest_file, encoding='utf-8') as f:  # 打开文件（读取模式）
                data = json.load(f)  # 加载JSON

            # 验证数据完整性
            if not isinstance(data, dict):
                raise ValueError(f"快照数据格式错误: 期望dict, 实际{type(data)}")

            missing = [f for f in self.REQUIRED_SNAPSHOT_FIELDS if f not in data]
            if missing:
                raise ValueError(f"快照数据缺少必填字段: {missing}")

            snapshot = TaskStateSnapshot(**data)  # 创建快照对象
            logger.info(f"[StateSnapshot] 任务 {task_id} 从磁盘加载快照: {latest_file}")  # 记录日志
            return snapshot  # 返回快照

        except Exception as e:  # 捕获异常
            logger.error(f"[SILENT_FAILURE_BLOCKED] 加载快照失败 {task_id}: {e}")
            raise SnapshotError(f"无法加载快照 {task_id}: {e}") from e

    def delete_snapshot(self, task_id: str) -> bool:  # 删除快照方法
        """
        删除任务快照  # 方法文档字符串

        Args:  # 参数说明
            task_id: 任务ID  # 参数1

        Returns:  # 返回值说明
            bool: 是否成功删除  # 返回类型
        """
        return self.clear_snapshot(task_id)  # 调用清除方法

    def clear_snapshot(self, task_id: str) -> bool:  # 清除快照方法
        """
        清除任务快照（兼容旧接口）  # 方法文档字符串

        Args:  # 参数说明
            task_id: 任务ID  # 参数1

        Returns:  # 返回值说明
            bool: 是否成功清除  # 返回类型
        """
        success = True  # 初始化成功标志

        # 清除内存缓存  # 内存清除
        if task_id in self._memory_cache:  # 检查内存缓存
            del self._memory_cache[task_id]  # 删除缓存
            logger.debug(f"[StateSnapshot] 任务 {task_id} 内存缓存已清除")  # 记录日志

        # 清除持久化文件  # 文件清除
        try:  # 异常处理
            pattern = f"{self.storage_dir}/snapshot_{task_id}_*.json"  # 构建匹配模式
            files = glob.glob(pattern)  # 查找匹配文件
            for f in files:  # 遍历文件
                os.remove(f)  # 删除文件
                logger.debug(f"[StateSnapshot] 快照文件已删除: {f}")  # 记录日志
        except Exception as e:  # 捕获异常
            logger.error(f"[SILENT_FAILURE_BLOCKED] 清除快照文件失败 {task_id}: {e}")
            success = False  # 设置失败标志

        return success  # 返回结果

    def list_snapshots(self, task_id: str | None = None) -> list[TaskStateSnapshot]:  # 列出快照方法
        """
        列出可用的快照  # 方法文档字符串

        Args:  # 参数说明
            task_id: 可选，指定任务ID  # 参数1

        Returns:  # 返回值说明
            List[TaskStateSnapshot]: 快照列表  # 返回类型
        """
        snapshots = []  # 快照列表

        try:  # 异常处理
            if task_id:  # 如果指定了任务ID
                pattern = f"{self.storage_dir}/snapshot_{task_id}_*.json"  # 构建任务特定模式
            else:  # 未指定任务ID
                pattern = f"{self.storage_dir}/snapshot_*.json"  # 构建通用模式

            files = glob.glob(pattern)  # 查找匹配文件

            for f in files:  # 遍历文件
                try:  # 异常处理
                    with open(f, encoding='utf-8') as file:  # 打开文件
                        data = json.load(file)  # 加载JSON

                    # 验证数据完整性
                    if not isinstance(data, dict):
                        logger.warning(f"[StateSnapshot] 快照文件格式错误 {f}: 期望dict, 实际{type(data)}")
                        continue

                    # 转换为TaskStateSnapshot对象  # 对象转换
                    snapshot = TaskStateSnapshot(**data)  # 创建快照对象
                    snapshots.append(snapshot)  # 添加到列表

                except Exception as e:  # 捕获异常
                    logger.warning(f"[StateSnapshot] 读取快照文件失败 {f}: {e}")  # 记录警告日志

            # 按时间排序（按timestamp属性排序）  # 排序
            snapshots.sort(key=lambda x: getattr(x, 'timestamp', 0), reverse=True)  # 按时间戳降序

        except Exception as e:  # 捕获异常
            logger.error(f"[SILENT_FAILURE_BLOCKED] 列出快照失败: {e}")
            raise SnapshotError(f"无法列出快照: {e}") from e

        return snapshots  # 返回快照列表


# 全局单例  # 全局单例注释
_snapshot_manager: StateSnapshotManager | None = None  # 快照管理器实例

def get_snapshot_manager() -> StateSnapshotManager:  # 获取快照管理器函数
    """获取状态快照管理器单例"""  # 函数文档字符串
    global _snapshot_manager  # 声明全局变量
    if _snapshot_manager is None:  # 检查是否已创建
        _snapshot_manager = StateSnapshotManager()  # 创建实例
    return _snapshot_manager  # 返回实例


async def capture_task_snapshot(task_id: str,  # 捕获任务快照便捷函数
                          working_memory,  # 工作记忆
                          loop_state,  # 循环状态
                          chat_history: list[dict],  # 聊天历史
                          session_id: str,  # 会话ID
                          user_id: str = "default",  # 用户ID
                          long_task_sm=None) -> TaskStateSnapshot:  # 长任务状态机
    """
    便捷函数：捕获任务快照（异步版本）  # 函数文档字符串

    Args:  # 参数说明
        task_id: 任务ID  # 参数1
        working_memory: WorkingMemory实例  # 参数2
        loop_state: LoopState实例  # 参数3
        chat_history: 聊天历史  # 参数4
        session_id: 会话ID  # 参数5
        user_id: 用户ID  # 参数6
        long_task_sm: 长任务状态机（可选）  # 参数7

    Returns:  # 返回值说明
        TaskStateSnapshot: 状态快照  # 返回类型

    Raises:
        SnapshotError: 快照捕获失败
    """
    manager = get_snapshot_manager()  # 获取管理器
    return await manager.capture_snapshot(  # 调用捕获方法
        task_id=task_id,  # 任务ID
        working_memory=working_memory,  # 工作记忆
        loop_state=loop_state,  # 循环状态
        chat_history=chat_history,  # 聊天历史
        session_id=session_id,  # 会话ID
        user_id=user_id,  # 用户ID
        long_task_sm=long_task_sm  # 长任务状态机
    )


async def restore_task_snapshot(task_id: str) -> TaskStateSnapshot | None:  # 恢复任务快照便捷函数
    """
    便捷函数：恢复任务快照（异步版本）  # 函数文档字符串

    Args:  # 参数说明
        task_id: 任务ID  # 参数1

    Returns:  # 返回值说明
        TaskStateSnapshot: 状态快照，如果不存在返回None

    Raises:
        SnapshotError: 快照存在但加载失败
    """
    manager = get_snapshot_manager()  # 获取管理器
    return await manager.restore_snapshot(task_id)  # 调用恢复方法


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"统一状态快照管理器"，负责捕获和恢复任务的完整状态。
# 解决长任务暂停后状态丢失问题，支持任务的断点续传。
#
# 【架构设计】
# - 双存储策略: 内存缓存 + 磁盘持久化
# - 数据类设计: TaskStateSnapshot使用@dataclass定义结构化快照
# - 自动清理: 未实现但预留了list_snapshots()接口用于管理
# - 可序列化: 自动处理复杂对象的JSON序列化
#
# 【关联文件】
# - core/working_memory.py            : 工作记忆类，快照的核心数据源
# - core/pause_confirmation_state_machine.py : 长任务状态机，存储暂停状态
# - core/long_running_manager.py      : 长任务管理器，调用捕获/恢复
# - core/agent_loop.py                : Agent循环，状态变化时触发快照
#
# 【核心功能效果】
# 1. 状态捕获: 捕获WorkingMemory、AgentLoop、长任务状态机的完整状态
# 2. 断点续传: 任务中断后可以从快照恢复，继续执行
# 3. 内存优先: 优先从内存恢复，快速响应
# 4. 持久化备份: 内存缓存同时写入磁盘，防止数据丢失
# 5. 自动序列化: 复杂对象自动转换为JSON可序列化格式
# 6. 多版本支持: 支持列出和选择不同时间点的快照
#
# 【使用场景】
# - 长任务暂停: 用户暂停24小时长任务时捕获完整状态
# - 系统重启: 重启后从磁盘快照恢复未完成任务
# - 容错恢复: 异常中断后恢复任务执行上下文
# =============================================================================
