#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
全局状态管理 - 向后兼容稳定版 V5.3
简化设计：保持单例模式，确保向后兼容

关键变量：
- last_user_input_time: Consciousness 用于判断用户活跃状态
- runtime_flags: 标记可选模块可用性（OCR、向量模型等）
- set_voice_interface/get_voice_interface: 语音接口管理
- consciousness: 全局意识线程实例引用
- session_chat_history/chat_count_map: 会话历史和计数
"""
import threading  # 导入线程模块：用于线程锁保护
import time  # 导入时间模块：用于获取时间戳
from datetime import datetime  # 从datetime导入日期时间类
from typing import Any  # 从typing导入类型注解工具

# 运行时标志字典（用于标记可选模块可用性）  # 注释：运行时标志区域开始
runtime_flags: dict[str, Any] = {  # 定义运行时标志字典：存储模块可用性状态
    "ocr_available": False,  # OCR功能是否可用标志
    "vector_memory_available": False,  # 向量记忆是否可用标志
}

# 上次用户输入时间戳（用于Consciousness等模块判断用户活跃状态）  # 注释：用户活跃时间跟踪
# 【P0-014 修复】使用线程锁保护，避免竞态条件  # 修复说明注释
last_user_input_time: float = time.time()  # 初始化最后用户输入时间为当前时间戳
_last_user_input_lock = threading.Lock()  # 创建线程锁保护该变量的并发访问

# ============================================================================  # 分隔线：会话历史区域开始
# 会话历史和计数（向后兼容 - 使用简单字典实现）  # 区域标题注释
# ============================================================================  # 分隔线结束

# 会话历史：session_id -> messages list  # 注释：会话历史存储结构说明
session_chat_history: dict[str, list[dict]] = {  # 定义会话历史字典：存储各会话的消息列表
    "console": [],  # 控制台会话历史（空列表初始）
    "web": [],  # Web会话历史（空列表初始）
    "voice": []  # 语音会话历史（空列表初始）
}

# 聊天计数：session_id -> count  # 注释：聊天计数存储结构说明
chat_count_map: dict[str, int] = {  # 定义聊天计数字典：存储各会话的消息计数
    "console": 0,  # 控制台会话计数（初始为0）
    "web": 0,  # Web会话计数（初始为0）
    "voice": 0  # 语音会话计数（初始为0）
}

# 线程锁保护并发访问  # 注释：线程锁创建
_history_lock = threading.Lock()  # 创建会话历史访问锁
_count_lock = threading.Lock()  # 创建聊天计数访问锁


def clear_session_history(  # 定义清空会话历史函数
    session_id: str,  # 参数：会话ID
    user_id: str = None  # 参数：用户ID（可选，向后兼容）
) -> bool:  # 返回：是否成功
    """清空指定会话的历史和统计"""  # 函数文档字符串
    global session_chat_history, chat_count_map  # 声明使用全局变量
    with _history_lock:  # 获取历史锁保护
        session_chat_history[session_id] = []  # 清空该会话历史列表
    with _count_lock:  # 获取计数锁保护
        if session_id in chat_count_map:  # 检查会话是否存在于计数映射
            chat_count_map[session_id] = 0  # 重置该会话计数为0
    return True  # 返回成功标志


def get_session_history(  # 定义获取会话历史函数
    session_id: str,  # 参数：会话ID
    user_id: str = None  # 参数：用户ID（可选，向后兼容）
) -> list[dict]:  # 返回：消息列表
    """安全地获取会话历史"""  # 函数文档字符串
    with _history_lock:  # 获取历史锁保护
        return session_chat_history.get(session_id, []).copy()  # 返回历史副本（避免外部修改）


def append_session_history(  # 定义追加会话历史函数
    session_id: str,  # 参数：会话ID
    message: dict,  # 参数：消息字典
    user_id: str = None  # 参数：用户ID（可选，向后兼容）
) -> None:  # 返回：无
    """安全地追加会话历史"""  # 函数文档字符串
    global session_chat_history  # 声明使用全局变量
    with _history_lock:  # 获取历史锁保护
        if session_id not in session_chat_history:  # 如果会话不存在于历史字典
            session_chat_history[session_id] = []  # 创建空列表
        session_chat_history[session_id].append(message)  # 追加消息到列表


def increment_chat_count(  # 定义增加聊天计数函数
    session_id: str,  # 参数：会话ID
    user_id: str = None  # 参数：用户ID（可选，向后兼容）
) -> int:  # 返回：新计数
    """安全地更新会话计数"""  # 函数文档字符串
    global chat_count_map  # 声明使用全局变量
    with _count_lock:  # 获取计数锁保护
        if session_id not in chat_count_map:  # 如果会话不存在于计数映射
            chat_count_map[session_id] = 0  # 初始化为0
        chat_count_map[session_id] += 1  # 计数加1
        return chat_count_map[session_id]  # 返回新的计数值


def get_chat_count(  # 定义获取聊天计数函数
    session_id: str,  # 参数：会话ID
    user_id: str = None  # 参数：用户ID（可选，向后兼容）
) -> int:  # 返回：计数
    """获取会话计数"""  # 函数文档字符串
    with _count_lock:  # 获取计数锁保护
        return chat_count_map.get(session_id, 0)  # 返回计数，默认0


# ============================================================================  # 分隔线：语音接口区域开始
# 语音接口管理（向后兼容）  # 区域标题注释
# ============================================================================  # 分隔线结束

# 全局语音接口实例  # 注释：语音接口全局变量说明
_voice_interface_instance: Any | None = None  # 语音接口实例（初始None）

# 兼容旧的全局变量名  # 注释：兼容性处理说明
voice_instance = _voice_interface_instance  # 创建别名保持向后兼容

# 【并发修复-BUG-002】语音接口锁保护
_voice_interface_lock = threading.Lock()       # 语音接口专用锁


def get_voice_interface() -> Any | None:  # 定义获取语音接口函数
    """获取语音接口实例（向后兼容）【线程安全】"""  # 函数文档字符串
    with _voice_interface_lock:                # 【并发修复-BUG-002】原子读取
        return _voice_interface_instance  # 返回语音接口实例


def set_voice_interface(  # 定义设置语音接口函数
    voice  # 参数：语音接口实例
) -> None:  # 返回：无
    """设置语音接口实例（向后兼容）【线程安全】"""  # 函数文档字符串
    global _voice_interface_instance, voice_instance  # 声明使用全局变量
    with _voice_interface_lock:                # 【并发修复-BUG-002】原子写入
        _voice_interface_instance = voice  # 设置实例到主变量
        voice_instance = voice  # 同时设置到别名变量


# ============================================================================  # 分隔线：意识线程区域开始
# 全局意识线程实例（向后兼容）  # 区域标题注释
# ============================================================================  # 分隔线结束

consciousness: Any | None = None  # 全局意识实例引用（初始None）


def update_last_user_input_time() -> None:  # 定义更新用户输入时间函数
    """
    更新最后用户输入时间  # 函数功能说明

    【P0-014 修复】使用线程锁保护，确保线程安全  # 修复说明
    """  # 函数文档字符串结束
    global last_user_input_time  # 声明使用全局变量
    with _last_user_input_lock:  # 获取锁保护
        last_user_input_time = time.time()  # 更新为当前时间戳


def get_last_user_input_time() -> float:  # 定义获取用户输入时间函数
    """
    安全地获取最后用户输入时间  # 函数功能说明

    【P0-014 修复】使用线程锁保护读取操作，防止读到不一致的值  # 修复说明

    Returns:  # 返回值说明
        float: 最后用户输入时间戳  # 返回类型说明
    """  # 函数文档字符串结束
    with _last_user_input_lock:  # 获取锁保护
        return last_user_input_time  # 返回时间戳


# ============================================================================  # 分隔线：多用户支持区域开始
# 简单的多用户支持（基础实现，不依赖Redis）  # 区域标题注释
# ============================================================================  # 分隔线结束

class SimpleUserContext:  # 定义简化用户上下文类
    """简化的用户上下文"""  # 类文档字符串
    def __init__(self, user_id: str):  # 初始化方法
        self.user_id = user_id  # 保存用户ID
        self.session_history: dict[str, list[dict]] = {}  # 用户会话历史字典
        self.chat_count: int = 0  # 用户聊天计数（初始0）
        self.ptt_active: bool = False  # PTT状态标志（初始False）
        self.created_at = datetime.now()  # 记录创建时间
        self.last_active = datetime.now()  # 记录最后活跃时间


class SimpleUserContextManager:  # 定义简化用户上下文管理器类
    """简化的用户上下文管理器"""  # 类文档字符串
    DEFAULT_USER_ID = "default_user"  # 默认用户ID常量定义

    def __init__(self):  # 初始化方法
        self._contexts: dict[str, SimpleUserContext] = {}  # 用户上下文字典
        self._lock = threading.RLock()  # 创建可重入锁保护
        # 预创建默认用户  # 注释：初始化默认用户
        self._contexts[self.DEFAULT_USER_ID] = SimpleUserContext(self.DEFAULT_USER_ID)  # 创建默认上下文

    def get_or_create_context(  # 定义获取或创建上下文方法
        self,
        user_id: str  # 参数：用户ID
    ) -> SimpleUserContext:  # 返回：用户上下文
        with self._lock:  # 获取锁保护
            if user_id not in self._contexts:  # 如果用户不存在
                self._contexts[user_id] = SimpleUserContext(user_id)  # 创建新上下文
            return self._contexts[user_id]  # 返回用户上下文

    def get_context(  # 定义获取上下文方法
        self,
        user_id: str  # 参数：用户ID
    ) -> SimpleUserContext | None:  # 返回：用户上下文或None
        with self._lock:  # 获取锁保护
            return self._contexts.get(user_id)  # 返回上下文或None

    def list_active_users(self) -> list[str]:  # 定义列出活跃用户方法
        with self._lock:  # 获取锁保护
            return list(self._contexts.keys())  # 返回用户ID列表


# 全局用户上下文管理器实例  # 注释：创建全局实例
_user_context_manager = SimpleUserContextManager()  # 创建用户上下文管理器实例


def get_default_user_context() -> SimpleUserContext:  # 定义获取默认用户上下文函数
    """获取默认用户上下文"""  # 函数文档字符串
    return _user_context_manager.get_or_create_context(SimpleUserContextManager.DEFAULT_USER_ID)  # 获取默认上下文


def get_or_create_user_context(  # 定义获取或创建用户上下文函数
    user_id: str  # 参数：用户ID
) -> SimpleUserContext:  # 返回：用户上下文
    """获取或创建用户上下文"""  # 函数文档字符串
    return _user_context_manager.get_or_create_context(user_id)  # 调用管理器方法


def list_active_users() -> list[str]:  # 定义列出活跃用户函数
    """列出所有活跃用户"""  # 函数文档字符串
    return _user_context_manager.list_active_users()  # 调用管理器方法


# ============================================================================  # 分隔线：PTT状态管理区域开始
# PTT 状态管理（全局）  # 区域标题注释
# ============================================================================  # 分隔线结束

def set_ptt_active(  # 定义设置PTT状态函数
    active: bool,  # 参数：是否激活
    user_id: str = "default"  # 参数：用户ID，默认"default"
) -> None:  # 返回：无
    """
    设置 PTT（免唤醒）状态  # 函数功能说明

    Args:  # 参数说明
        active: 是否激活 PTT 模式  # 参数1说明
        user_id: 用户ID，默认为 "default"  # 参数2说明
    """  # 函数文档字符串结束
    try:  # 异常处理开始
        from core.dialog.dialogue_manager import dialogue_manager  # 导入对话管理器
        dialogue_manager.ptt_manager.set_ptt_active(user_id, active)  # 设置PTT状态
    except Exception as e:  # 捕获异常
        logger = None  # 初始化logger变量
        try:  # 尝试导入logger
            from core.logger import logger as _logger  # 导入日志模块
            logger = _logger  # 赋值给logger变量
        except Exception:  # 导入失败
            logger = None  # 设置为None
        if logger:  # 如果logger可用
            logger.debug(f"[global_state] 设置 PTT 状态失败: {e}")  # 记录调试日志


def is_ptt_active(  # 定义检查PTT状态函数
    user_id: str = "default"  # 参数：用户ID，默认"default"
) -> bool:  # 返回：是否激活
    """
    检查 PTT（免唤醒）状态  # 函数功能说明

    Args:  # 参数说明
        user_id: 用户ID，默认为 "default"  # 参数说明

    Returns:  # 返回值说明
        bool: 是否处于 PTT 模式  # 返回类型说明
    """  # 函数文档字符串结束
    try:  # 异常处理开始
        from core.dialog.dialogue_manager import dialogue_manager  # 导入对话管理器
        return dialogue_manager.ptt_manager.is_ptt_active(user_id)  # 返回PTT状态
    except Exception:  # 捕获异常
        return False  # 异常时返回False


# ============================================================================  # 分隔线：状态注册区域开始
# 状态注册到 StateRegistry  # 区域标题注释
# ============================================================================  # 分隔线结束

def _register_global_state() -> None:  # 定义注册全局状态函数（私有）
    """注册全局状态到状态注册表"""  # 函数文档字符串
    try:  # 异常处理开始
        from core.session.state_registry import register_state  # 导入注册函数

        def _get_global_state() -> dict:  # 内部函数：获取全局状态
            return {  # 返回状态字典
                "active_sessions": len(session_chat_history),  # 活跃会话数
                "session_ids": list(session_chat_history.keys()),  # 会话ID列表
                "chat_counts": dict(chat_count_map.items()),  # 聊天计数字典
                "active_users": list_active_users(),  # 活跃用户列表
                "runtime_flags": runtime_flags.copy(),  # 运行时标志副本
                "last_user_input_time": get_last_user_input_time()  # 最后用户输入时间
            }

        register_state(  # 调用注册函数
            name="global_state",  # 状态名称
            accessor=_get_global_state,  # 状态访问器函数
            description="全局状态"  # 状态描述
        )
    except Exception as e:  # 捕获异常
        print(f"[GlobalState] 注册全局状态失败: {e}")  # 打印错误信息


# 延迟注册（避免导入时循环依赖问题）  # 注释：延迟注册机制说明
import threading  # 导入线程模块（重复导入，实际使用已导入的）

_state_registered = False  # 状态注册标志（初始False）
_register_lock = threading.Lock()  # 创建注册锁


def ensure_state_registered() -> None:  # 定义确保状态已注册函数
    """确保状态已注册"""  # 函数文档字符串
    global _state_registered  # 声明使用全局变量
    if not _state_registered:  # 如果未注册
        with _register_lock:  # 获取锁保护
            if not _state_registered:  # 双重检查（避免竞态）
                _register_global_state()  # 执行注册
                _state_registered = True  # 标记已注册


# 可以在需要时调用，或在应用启动时调用  # 注释：使用说明
# ensure_state_registered()  # 调用示例（已注释）


# =============================================================================
# 总结性注释：文件角色、关联关系与核心效果
# =============================================================================
#
# 【文件角色】
# 本文件（global_state.py）是 SiliconBase V5 系统的"全局状态管理器"核心模块。
# 采用简化设计，保持单例模式，确保向后兼容，支持基础多用户功能。
# 它是系统中各模块共享全局状态的中央存储库。
#
# 【核心职责】
# 1. 运行时标志管理：标记OCR、向量记忆等可选模块的可用性
# 2. 用户活跃追踪：记录最后用户输入时间，支持Consciousness判断用户活跃度
# 3. 语音接口管理：提供全局语音接口的获取和设置
# 4. 会话历史管理：简单的会话历史存储、追加、清空和查询
# 5. 聊天计数管理：各会话的消息计数统计
# 6. PTT状态管理：免唤醒模式的设置和查询
# 7. 基础多用户支持：SimpleUserContextManager提供不依赖Redis的多用户功能
# 8. 状态注册：向StateRegistry注册全局状态供外部查询
#
# 【核心数据结构】
# 1. runtime_flags: Dict[str, Any] - 运行时标志字典
#    - ocr_available: OCR功能可用性
#    - vector_memory_available: 向量记忆可用性
#
# 2. last_user_input_time: float - 最后用户输入时间戳
#    - 使用_last_user_input_lock线程锁保护
#    - 通过update_last_user_input_time()和get_last_user_input_time()访问
#
# 3. session_chat_history: Dict[str, List[dict]] - 会话历史字典
#    - key: 会话ID (console/web/voice等)
#    - value: 消息列表
#    - 使用_history_lock保护
#
# 4. chat_count_map: Dict[str, int] - 聊天计数字典
#    - key: 会话ID
#    - value: 消息计数
#    - 使用_count_lock保护
#
# 5. SimpleUserContext: 用户上下文类
#    - user_id: 用户ID
#    - session_history: 用户会话历史
#    - chat_count: 用户聊天计数
#    - ptt_active: PTT状态
#    - created_at/last_active: 时间戳
#
# 【关联文件】
# 1. core/state_registry.py       - 状态注册表
#    * 关系：被本文件导入，用于注册全局状态
#    * 交互：调用register_state()注册全局状态访问器
#
# 2. core/dialogue_manager.py     - 对话管理器
#    * 关系：被set_ptt_active/is_ptt_active导入
#    * 交互：通过ptt_manager管理PTT状态
#
# 3. core/consciousness.py        - 意识系统
#    * 关系：引用consciousness全局变量和last_user_input_time
#    * 交互：判断用户活跃状态，触发自主行为
#
# 4. core/voice_interface.py      - 语音接口
#    * 关系：通过set_voice_interface/get_voice_interface管理
#    * 交互：提供全局语音功能访问
#
# 5. core/agent_loop.py           - Agent主循环
#    * 关系：调用update_last_user_input_time()更新用户活跃时间
#    * 交互：追踪用户交互状态
#
# 6. core/logger.py               - 日志系统
#    * 关系：在set_ptt_active中尝试导入
#    * 交互：记录调试信息
#
# 【达到的效果】
# 1. 向后兼容：保持原有全局变量访问方式，兼容旧代码
# 2. 线程安全：使用线程锁保护共享状态，避免竞态条件
# 3. 简单多用户：不依赖Redis，提供基础多用户支持
# 4. 状态集中：统一管理全局状态，便于维护和监控
# 5. 延迟注册：避免导入时循环依赖问题
# 6. 模块化：可选模块通过runtime_flags标记可用性
#
# 【使用场景】
# - AgentLoop更新用户活跃时间，触发Consciousness判断
# - VoiceInterface注册自身到全局状态
# - 各模块检查OCR/向量记忆等可选功能是否可用
# - PTT管理器设置和查询免唤醒状态
# - 多用户场景下管理各用户的会话历史
# - 状态监控页面查询全局状态
#
# =============================================================================
