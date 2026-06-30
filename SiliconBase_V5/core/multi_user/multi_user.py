#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
多用户支持模块 - SiliconBase V5  # 模块功能概述：多用户支持
实现用户会话隔离、独立记忆空间、用户偏好管理  # 核心功能描述
"""  # 文档字符串结束

import hashlib  # 导入哈希模块，用于生成摘要
import json  # 导入JSON模块，用于数据序列化
import threading  # 导入线程模块，用于线程安全锁
import time  # 导入时间模块，用于时间戳操作
import uuid  # 导入UUID模块，用于生成唯一标识符
from dataclasses import dataclass  # 导入数据类相关装饰器和函数
from pathlib import Path  # 导入路径处理模块

from core.logger import logger  # 导入全局日志记录器


@dataclass  # 数据类装饰器，自动生成初始化等方法
class UserSession:  # 定义用户会话数据类
    """用户会话"""  # 类文档字符串
    session_id: str  # 会话唯一标识符
    user_id: str  # 用户唯一标识符
    created_at: float  # 会话创建时间戳
    last_active: float  # 最后活跃时间戳
    preferences: dict  # 用户偏好设置字典
    context: dict  # 会话上下文数据字典


class UserMemoryStore:  # 用户专属记忆存储类
    """用户专属记忆存储"""  # 类文档字符串

    def __init__(self, user_id: str):  # 初始化方法，接收用户ID参数
        self.user_id = user_id  # 保存用户ID
        self.namespace = f"user_{user_id}"  # 为用户创建独立的命名空间
        self._memories: list[dict] = []  # 初始化记忆列表
        self._lock = threading.RLock()  # 创建可重入锁，保证线程安全

        # 数据持久化路径  # 注释：设置数据存储路径
        self.data_dir = Path("data/user_memories")  # 设置数据目录路径
        self.data_dir.mkdir(parents=True, exist_ok=True)  # 递归创建目录，如已存在则不报错
        self._file_path = self.data_dir / f"{user_id}.json"  # 设置用户记忆文件路径

        # 加载已有数据  # 注释：从文件加载已有记忆
        self._load()  # 调用加载方法

    def _load(self):  # 私有方法：从文件加载记忆
        """从文件加载记忆"""  # 方法文档字符串
        if self._file_path.exists():  # 检查文件是否存在
            try:  # 异常处理开始
                with open(self._file_path, encoding='utf-8') as f:  # 以UTF-8编码打开文件
                    self._memories = json.load(f)  # 解析JSON数据到记忆列表
            except Exception as e:  # 捕获异常
                logger.error(f"加载用户记忆失败 {self.user_id}: {e}")  # 记录错误日志
                self._memories = []  # 出错时初始化为空列表

    def _save(self):  # 私有方法：保存记忆到文件
        """保存记忆到文件"""  # 方法文档字符串
        try:  # 异常处理开始
            with open(self._file_path, 'w', encoding='utf-8') as f:  # 以UTF-8编码打开文件写入
                json.dump(self._memories, f, ensure_ascii=False, indent=2)  # 保存为格式化JSON
        except Exception as e:  # 捕获异常
            logger.error(f"保存用户记忆失败 {self.user_id}: {e}")  # 记录错误日志

    def add(self, content: str, mem_type: str = "general", metadata: dict = None):  # 添加记忆方法
        """添加记忆"""  # 方法文档字符串
        with self._lock:  # 获取锁，保证线程安全
            memory_entry = {  # 创建记忆条目字典
                'id': hashlib.md5(f"{content}{time.time()}".encode()).hexdigest()[:16],  # 生成唯一ID
                'content': content,  # 记忆内容
                'type': mem_type,  # 记忆类型
                'metadata': metadata or {},  # 元数据，默认为空字典
                'timestamp': time.time()  # 当前时间戳
            }
            self._memories.append(memory_entry)  # 添加到记忆列表

            # 限制记忆数量，防止无限增长  # 注释：内存保护机制
            if len(self._memories) > 1000:  # 如果超过1000条
                self._memories = self._memories[-1000:]  # 只保留最近1000条

            self._save()  # 保存到文件

    def search(self, query: str, limit: int = 5) -> list[dict]:  # 搜索记忆方法
        """简单关键词搜索记忆"""  # 方法文档字符串
        with self._lock:  # 获取锁，保证线程安全
            query_lower = query.lower()  # 将查询转为小写
            results = []  # 初始化结果列表

            for mem in reversed(self._memories):  # 逆序遍历记忆（最新的优先）
                if query_lower in mem['content'].lower():  # 检查查询词是否在内容中
                    results.append(mem)  # 添加到结果
                    if len(results) >= limit:  # 达到限制数量
                        break  # 结束循环

            return results  # 返回搜索结果

    def get_recent(self, limit: int = 10) -> list[dict]:  # 获取最近记忆方法
        """获取最近的记忆"""  # 方法文档字符串
        with self._lock:  # 获取锁，保证线程安全
            return self._memories[-limit:]  # 返回列表的最后limit个元素

    def count(self) -> int:  # 获取记忆数量方法
        """获取记忆数量"""  # 方法文档字符串
        with self._lock:  # 获取锁，保证线程安全
            return len(self._memories)  # 返回记忆列表长度

    def clear(self):  # 清空记忆方法
        """清空记忆"""  # 方法文档字符串
        with self._lock:  # 获取锁，保证线程安全
            self._memories = []  # 清空记忆列表
            self._save()  # 保存到文件（保存空列表）


class MultiUserManager:  # 多用户管理器类
    """多用户管理器"""  # 类文档字符串

    def __init__(self):  # 初始化方法
        self._sessions: dict[str, UserSession] = {}  # 会话字典：session_id -> UserSession
        self._user_memories: dict[str, UserMemoryStore] = {}  # 用户记忆存储字典
        self._sessions_lock = threading.RLock()  # 会话操作锁
        self.session_timeout = 3600  # 1小时超时（秒）

        # 用户偏好持久化  # 注释：设置偏好存储
        self.preferences_dir = Path("data/user_preferences")  # 偏好文件目录
        self.preferences_dir.mkdir(parents=True, exist_ok=True)  # 创建目录

    def create_session(self, user_id: str = None, preferences: dict = None) -> str:  # 创建会话方法
        """创建新会话"""  # 方法文档字符串
        session_id = str(uuid.uuid4())  # 生成UUID作为会话ID
        user_id = user_id or f"anonymous_{hashlib.md5(session_id.encode()).hexdigest()[:8]}"  # 生成用户ID

        # 加载或创建用户偏好  # 注释：偏好设置处理
        user_prefs = self._load_user_preferences(user_id)  # 加载已有偏好
        if preferences:  # 如果传入了新偏好
            user_prefs.update(preferences)  # 合并更新

        session = UserSession(  # 创建UserSession实例
            session_id=session_id,  # 会话ID
            user_id=user_id,  # 用户ID
            created_at=time.time(),  # 创建时间
            last_active=time.time(),  # 最后活跃时间
            preferences=user_prefs,  # 偏好设置
            context={}  # 空上下文
        )

        with self._sessions_lock:  # 获取锁
            self._sessions[session_id] = session  # 保存会话

        # 为用户创建独立的记忆存储  # 注释：创建记忆空间
        if user_id not in self._user_memories:  # 如果不存在
            self._user_memories[user_id] = UserMemoryStore(user_id)  # 创建存储实例

        logger.info(f"[MultiUser] 创建会话: {session_id}, 用户: {user_id}")  # 记录日志
        return session_id  # 返回会话ID

    def get_session(self, session_id: str) -> UserSession | None:  # 获取会话方法
        """获取会话"""  # 方法文档字符串
        with self._sessions_lock:  # 获取锁
            session = self._sessions.get(session_id)  # 获取会话
            if session:  # 如果存在
                # 检查超时  # 注释：超时检测
                if time.time() - session.last_active > self.session_timeout:  # 超时
                    self.destroy_session(session_id)  # 销毁会话
                    return None  # 返回None
                session.last_active = time.time()  # 更新最后活跃时间
            return session  # 返回会话对象

    def destroy_session(self, session_id: str):  # 销毁会话方法
        """销毁会话"""  # 方法文档字符串
        with self._sessions_lock:  # 获取锁
            if session_id in self._sessions:  # 如果存在
                session = self._sessions[session_id]  # 获取会话
                # 保存用户偏好  # 注释：持久化偏好
                self._save_user_preferences(session.user_id, session.preferences)  # 保存偏好
                logger.info(f"[MultiUser] 销毁会话: {session_id}")  # 记录日志
                del self._sessions[session_id]  # 删除会话

    def _load_user_preferences(self, user_id: str) -> dict:  # 加载用户偏好方法
        """加载用户偏好"""  # 方法文档字符串
        pref_file = self.preferences_dir / f"{user_id}.json"  # 偏好文件路径
        if pref_file.exists():  # 如果文件存在
            try:  # 异常处理
                with open(pref_file, encoding='utf-8') as f:  # 打开文件
                    return json.load(f)  # 解析并返回
            except Exception as e:  # 捕获异常
                logger.error(f"加载用户偏好失败 {user_id}: {e}")  # 记录错误
        return {}  # 默认返回空字典

    def _save_user_preferences(self, user_id: str, preferences: dict):  # 保存用户偏好方法
        """保存用户偏好"""  # 方法文档字符串
        try:  # 异常处理
            pref_file = self.preferences_dir / f"{user_id}.json"  # 偏好文件路径
            with open(pref_file, 'w', encoding='utf-8') as f:  # 打开文件写入
                json.dump(preferences, f, ensure_ascii=False, indent=2)  # 保存为JSON
        except Exception as e:  # 捕获异常
            logger.error(f"保存用户偏好失败 {user_id}: {e}")  # 记录错误

    def store_user_memory(self, session_id: str, content: str,
                         mem_type: str = "general", metadata: dict = None):  # 存储用户记忆方法
        """存储用户专属记忆"""  # 方法文档字符串
        session = self.get_session(session_id)  # 获取会话
        if not session:  # 会话不存在
            return  # 直接返回

        memory_store = self._user_memories.get(session.user_id)  # 获取记忆存储
        if not memory_store:  # 如果不存在
            memory_store = UserMemoryStore(session.user_id)  # 创建存储实例
            self._user_memories[session.user_id] = memory_store  # 保存引用

        memory_store.add(content, mem_type, {  # 添加记忆
            **(metadata or {}),  # 合并传入的元数据
            'user_id': session.user_id,  # 添加用户ID
            'session_id': session_id,  # 添加会话ID
            'timestamp': time.time()  # 添加时间戳
        })

    def retrieve_user_memory(self, session_id: str, query: str,
                            limit: int = 5) -> list[dict]:  # 检索用户记忆方法
        """检索用户专属记忆"""  # 方法文档字符串
        session = self.get_session(session_id)  # 获取会话
        if not session:  # 会话不存在
            return []  # 返回空列表

        memory_store = self._user_memories.get(session.user_id)  # 获取记忆存储
        if not memory_store:  # 不存在
            return []  # 返回空列表

        return memory_store.search(query, limit)  # 调用搜索方法

    def get_user_stats(self, user_id: str) -> dict:  # 获取用户统计方法
        """获取用户统计"""  # 方法文档字符串
        with self._sessions_lock:  # 获取锁
            sessions = [s for s in self._sessions.values() if s.user_id == user_id]  # 筛选用户会话

        memory_store = self._user_memories.get(user_id)  # 获取记忆存储
        memory_count = memory_store.count() if memory_store else 0  # 获取记忆数量

        return {  # 返回统计字典
            'user_id': user_id,  # 用户ID
            'active_sessions': len(sessions),  # 活跃会话数
            'total_memories': memory_count,  # 记忆总数
            'preferences': sessions[0].preferences if sessions else self._load_user_preferences(user_id)  # 偏好设置
        }

    def update_user_preference(self, session_id: str, key: str, value: any):  # 更新用户偏好方法
        """更新用户偏好"""  # 方法文档字符串
        session = self.get_session(session_id)  # 获取会话
        if session:  # 如果存在
            session.preferences[key] = value  # 更新偏好
            self._save_user_preferences(session.user_id, session.preferences)  # 保存到文件

    def get_user_preference(self, session_id: str, key: str, default=None):  # 获取用户偏好方法
        """获取用户偏好"""  # 方法文档字符串
        session = self.get_session(session_id)  # 获取会话
        if session:  # 如果存在
            return session.preferences.get(key, default)  # 返回偏好值
        return default  # 返回默认值

    def list_active_sessions(self) -> list[dict]:  # 列出活跃会话方法
        """列出所有活跃会话"""  # 方法文档字符串
        with self._sessions_lock:  # 获取锁
            return [  # 返回会话信息列表
                {
                    'session_id': s.session_id,  # 会话ID
                    'user_id': s.user_id,  # 用户ID
                    'created_at': s.created_at,  # 创建时间
                    'last_active': s.last_active,  # 最后活跃时间
                    'inactive_seconds': time.time() - s.last_active  # 不活跃秒数
                }
                for s in self._sessions.values()  # 遍历所有会话
            ]

    def cleanup_expired_sessions(self):  # 清理过期会话方法
        """清理过期会话"""  # 方法文档字符串
        current_time = time.time()  # 获取当前时间
        expired_sessions = []  # 过期会话列表

        with self._sessions_lock:  # 获取锁
            for session_id, session in list(self._sessions.items()):  # 遍历所有会话
                if current_time - session.last_active > self.session_timeout:  # 检查超时
                    expired_sessions.append(session_id)  # 添加到过期列表

        for session_id in expired_sessions:  # 遍历过期会话
            self.destroy_session(session_id)  # 销毁会话

        if expired_sessions:  # 如果有过期会话
            logger.info(f"[MultiUser] 清理 {len(expired_sessions)} 个过期会话")  # 记录日志

    def get_session_context(self, session_id: str) -> dict:  # 获取会话上下文方法
        """获取会话上下文"""  # 方法文档字符串
        session = self.get_session(session_id)  # 获取会话
        if session:  # 如果存在
            return session.context.copy()  # 返回上下文副本
        return {}  # 返回空字典

    def set_session_context(self, session_id: str, key: str, value: any):  # 设置会话上下文方法
        """设置会话上下文"""  # 方法文档字符串
        session = self.get_session(session_id)  # 获取会话
        if session:  # 如果存在
            session.context[key] = value  # 设置上下文值


# 全局实例
multi_user_manager = MultiUserManager()  # 创建多用户管理器全局实例


# 便捷函数
def create_session(user_id: str = None, preferences: dict = None) -> str:  # 创建会话便捷函数
    """创建会话的便捷函数"""  # 函数文档字符串
    return multi_user_manager.create_session(user_id, preferences)  # 调用管理器方法


def get_session(session_id: str) -> UserSession | None:  # 获取会话便捷函数
    """获取会话的便捷函数"""  # 函数文档字符串
    return multi_user_manager.get_session(session_id)  # 调用管理器方法


def store_user_memory(session_id: str, content: str, mem_type: str = "general", metadata: dict = None):  # 存储记忆便捷函数
    """存储用户记忆的便捷函数"""  # 函数文档字符串
    multi_user_manager.store_user_memory(session_id, content, mem_type, metadata)  # 调用管理器方法


def retrieve_user_memory(session_id: str, query: str, limit: int = 5) -> list[dict]:  # 检索记忆便捷函数
    """检索用户记忆的便捷函数"""  # 函数文档字符串
    return multi_user_manager.retrieve_user_memory(session_id, query, limit)  # 调用管理器方法


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"多用户支持核心模块"，负责实现用户级别的
# 会话隔离、独立记忆空间和用户偏好管理。这是系统支持多用户架构的基础组件。
#
# 【核心功能】
# 1. 用户会话管理：创建、获取、销毁用户会话，支持1小时超时自动清理
# 2. 记忆空间隔离：每个用户拥有独立的记忆存储，存储在data/user_memories/目录下
# 3. 用户偏好管理：持久化用户偏好设置到data/user_preferences/目录
# 4. 线程安全：使用RLock保证多线程环境下的数据安全
#
# 【主要类说明】
# - UserSession: 用户会话数据类，包含session_id、user_id、偏好设置等
# - UserMemoryStore: 用户专属记忆存储，支持增删改查和关键词搜索
# - MultiUserManager: 多用户管理器，统一管理所有用户和会话
#
# 【关联文件】
# - core/user_session_manager.py: 更高级别的会话管理，调用本模块
# - core/dialogue_manager.py: 对话管理器，使用本模块进行用户隔离
# - core/memory_manager.py: 记忆管理器，与用户记忆存储配合使用
#
# 【使用场景】
# - 多用户聊天系统：每个用户有独立的对话历史和记忆
# - 用户偏好个性化：记住用户的设置和习惯
# - 会话超时管理：自动清理长时间不活跃的会话，释放资源
#
# 【数据持久化】
# - 用户记忆：data/user_memories/{user_id}.json
# - 用户偏好：data/user_preferences/{user_id}.json
#
# 【向后兼容】
# 未指定user_id时自动生成anonymous_前缀的匿名用户ID，确保单用户场景
# 也能正常工作。
# =============================================================================
