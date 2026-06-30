#!/usr/bin/env python3
"""
用户数据同步服务 - 跨设备数据同步
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
支持本地/云端/混合三种部署模式，实现记忆、工具、配置等数据的跨设备同步

【功能特性】
  ✓ 多部署模式支持: local(本地) / cloud(云端) / hybrid(混合)
  ✓ 数据类型: memories, user_configs, user_prompts, custom_tools, tasks
  ✓ 离线缓存: 网络中断时本地存储，恢复后自动同步
  ✓ 冲突解决: 支持云端优先/本地优先/时间戳优先等多种策略
  ✓ 增量同步: 只同步变更数据，减少网络传输

【部署模式】
  • local:  只存本地，尝试同步到云端（如果有账号）
  • cloud:  云端是数据源，同步到本地缓存
  • hybrid: 双向同步，冲突时云端优先（默认）

作者: SiliconBase Team
版本: 1.0.0
"""

import asyncio
import hashlib
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.diagnostic import safe_create_task

# 条件导入 aiohttp
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    aiohttp = None

# 类型检查时才导入 aiohttp 类型
if TYPE_CHECKING:
    import aiohttp

import contextlib

from core.config import config
from core.logger import logger

# ═══════════════════════════════════════════════════════════════════
# 数据模型定义
# ═══════════════════════════════════════════════════════════════════

class SyncStatus(Enum):
    """同步状态枚举"""
    PENDING = "pending"           # 等待同步
    SYNCING = "syncing"           # 同步中
    SUCCESS = "success"           # 同步成功
    FAILED = "failed"             # 同步失败
    CONFLICT = "conflict"         # 冲突待解决
    OFFLINE = "offline"           # 离线状态


class ConflictResolution(Enum):
    """冲突解决策略"""
    CLOUD_FIRST = "cloud_first"       # 云端优先
    LOCAL_FIRST = "local_first"       # 本地优先
    TIMESTAMP_FIRST = "timestamp_first"  # 时间戳优先
    MERGE = "merge"                   # 合并数据


@dataclass
class SyncItem:
    """同步队列项"""
    user_id: str
    data_type: str                    # memories/user_configs/user_prompts/custom_tools/tasks
    operation: str                    # push/pull/merge
    priority: int = 0                 # 优先级，数字越大越优先
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime = field(default_factory=datetime.now)
    last_attempt: datetime | None = None
    status: SyncStatus = SyncStatus.PENDING
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "user_id": self.user_id,
            "data_type": self.data_type,
            "operation": self.operation,
            "priority": self.priority,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "created_at": self.created_at.isoformat(),
            "last_attempt": self.last_attempt.isoformat() if self.last_attempt else None,
            "status": self.status.value,
            "error_message": self.error_message
        }


@dataclass
class SyncRecord:
    """同步记录"""
    record_id: str
    user_id: str
    data_type: str
    local_checksum: str
    cloud_checksum: str
    local_modified_at: datetime
    cloud_modified_at: datetime
    last_sync_at: datetime | None = None
    conflict_resolved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "user_id": self.user_id,
            "data_type": self.data_type,
            "local_checksum": self.local_checksum,
            "cloud_checksum": self.cloud_checksum,
            "local_modified_at": self.local_modified_at.isoformat(),
            "cloud_modified_at": self.cloud_modified_at.isoformat(),
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "conflict_resolved": self.conflict_resolved
        }


# ═══════════════════════════════════════════════════════════════════
# 本地存储适配器
# ═══════════════════════════════════════════════════════════════════

class LocalStorageAdapter:
    """本地存储适配器 - 封装PostgreSQL和本地文件存储"""

    def __init__(self):
        self._cache_dir = Path(__file__).parent.parent / "data" / "sync_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._sync_records_file = self._cache_dir / "sync_records.json"
        self._offline_queue_file = self._cache_dir / "offline_queue.json"
        self._lock = threading.RLock()

    # ─────────────────────────────────────────────────────────────
    # 数据获取方法
    # ─────────────────────────────────────────────────────────────

    async def get_memories(self, user_id: str, since: datetime | None = None) -> list[dict[str, Any]]:
        """获取用户记忆数据"""
        try:
            from core.memory.memory_manager import MemoryManager
            mm = MemoryManager()
            store = mm.get_user_store(user_id)

            # 获取所有层级的记忆
            all_memories = []
            for layer in ["short", "mid", "long", "evolve"]:
                memories = store.query(layer=layer, limit=1000)
                for mem in memories:
                    mem_dict = dict(mem) if hasattr(mem, 'items') else mem
                    if since and mem_dict.get('created_at'):
                        try:
                            mem_time = datetime.fromisoformat(str(mem_dict['created_at']))
                            if mem_time < since:
                                continue
                        except (ValueError, TypeError) as e:
                            # 时间解析异常 - 记录并继续处理
                            logger.error(f"[SILENT_FAILURE_BLOCKED] 时间解析失败 '{mem_dict.get('created_at')}': {e}")
                    all_memories.append(mem_dict)

            return all_memories
        except Exception as e:
            logger.error(f"[LocalStorage] 获取记忆失败: {e}")
            return []

    async def get_user_configs(self, user_id: str) -> dict[str, Any]:
        """获取用户配置"""
        try:
            return config.get_user_all_configs(user_id)
        except Exception as e:
            logger.error(f"[LocalStorage] 获取用户配置失败: {e}")
            return {}

    async def get_user_prompts(self, user_id: str) -> dict[str, str]:
        """获取用户提示词配置"""
        try:
            result = {}
            # 获取用户所有模块的提示词
            module_ids = ["identity", "personality", "world_view", "response_style",
                         "thinking_pattern", "emotion_expression", "value_judgment"]
            for module_id in module_ids:
                content = config.get_user_prompt_module(user_id, module_id)
                if content:
                    result[module_id] = content
            return result
        except Exception as e:
            logger.error(f"[LocalStorage] 获取用户提示词失败: {e}")
            return {}

    async def get_custom_tools(self, user_id: str) -> list[dict[str, Any]]:
        """获取用户自定义工具"""
        try:
            from core.tool.tool_manager import tool_manager
            tools = tool_manager.get_user_tools(user_id)
            return [tool.to_dict() if hasattr(tool, 'to_dict') else tool for tool in tools]
        except Exception as e:
            logger.error(f"[LocalStorage] 获取自定义工具失败: {e}")
            return []

    async def get_tasks(self, user_id: str) -> list[dict[str, Any]]:
        """获取用户任务数据"""
        try:
            from core.task.user_task_store import user_task_store
            tasks = user_task_store.get_user_tasks(user_id)
            return [task.to_dict() if hasattr(task, 'to_dict') else task for task in tasks]
        except Exception as e:
            logger.error(f"[LocalStorage] 获取任务失败: {e}")
            return []

    # ─────────────────────────────────────────────────────────────
    # 数据保存方法
    # ─────────────────────────────────────────────────────────────

    async def save_memories(self, user_id: str, memories: list[dict[str, Any]]) -> bool:
        """保存记忆数据到本地"""
        try:
            from core.memory.memory_manager import MemoryManager
            mm = MemoryManager()
            store = mm.get_user_store(user_id)

            for mem in memories:
                memory_id = mem.get('memory_id') or mem.get('id')
                if memory_id:
                    # 更新或添加记忆
                    store.update(memory_id, mem)
                else:
                    # 新增记忆
                    mm.add(
                        user_id=user_id,
                        layer=mem.get('layer', 'short'),
                        content=mem.get('content', {}),
                        mem_type=mem.get('mem_type', 'chat'),
                        scene=mem.get('scene', '')
                    )
            return True
        except Exception as e:
            logger.error(f"[LocalStorage] 保存记忆失败: {e}")
            return False

    async def save_user_configs(self, user_id: str, configs: dict[str, Any]) -> bool:
        """保存用户配置"""
        try:
            for key, value in configs.items():
                config.set_user_config(user_id, key, value)
            return True
        except Exception as e:
            logger.error(f"[LocalStorage] 保存用户配置失败: {e}")
            return False

    async def save_user_prompts(self, user_id: str, prompts: dict[str, str]) -> bool:
        """保存用户提示词"""
        try:
            for module_id, content in prompts.items():
                config.set_user_prompt_module(user_id, module_id, content)
            return True
        except Exception as e:
            logger.error(f"[LocalStorage] 保存用户提示词失败: {e}")
            return False

    async def save_custom_tools(self, user_id: str, tools: list[dict[str, Any]]) -> bool:
        """保存自定义工具"""
        try:
            from core.tool.tool_manager import tool_manager
            for tool in tools:
                tool_manager.register_user_tool(user_id, tool)
            return True
        except Exception as e:
            logger.error(f"[LocalStorage] 保存自定义工具失败: {e}")
            return False

    async def save_tasks(self, user_id: str, tasks: list[dict[str, Any]]) -> bool:
        """保存任务数据"""
        try:
            from core.task.user_task_store import user_task_store
            for task in tasks:
                user_task_store.save_task(user_id, task)
            return True
        except Exception as e:
            logger.error(f"[LocalStorage] 保存任务失败: {e}")
            return False

    # ─────────────────────────────────────────────────────────────
    # 同步记录管理
    # ─────────────────────────────────────────────────────────────

    def get_sync_records(self, user_id: str | None = None) -> dict[str, SyncRecord]:
        """获取同步记录"""
        with self._lock:
            if not self._sync_records_file.exists():
                return {}

            try:
                with open(self._sync_records_file, encoding='utf-8') as f:
                    data = json.load(f)

                records = {}
                for key, value in data.items():
                    if user_id and not key.startswith(f"{user_id}:"):
                        continue
                    records[key] = SyncRecord(
                        record_id=value['record_id'],
                        user_id=value['user_id'],
                        data_type=value['data_type'],
                        local_checksum=value['local_checksum'],
                        cloud_checksum=value['cloud_checksum'],
                        local_modified_at=datetime.fromisoformat(value['local_modified_at']),
                        cloud_modified_at=datetime.fromisoformat(value['cloud_modified_at']),
                        last_sync_at=datetime.fromisoformat(value['last_sync_at']) if value.get('last_sync_at') else None,
                        conflict_resolved=value.get('conflict_resolved', False)
                    )
                return records
            except Exception as e:
                logger.error(f"[LocalStorage] 读取同步记录失败: {e}")
                return {}

    def save_sync_record(self, record: SyncRecord) -> bool:
        """保存同步记录"""
        with self._lock:
            try:
                records = self.get_sync_records()
                key = f"{record.user_id}:{record.data_type}"
                records[key] = record

                # 转换为可序列化的格式
                data = {k: v.to_dict() for k, v in records.items()}

                with open(self._sync_records_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return True
            except Exception as e:
                logger.error(f"[LocalStorage] 保存同步记录失败: {e}")
                return False

    # ─────────────────────────────────────────────────────────────
    # 离线队列管理
    # ─────────────────────────────────────────────────────────────

    def get_offline_queue(self) -> list[SyncItem]:
        """获取离线同步队列"""
        with self._lock:
            if not self._offline_queue_file.exists():
                return []

            try:
                with open(self._offline_queue_file, encoding='utf-8') as f:
                    data = json.load(f)

                items = []
                for item_data in data:
                    items.append(SyncItem(
                        user_id=item_data['user_id'],
                        data_type=item_data['data_type'],
                        operation=item_data['operation'],
                        priority=item_data.get('priority', 0),
                        retry_count=item_data.get('retry_count', 0),
                        max_retries=item_data.get('max_retries', 3),
                        created_at=datetime.fromisoformat(item_data['created_at']),
                        last_attempt=datetime.fromisoformat(item_data['last_attempt']) if item_data.get('last_attempt') else None,
                        status=SyncStatus(item_data['status']),
                        error_message=item_data.get('error_message')
                    ))
                return items
            except Exception as e:
                logger.error(f"[LocalStorage] 读取离线队列失败: {e}")
                return []

    def save_offline_queue(self, queue: list[SyncItem]) -> bool:
        """保存离线同步队列"""
        with self._lock:
            try:
                data = [item.to_dict() for item in queue]
                with open(self._offline_queue_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return True
            except Exception as e:
                logger.error(f"[LocalStorage] 保存离线队列失败: {e}")
                return False

    def add_to_offline_queue(self, item: SyncItem) -> bool:
        """添加项目到离线队列"""
        queue = self.get_offline_queue()
        queue.append(item)
        return self.save_offline_queue(queue)

    def clear_offline_queue(self) -> bool:
        """清空离线队列"""
        return self.save_offline_queue([])

    # ─────────────────────────────────────────────────────────────
    # 辅助方法
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def compute_checksum(data: Any) -> str:
        """计算数据校验和"""
        json_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(json_str.encode()).hexdigest()


# ═══════════════════════════════════════════════════════════════════
# 云端API客户端
# ═══════════════════════════════════════════════════════════════════

class CloudSyncAPI:
    """云端同步API客户端"""

    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        if not AIOHTTP_AVAILABLE:
            raise RuntimeError("aiohttp 模块不可用，无法使用 CloudSyncAPI")
        self.base_url = base_url or config.get("sync.cloud_api_url", "https://api.siliconbase.cloud")
        self.api_key = api_key or config.get("sync.api_key", "")
        self.timeout = aiohttp.ClientTimeout(total=30)
        self._session: Any | None = None
        self._lock = asyncio.Lock()

    async def _get_session(self) -> Any:
        """获取或创建HTTP会话"""
        async with self._lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(
                    timeout=self.timeout,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
                )
            return self._session

    async def close(self):
        """关闭HTTP会话"""
        async with self._lock:
            if self._session and not self._session.closed:
                await self._session.close()
                self._session = None

    async def check_connection(self) -> bool:
        """检查云端连接状态"""
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/api/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                return resp.status == 200
        except Exception as e:
            logger.debug(f"[CloudAPI] 连接检查失败: {e}")
            return False

    async def pull(self, user_id: str, data_type: str, last_sync: datetime | None = None) -> dict[str, Any]:
        """从云端拉取数据"""
        try:
            session = await self._get_session()
            params = {"user_id": user_id, "data_type": data_type}
            if last_sync:
                params["last_sync"] = last_sync.isoformat()

            async with session.get(f"{self.base_url}/api/sync/{user_id}/pull", params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 404:
                    return {"data": None, "message": "No data found"}
                else:
                    text = await resp.text()
                    raise Exception(f"云端拉取失败: {resp.status} - {text}")
        except Exception as e:
            logger.error(f"[CloudAPI] 拉取数据失败: {e}")
            raise

    async def push(self, user_id: str, data_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """推送数据到云端"""
        try:
            session = await self._get_session()
            payload = {
                "user_id": user_id,
                "data_type": data_type,
                "data": data,
                "timestamp": datetime.now().isoformat()
            }

            async with session.post(f"{self.base_url}/api/sync/{user_id}/push", json=payload) as resp:
                if resp.status in [200, 201]:
                    return await resp.json()
                else:
                    text = await resp.text()
                    raise Exception(f"云端推送失败: {resp.status} - {text}")
        except Exception as e:
            logger.error(f"[CloudAPI] 推送数据失败: {e}")
            raise

    async def get_sync_status(self, user_id: str) -> dict[str, Any]:
        """获取云端同步状态"""
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/api/sync/{user_id}/status") as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    return {"error": f"获取状态失败: {resp.status}"}
        except Exception as e:
            logger.error(f"[CloudAPI] 获取同步状态失败: {e}")
            return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════
# 同步服务核心类
# ═══════════════════════════════════════════════════════════════════

class SyncService:
    """
    用户数据同步服务

    实现跨设备数据同步的核心逻辑，支持多种部署模式和冲突解决策略。
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 部署模式
        self.deploy_mode = config.get_deploy_mode()

        # 存储适配器
        self.local_db = LocalStorageAdapter()
        self.cloud_api: CloudSyncAPI | None = None

        # 同步队列
        self._sync_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._offline_queue: list[SyncItem] = []

        # 状态管理
        self._is_online = True
        self._is_running = False
        self._sync_task: asyncio.Task | None = None

        # 事件监听
        self._change_listeners: list[Callable] = []

        # 初始化云端API（如果需要）
        if self.deploy_mode in ["cloud", "hybrid"]:
            self.cloud_api = CloudSyncAPI()

        # 加载离线队列
        self._offline_queue = self.local_db.get_offline_queue()

        logger.info(f"[SyncService] 初始化完成，部署模式: {self.deploy_mode}")

    async def start(self):
        """启动同步服务"""
        if self._is_running:
            return

        self._is_running = True
        self._sync_task = safe_create_task(self._sync_worker(), name="_sync_worker")

        # 启动网络监控
        safe_create_task(self._network_monitor(), name="_network_monitor")

        logger.info("[SyncService] 同步服务已启动")

    async def stop(self):
        """停止同步服务"""
        self._is_running = False

        if self._sync_task:
            self._sync_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sync_task

        if self.cloud_api:
            await self.cloud_api.close()

        # 保存离线队列
        self.local_db.save_offline_queue(self._offline_queue)

        logger.info("[SyncService] 同步服务已停止")

    # ─────────────────────────────────────────────────────────────
    # 公共API方法
    # ─────────────────────────────────────────────────────────────

    async def sync_user_data(self, user_id: str, data_type: str, priority: int = 0) -> dict[str, Any]:
        """
        同步用户数据

        Args:
            user_id: 用户ID
            data_type: 数据类型 (memories/user_configs/user_prompts/custom_tools/tasks)
            priority: 同步优先级，数字越大越优先

        Returns:
            同步结果
        """
        # 根据部署模式选择同步策略
        if self.deploy_mode == "local":
            return await self._local_only_sync(user_id, data_type)
        elif self.deploy_mode == "cloud":
            return await self._cloud_to_local_sync(user_id, data_type)
        else:  # hybrid
            return await self._bidirectional_sync(user_id, data_type)

    async def sync_all(self, user_id: str) -> dict[str, Any]:
        """
        同步用户所有数据类型

        Args:
            user_id: 用户ID

        Returns:
            同步结果汇总
        """
        data_types = ["memories", "user_configs", "user_prompts", "custom_tools", "tasks"]
        results = {}

        for data_type in data_types:
            try:
                result = await self.sync_user_data(user_id, data_type)
                results[data_type] = result
            except Exception as e:
                results[data_type] = {"success": False, "error": str(e)}

        return {
            "success": all(r.get("success", False) for r in results.values()),
            "results": results
        }

    async def queue_sync(self, user_id: str, data_type: str, operation: str = "push", priority: int = 0):
        """
        将同步任务加入队列

        Args:
            user_id: 用户ID
            data_type: 数据类型
            operation: 操作类型 (push/pull/merge)
            priority: 优先级
        """
        item = SyncItem(
            user_id=user_id,
            data_type=data_type,
            operation=operation,
            priority=priority
        )

        if self._is_online:
            await self._sync_queue.put((-priority, item))  # 优先级高的在前
        else:
            # 离线状态，保存到离线队列
            self._offline_queue.append(item)
            self.local_db.add_to_offline_queue(item)
            logger.info(f"[SyncService] 任务已加入离线队列: {data_type}")

    async def sync_on_reconnect(self) -> dict[str, Any]:
        """
        网络恢复后自动同步离线队列

        Returns:
            同步结果
        """
        if not self._offline_queue:
            return {"success": True, "message": "无离线任务", "synced": 0}

        logger.info(f"[SyncService] 开始处理离线队列，共 {len(self._offline_queue)} 个任务")

        synced = 0
        failed = 0

        # 复制队列并清空
        queue_copy = self._offline_queue.copy()
        self._offline_queue = []
        self.local_db.clear_offline_queue()

        for item in queue_copy:
            try:
                result = await self.sync_user_data(item.user_id, item.data_type)
                if result.get("success"):
                    synced += 1
                else:
                    failed += 1
                    # 重新加入队列（如果重试次数未超限）
                    if item.retry_count < item.max_retries:
                        item.retry_count += 1
                        self._offline_queue.append(item)
            except Exception as e:
                logger.error(f"[SyncService] 离线任务同步失败: {e}")
                failed += 1

        # 保存未完成的任务
        if self._offline_queue:
            self.local_db.save_offline_queue(self._offline_queue)

        return {
            "success": failed == 0,
            "synced": synced,
            "failed": failed,
            "pending": len(self._offline_queue)
        }

    async def get_sync_status(self, user_id: str) -> dict[str, Any]:
        """获取同步状态"""
        records = self.local_db.get_sync_records(user_id)

        return {
            "deploy_mode": self.deploy_mode,
            "is_online": self._is_online,
            "pending_count": self._sync_queue.qsize() + len(self._offline_queue),
            "last_sync_records": {k: v.to_dict() for k, v in list(records.items())[:10]}
        }

    def add_change_listener(self, callback: Callable):
        """添加数据变更监听器"""
        self._change_listeners.append(callback)

    # ─────────────────────────────────────────────────────────────
    # 同步策略实现
    # ─────────────────────────────────────────────────────────────

    async def _local_only_sync(self, user_id: str, data_type: str) -> dict[str, Any]:
        """
        本地模式同步

        只操作本地数据，如果云端可用则尝试同步（需要用户绑定云端账号）
        """
        logger.debug(f"[SyncService] 本地模式同步: {data_type}")

        # 获取本地数据
        local_data = await self._get_local_data(user_id, data_type)

        # 如果云端可用，尝试推送（异步，不阻塞）
        if self.cloud_api and await self.cloud_api.check_connection():
            safe_create_task(self._try_cloud_push(user_id, data_type, local_data), name="_try_cloud_push")

        return {
            "success": True,
            "mode": "local",
            "data_type": data_type,
            "local_count": len(local_data) if isinstance(local_data, list) else 1,
            "cloud_sync": "async"
        }

    async def _cloud_to_local_sync(self, user_id: str, data_type: str) -> dict[str, Any]:
        """
        云端模式同步

        云端是数据源，同步到本地缓存
        """
        if not self.cloud_api:
            return {"success": False, "error": "云端API未配置"}

        logger.debug(f"[SyncService] 云端模式同步: {data_type}")

        # 获取同步记录
        record_key = f"{user_id}:{data_type}"
        records = self.local_db.get_sync_records(user_id)
        record = records.get(record_key)

        last_sync = record.last_sync_at if record else None

        # 从云端拉取
        cloud_result = await self.cloud_api.pull(user_id, data_type, last_sync)
        cloud_data = cloud_result.get("data")

        if cloud_data is None:
            return {"success": True, "message": "云端无数据", "changes": 0}

        # 保存到本地
        await self._save_local_data(user_id, data_type, cloud_data)

        # 更新同步记录
        new_record = SyncRecord(
            record_id=record_key,
            user_id=user_id,
            data_type=data_type,
            local_checksum=self.local_db.compute_checksum(cloud_data),
            cloud_checksum=cloud_result.get("checksum", ""),
            local_modified_at=datetime.now(),
            cloud_modified_at=datetime.fromisoformat(cloud_result.get("timestamp", datetime.now().isoformat())),
            last_sync_at=datetime.now()
        )
        self.local_db.save_sync_record(new_record)

        return {
            "success": True,
            "mode": "cloud",
            "data_type": data_type,
            "changes": len(cloud_data) if isinstance(cloud_data, list) else 1
        }

    async def _bidirectional_sync(self, user_id: str, data_type: str,
                                   conflict_resolution: ConflictResolution = ConflictResolution.CLOUD_FIRST) -> dict[str, Any]:
        """
        双向同步（混合模式）

        合并云端和本地数据，根据冲突解决策略处理冲突
        """
        if not self.cloud_api:
            return await self._local_only_sync(user_id, data_type)

        logger.debug(f"[SyncService] 双向同步: {data_type}")

        try:
            # 1. 获取云端数据
            cloud_result = await self.cloud_api.pull(user_id, data_type)
            cloud_data = cloud_result.get("data", {})

            # 2. 获取本地数据
            local_data = await self._get_local_data(user_id, data_type)

            # 3. 合并数据
            merged, conflicts = self._merge_data(
                cloud_data,
                local_data,
                conflict_resolution=conflict_resolution
            )

            # 4. 保存到本地
            await self._save_local_data(user_id, data_type, merged)

            # 5. 推送变更到云端
            await self.cloud_api.push(user_id, data_type, merged)

            # 6. 更新同步记录
            record_key = f"{user_id}:{data_type}"
            new_record = SyncRecord(
                record_id=record_key,
                user_id=user_id,
                data_type=data_type,
                local_checksum=self.local_db.compute_checksum(merged),
                cloud_checksum=self.local_db.compute_checksum(merged),
                local_modified_at=datetime.now(),
                cloud_modified_at=datetime.now(),
                last_sync_at=datetime.now(),
                conflict_resolved=len(conflicts) > 0
            )
            self.local_db.save_sync_record(new_record)

            # 7. 通知监听器
            if conflicts:
                self._notify_change("conflict_resolved", {
                    "user_id": user_id,
                    "data_type": data_type,
                    "conflicts": conflicts
                })

            return {
                "success": True,
                "mode": "hybrid",
                "data_type": data_type,
                "conflicts": len(conflicts),
                "conflict_resolution": conflict_resolution.value
            }

        except Exception as e:
            logger.error(f"[SyncService] 双向同步失败: {e}")
            # 失败时加入离线队列
            await self.queue_sync(user_id, data_type, priority=1)
            return {"success": False, "error": str(e)}

    # ─────────────────────────────────────────────────────────────
    # 数据操作方法
    # ─────────────────────────────────────────────────────────────

    async def _get_local_data(self, user_id: str, data_type: str) -> Any:
        """获取本地数据"""
        getters = {
            "memories": self.local_db.get_memories,
            "user_configs": self.local_db.get_user_configs,
            "user_prompts": self.local_db.get_user_prompts,
            "custom_tools": self.local_db.get_custom_tools,
            "tasks": self.local_db.get_tasks
        }

        getter = getters.get(data_type)
        if not getter:
            raise ValueError(f"未知的数据类型: {data_type}")

        return await getter(user_id)

    async def _save_local_data(self, user_id: str, data_type: str, data: Any) -> bool:
        """保存数据到本地"""
        savers = {
            "memories": self.local_db.save_memories,
            "user_configs": self.local_db.save_user_configs,
            "user_prompts": self.local_db.save_user_prompts,
            "custom_tools": self.local_db.save_custom_tools,
            "tasks": self.local_db.save_tasks
        }

        saver = savers.get(data_type)
        if not saver:
            raise ValueError(f"未知的数据类型: {data_type}")

        return await saver(user_id, data)

    async def _try_cloud_push(self, user_id: str, data_type: str, data: Any):
        """尝试异步推送到云端"""
        try:
            if self.cloud_api and await self.cloud_api.check_connection():
                await self.cloud_api.push(user_id, data_type, data)
                logger.debug(f"[SyncService] 异步云端推送成功: {data_type}")
        except Exception as e:
            logger.debug(f"[SyncService] 异步云端推送失败: {e}")

    def _merge_data(self, cloud_data: Any, local_data: Any,
                    conflict_resolution: ConflictResolution) -> tuple[Any, list[dict]]:
        """
        合并云端和本地数据

        Returns:
            (合并后的数据, 冲突列表)
        """
        conflicts = []

        # 处理列表类型数据（如memories, tasks, custom_tools）
        if isinstance(cloud_data, list) and isinstance(local_data, list):
            return self._merge_lists(cloud_data, local_data, conflict_resolution)

        # 处理字典类型数据（如user_configs, user_prompts）
        if isinstance(cloud_data, dict) and isinstance(local_data, dict):
            return self._merge_dicts(cloud_data, local_data, conflict_resolution)

        # 单一值，根据冲突策略选择
        if cloud_data == local_data:
            return cloud_data, conflicts

        # 存在冲突
        conflicts.append({
            "cloud": cloud_data,
            "local": local_data
        })

        if conflict_resolution == ConflictResolution.CLOUD_FIRST:
            return cloud_data, conflicts
        elif conflict_resolution == ConflictResolution.LOCAL_FIRST:
            return local_data, conflicts
        elif conflict_resolution == ConflictResolution.MERGE:
            # 对于不可合并的类型，默认使用云端
            return cloud_data, conflicts
        else:
            return cloud_data, conflicts

    def _merge_lists(self, cloud_list: list[dict], local_list: list[dict],
                     conflict_resolution: ConflictResolution) -> tuple[list[dict], list[dict]]:
        """合并列表数据（基于ID去重）"""
        conflicts = []

        # 创建ID索引
        cloud_map = {self._get_item_id(item): item for item in cloud_list}
        local_map = {self._get_item_id(item): item for item in local_list}

        # 合并
        merged = []
        all_ids = set(cloud_map.keys()) | set(local_map.keys())

        for item_id in all_ids:
            cloud_item = cloud_map.get(item_id)
            local_item = local_map.get(item_id)

            if cloud_item and local_item:
                # 存在冲突，需要合并
                if cloud_item == local_item:
                    merged.append(cloud_item)
                else:
                    conflicts.append({
                        "id": item_id,
                        "cloud": cloud_item,
                        "local": local_item
                    })
                    # 根据策略选择
                    if conflict_resolution == ConflictResolution.CLOUD_FIRST:
                        merged.append(cloud_item)
                    elif conflict_resolution == ConflictResolution.LOCAL_FIRST:
                        merged.append(local_item)
                    elif conflict_resolution == ConflictResolution.TIMESTAMP_FIRST:
                        # 比较时间戳
                        cloud_time = self._get_item_timestamp(cloud_item)
                        local_time = self._get_item_timestamp(local_item)
                        merged.append(cloud_item if cloud_time >= local_time else local_item)
                    else:
                        merged.append(cloud_item)
            elif cloud_item:
                merged.append(cloud_item)
            else:
                merged.append(local_item)

        return merged, conflicts

    def _merge_dicts(self, cloud_dict: dict, local_dict: dict,
                     conflict_resolution: ConflictResolution) -> tuple[dict, list[dict]]:
        """合并字典数据"""
        conflicts = []
        merged = {}

        all_keys = set(cloud_dict.keys()) | set(local_dict.keys())

        for key in all_keys:
            cloud_val = cloud_dict.get(key)
            local_val = local_dict.get(key)

            if cloud_val == local_val:
                merged[key] = cloud_val
            elif cloud_val is None:
                merged[key] = local_val
            elif local_val is None:
                merged[key] = cloud_val
            else:
                # 冲突
                conflicts.append({
                    "key": key,
                    "cloud": cloud_val,
                    "local": local_val
                })

                if conflict_resolution == ConflictResolution.CLOUD_FIRST:
                    merged[key] = cloud_val
                elif conflict_resolution == ConflictResolution.LOCAL_FIRST:
                    merged[key] = local_val
                else:
                    merged[key] = cloud_val

        return merged, conflicts

    def _get_item_id(self, item: dict) -> str:
        """获取项目的唯一标识"""
        if not isinstance(item, dict):
            return str(hash(str(item)))

        for key in ['id', 'memory_id', 'task_id', 'tool_id', 'name']:
            if key in item:
                return str(item[key])

        return str(hash(json.dumps(item, sort_keys=True)))

    def _get_item_timestamp(self, item: dict) -> datetime:
        """获取项目的时间戳"""
        if not isinstance(item, dict):
            return datetime.min

        for key in ['updated_at', 'modified_at', 'created_at', 'timestamp']:
            if key in item and item[key]:
                try:
                    return datetime.fromisoformat(str(item[key]).replace('Z', '+00:00'))
                except (ValueError, TypeError) as e:
                    # 时间解析异常 - 记录并继续处理
                    logger.error(f"[SILENT_FAILURE_BLOCKED] 时间戳解析失败 '{item[key]}': {e}")

        return datetime.min

    # ─────────────────────────────────────────────────────────────
    # 后台任务
    # ─────────────────────────────────────────────────────────────

    async def _sync_worker(self):
        """同步工作线程"""
        while self._is_running:
            try:
                # 获取队列中的任务
                priority, item = await asyncio.wait_for(
                    self._sync_queue.get(),
                    timeout=5.0
                )

                # 执行同步
                await self.sync_user_data(item.user_id, item.data_type)

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"[SyncService] 同步工作线程异常: {e}")

    async def _network_monitor(self):
        """网络状态监控"""
        last_state = True

        while self._is_running:
            try:
                if self.cloud_api:
                    current_state = await self.cloud_api.check_connection()

                    # 网络恢复
                    if not last_state and current_state:
                        logger.info("[SyncService] 网络已恢复，开始同步离线数据")
                        await self.sync_on_reconnect()

                    # 网络断开
                    if last_state and not current_state:
                        logger.warning("[SyncService] 网络已断开，切换到离线模式")

                    self._is_online = current_state
                    last_state = current_state

                await asyncio.sleep(30)  # 每30秒检查一次

            except Exception as e:
                logger.error(f"[SyncService] 网络监控异常: {e}")
                await asyncio.sleep(60)

    def _notify_change(self, event_type: str, data: dict):
        """通知数据变更"""
        for listener in self._change_listeners:
            try:
                if asyncio.iscoroutinefunction(listener):
                    safe_create_task(listener(event_type, data), name="listener")
                else:
                    listener(event_type, data)
            except Exception as e:
                logger.error(f"[SyncService] 通知监听器失败: {e}")


# ═══════════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════════

_sync_service: SyncService | None = None


def get_sync_service() -> SyncService:
    """获取同步服务单例"""
    global _sync_service
    if _sync_service is None:
        _sync_service = SyncService()
    return _sync_service


async def init_sync_service() -> SyncService:
    """初始化并启动同步服务"""
    service = get_sync_service()
    await service.start()
    return service


async def stop_sync_service():
    """停止同步服务"""
    global _sync_service
    if _sync_service:
        await _sync_service.stop()
        _sync_service = None
