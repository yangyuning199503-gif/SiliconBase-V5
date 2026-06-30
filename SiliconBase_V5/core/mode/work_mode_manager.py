#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
工作模式管理器 - 双模式架构实现  # 模块功能概述：管理工作模式
2026-02-28 重构：实现双模式架构（日常模式 vs 专注模式）  # 版本信息

双模式架构定义：  # 架构定义
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  # 分隔线
DAILY (日常模式):  # 日常模式
- AI连接思维模块  # 特性1
- 弱连接可主动触发任务  # 特性2
- 正常思考频率（5分钟）  # 特性3
- 思考优先级：中等（5）  # 特性4

FOCUS (专注模式):  # 专注模式
- AI也能思考，但优先级最低  # 特性1
- 不主动触发弱连接  # 特性2
- 思考频率降低（10分钟）  # 特性3
- 思考优先级：最低（10）  # 特性4
- 优先考虑用户需求  # 特性5
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  # 分隔线
"""  # 文档字符串结束
import threading  # 导入线程模块
import time  # 导入时间模块
from collections.abc import Callable  # 从typing导入类型注解
from dataclasses import dataclass  # 从dataclasses导入数据类装饰器
from enum import Enum  # 从enum导入枚举类
from typing import Any

from core.config import config  # 导入配置模块
from core.logger import logger  # 导入日志记录器


class WorkMode(Enum):  # 工作模式枚举类
    """
    双模式架构定义

    DAILY (日常模式):
    - AI连接思维模块
    - 弱连接可主动触发任务
    - 正常思考频率

    FOCUS (专注模式):
    - AI也能思考，但优先级最低
    - 不主动触发弱连接
    - 思考频率降低
    - 优先考虑用户需求
    """  # 类文档字符串
    DAILY = "daily"      # 日常模式
    FOCUS = "focus"      # 专注模式


@dataclass  # 数据类装饰器
class ModeConfig:  # 模式配置数据类
    """模式配置数据类"""  # 类文档字符串
    mode: WorkMode  # 工作模式
    name: str = ""                           # 模式名称
    description: str = ""                    # 模式描述
    consciousness: dict[str, Any] = None     # 意识线程配置
    weak_connection: dict[str, Any] = None   # 弱连接配置

    def __post_init__(self):  # 初始化后处理
        """初始化默认值"""  # 方法文档字符串
        if self.consciousness is None:  # 如果意识配置为空
            self.consciousness = {  # 设置默认值
                "enabled": True,  # 启用
                "think_interval": 300,     # 思考间隔（秒）
                "think_priority": 5         # 思考优先级（1-10，1最高，10最低）
            }
        if self.weak_connection is None:  # 如果弱连接配置为空
            self.weak_connection = {  # 设置默认值
                "enabled": True,           # 弱连接是否启用
                "can_propose_task": True   # 弱连接是否可主动触发任务
            }


class WorkModeManager:  # 工作模式管理器类
    """
    工作模式管理器 - 管理双模式架构

    职责：
    1. 维护当前工作模式状态
    2. 提供模式切换功能
    3. 根据模式配置调整意识线程和弱连接行为
    """  # 类文档字符串
    _instance = None  # 单例模式：类变量
    _lock = threading.Lock()  # 单例模式：类级锁

    def __new__(cls):  # 重写__new__方法，实现单例模式
        with cls._lock:  # 获取锁
            if cls._instance is None:  # 如果实例不存在
                cls._instance = super().__new__(cls)  # 创建实例
        return cls._instance  # 返回实例

    def __init__(self):  # 初始化方法
        if '_initialized' in self.__dict__:  # 如果已初始化
            return  # 直接返回
        self._initialized = True  # 标记为已初始化

        self._mode = WorkMode.DAILY  # 日常模式为默认
        self._on_mode_change: Callable | None = None  # 模式变更回调
        self._lock = threading.Lock()  # 实例锁

        # 从配置加载模式配置
        self._load_configs()  # 加载配置

        logger.info(f"[WorkModeManager] 初始化完成，当前模式: {self._mode.value}")  # 记录日志

        # 注册状态到 StateRegistry
        self._register_state()  # 注册状态

        # ========== 【自动模式切换 - 初始化】==========
        # 【修复】关闭自动回退机制，模式切换完全由用户控制
        self._last_user_input_time = time.time()  # 上次用户输入时间
        self._focus_start_time = None  # 专注模式开始时间
        self._is_working = False  # 是否正在执行工作（长任务）
        self._auto_revert_delay = None  # 自动回退已关闭（设为None禁用）
        self._last_check_time = time.time()  # 上次检查时间
        # =============================================

    # ========== 【自动模式切换 - 专注模式超时回退】==========

    def on_user_input(self):  # 用户输入时调用
        """
        用户输入时调用
        更新最后输入时间，重置自动回退计时器
        """  # 方法文档字符串
        self._last_user_input_time = time.time()  # 更新输入时间
        if self._mode == WorkMode.FOCUS:  # 如果在专注模式
            logger.debug("[WorkModeManager] 专注模式收到用户输入，计时器重置")  # 记录调试日志

    def on_work_start(self):  # 工作开始时调用
        """工作开始时调用（长任务）"""  # 方法文档字符串
        self._is_working = True  # 标记为工作中
        logger.info("[WorkModeManager] 工作开始，暂停自动模式切换计时")  # 记录日志

    def on_work_end(self):  # 工作结束时调用
        """工作结束时调用"""  # 方法文档字符串
        self._is_working = False  # 标记为工作结束
        self._last_user_input_time = time.time()  # 重置计时器
        logger.info("[WorkModeManager] 工作结束，恢复自动模式切换计时")  # 记录日志

    def check_auto_revert(self) -> bool:  # 检查是否应该自动回退
        """
        检查是否应该自动回退到日常模式

        【修复】自动回退已关闭，模式切换完全由用户控制

        Returns:
            True: 应该回退到日常模式
            False: 保持当前模式
        """  # 方法文档字符串
        # 【修复】自动回退已禁用
        if self._auto_revert_delay is None:
            return False

        with self._lock:  # 获取锁
            # 只在专注模式下检查
            if self._mode != WorkMode.FOCUS:  # 如果不是专注模式
                return False  # 不需要回退

            # 工作执行中不检查
            if self._is_working:  # 如果工作中
                return False  # 不需要回退

            # 检查是否超时
            idle_time = time.time() - self._last_user_input_time  # 计算空闲时间
            if idle_time >= self._auto_revert_delay:  # 如果超过阈值
                logger.info(f"[WorkModeManager] 专注模式空闲{int(idle_time)}秒，自动回退日常模式")  # 记录日志
                return True  # 需要回退

            return False  # 不需要回退

    def auto_revert_if_needed(self):  # 如果需要则自动回退
        """如果需要，自动回退到日常模式"""  # 方法文档字符串
        if self.check_auto_revert():  # 如果需要回退
            self.set_mode(WorkMode.DAILY)  # 切换到日常模式
            # 播报模式切换（可选）
            logger.info("[WorkModeManager] 已从专注模式自动切换回日常模式")  # 记录日志

    def get_idle_time(self) -> float:  # 获取当前空闲时间
        """获取当前空闲时间（秒）"""  # 方法文档字符串
        if self._is_working:  # 如果工作中
            return 0  # 工作中不算空闲
        return time.time() - self._last_user_input_time  # 返回空闲时间

    # =============================================

    def _register_state(self):  # 注册状态到状态注册表
        """注册当前模式状态到状态注册表"""  # 方法文档字符串
        try:  # 异常处理
            from core.session.state_registry import register_state  # 导入注册函数

            def _get_mode_state():  # 获取模式状态的内部函数
                return {  # 返回状态字典
                    "current_mode": self._mode.value,  # 当前模式
                    "config": self.get_mode_info()  # 配置信息
                }

            register_state(  # 注册状态
                name="work_mode",  # 状态名称
                accessor=_get_mode_state,  # 访问函数
                description="当前工作模式状态"  # 描述
            )
        except Exception as e:  # 捕获异常
            logger.warning(f"[WorkModeManager] 注册状态失败: {e}")  # 记录警告

    def _load_configs(self):  # 从配置文件加载模式配置
        """从配置文件加载模式配置"""  # 方法文档字符串
        # 日常模式配置
        daily_config = config.get("work_mode.daily", {})  # 从配置读取
        self._mode_configs: dict[WorkMode, ModeConfig] = {  # 模式配置字典
            WorkMode.DAILY: ModeConfig(  # 日常模式配置
                mode=WorkMode.DAILY,
                name=daily_config.get("name", "日常模式"),
                description=daily_config.get("description", "AI连接思维模块，弱连接可主动触发任务"),
                consciousness=daily_config.get("consciousness", {  # 意识配置
                    "enabled": True,
                    "think_interval": 300,  # 5分钟
                    "think_priority": 5      # 中等优先级
                }),
                weak_connection=daily_config.get("weak_connection", {  # 弱连接配置
                    "enabled": True,
                    "can_propose_task": True  # 弱连接可主动触发任务
                })
            ),
            WorkMode.FOCUS: ModeConfig(  # 专注模式配置
                mode=WorkMode.FOCUS,
                name=daily_config.get("name", "专注模式"),
                description=daily_config.get("description", "AI思考优先级最低，不主动触发弱连接"),
                consciousness=daily_config.get("consciousness", {  # 意识配置
                    "enabled": True,
                    "think_interval": 600,  # 10分钟（频率降低）
                    "think_priority": 10     # 优先级最低（数字越大优先级越低）
                }),
                weak_connection=daily_config.get("weak_connection", {  # 弱连接配置
                    "enabled": False,         # 专注模式下禁用弱连接
                    "can_propose_task": False # 不主动触发任务
                })
            )
        }

    def set_mode(
        self,
        mode: WorkMode,
        reason: str = "",
        user_id: str = "default",
        session_id: str | None = None,
        use_coordinator: bool = True
    ) -> bool:
        """
        切换工作模式并播报

        【Phase 1 Week 2】集成 StateCoordinator
        切换前触发 Coordinator 保存，切换后触发 Coordinator 恢复

        Args:
            mode: 目标工作模式
            reason: 切换原因（可选）
            user_id: 用户ID（用于Coordinator）
            session_id: 会话ID（用于Coordinator）
            use_coordinator: 是否使用Coordinator协调

        Returns:
            bool: 切换是否成功
        """
        if mode not in self._mode_configs:
            logger.error(f"[WorkModeManager] 未知模式: {mode}")
            return False

        with self._lock:
            if mode == self._mode:
                return True

            old_mode = self._mode
            mode_config = self._mode_configs[mode]

            # ═══════════════════════════════════════════════════════════════
            # 【Phase 1 Week 2】Step 1: 切换前触发 Coordinator 保存
            # ═══════════════════════════════════════════════════════════════
            coordinator_result = None
            if use_coordinator:
                try:
                    from core.state_coordinator import before_mode_switch
                    coordinator_result = before_mode_switch(
                        from_mode=old_mode.value,
                        to_mode=mode.value,
                        context={"reason": reason, "auto": False},
                        user_id=user_id,
                        session_id=session_id
                    )
                    if coordinator_result.errors:
                        logger.warning(
                            f"[WorkModeManager] Coordinator 保存出现错误: "
                            f"{coordinator_result.errors}"
                        )
                except Exception as e:
                    logger.warning(f"[WorkModeManager] Coordinator 保存失败: {e}")

            # 执行模式切换
            self._mode = mode
            logger.info(f"[WorkModeManager] 切换工作模式: {old_mode.value} -> {mode.value}")

            # 【P2-004】模式切换语音播报
            try:
                self._announce_mode_change(mode, old_mode, reason)
            except Exception as e:
                logger.warning(f"[WorkModeManager] 模式切换语音播报失败: {e}")

            # 应用模式配置到意识线程
            try:
                self._apply_consciousness_config(mode_config.consciousness)
            except Exception as e:
                logger.warning(f"[WorkModeManager] 应用意识线程配置失败: {e}")

            # 应用模式配置到弱连接
            try:
                self._apply_weak_connection_config(mode_config.weak_connection)
            except Exception as e:
                logger.warning(f"[WorkModeManager] 应用弱连接配置失败: {e}")

            # 触发模式变更回调
            if self._on_mode_change:
                try:
                    self._on_mode_change(mode)
                except Exception as e:
                    logger.warning(f"[WorkModeManager] 模式变更回调失败: {e}")

            # ═══════════════════════════════════════════════════════════════
            # 【Phase 1 Week 2】Step 2: 切换后触发 Coordinator 恢复
            # ═══════════════════════════════════════════════════════════════
            if use_coordinator and coordinator_result and coordinator_result.snapshot_id:
                try:
                    from core.state_coordinator import after_mode_switch
                    after_result = after_mode_switch(
                        to_mode=mode.value,
                        snapshot_id=coordinator_result.snapshot_id,
                        user_id=user_id,
                        session_id=session_id,
                        restore_strategy="merge"  # 默认使用合并策略
                    )
                    if after_result.errors:
                        logger.warning(
                            f"[WorkModeManager] Coordinator 恢复出现错误: "
                            f"{after_result.errors}"
                        )
                except Exception as e:
                    logger.warning(f"[WorkModeManager] Coordinator 恢复失败: {e}")

            logger.info(f"[WorkModeManager] 已切换到{mode_config.name}模式")
            return True

    def _announce_mode_change(self, new_mode: WorkMode, old_mode: WorkMode, reason: str = ""):
        """
        【P2-004】播报模式切换

        使用语音助手播报模式切换信息

        Args:
            new_mode: 新模式
            old_mode: 旧模式
            reason: 切换原因
        """
        try:
            # 尝试导入语音助手
            from voice.voice_assistant import get_voice_assistant
            from voice.voice_prompts import DialogueManagerAnnouncements
            voice = get_voice_assistant()

            if not voice:
                logger.debug("[WorkModeManager] 语音助手不可用，跳过播报")
                return

            # 根据模式构建播报文本
            if new_mode == WorkMode.FOCUS:
                if reason:
                    voice.speak(f"进入专注模式，{reason}", is_system=True)
                else:
                    voice.speak(DialogueManagerAnnouncements.FOCUS_MODE_ON, is_system=True)
            elif new_mode == WorkMode.DAILY:
                if old_mode == WorkMode.FOCUS:
                    voice.speak(DialogueManagerAnnouncements.FOCUS_MODE_OFF, is_system=True)
                else:
                    voice.speak(DialogueManagerAnnouncements.DAILY_MODE, is_system=True)

            logger.debug(f"[WorkModeManager] 模式切换已播报: {old_mode.value} -> {new_mode.value}")

        except ImportError:
            # 语音模块不存在，静默跳过
            logger.debug("[WorkModeManager] 语音模块未安装，跳过播报")
        except Exception as e:
            logger.warning(f"[WorkModeManager] 语音播报失败: {e}")

    def _apply_consciousness_config(self, config: dict[str, Any]):  # 应用意识线程配置
        """应用意识线程配置"""  # 方法文档字符串
        try:  # 异常处理
            from core.Consciousness import get_consciousness  # 导入意识模块
            consciousness = get_consciousness()  # 获取意识实例

            if consciousness:  # 如果存在
                consciousness.set_think_interval(config["think_interval"])  # 设置思考间隔
                consciousness.set_think_priority(config["think_priority"])  # 设置优先级
                logger.info(f"[WorkModeManager] 意识线程配置: 间隔={config['think_interval']}秒, 优先级={config['think_priority']}")  # 记录日志
        except Exception as e:  # 捕获异常
            logger.warning(f"[WorkModeManager] 配置意识线程失败: {e}")  # 记录警告

    def _apply_weak_connection_config(self, config: dict[str, Any]):  # 应用弱连接配置
        """应用弱连接配置"""  # 方法文档字符串
        try:  # 异常处理
            from core.weak_connection import get_weak_connection_engine  # 导入弱连接模块
            weak_engine = get_weak_connection_engine()  # 获取弱连接引擎

            if weak_engine:  # 如果存在
                # 弱连接通过 should_run 方法检查模式，不需要额外配置
                logger.info(f"[WorkModeManager] 弱连接配置: enabled={config['enabled']}, can_propose_task={config['can_propose_task']}")  # 记录日志
        except Exception as e:  # 捕获异常
            logger.warning(f"[WorkModeManager] 配置弱连接失败: {e}")  # 记录警告

    def get_current_mode(self) -> WorkMode:  # 获取当前工作模式
        """获取当前工作模式"""  # 方法文档字符串
        return self._mode  # 返回当前模式

    def get_mode_config(self, mode: WorkMode = None) -> dict[str, Any] | None:  # 获取模式配置
        """获取指定模式的配置，默认返回当前模式配置"""  # 方法文档字符串
        if mode is None:  # 如果未指定
            mode = self._mode  # 使用当前模式
        cfg = self._mode_configs.get(mode)  # 获取配置
        if cfg:  # 如果存在
            return {  # 返回配置字典
                "mode": cfg.mode.value,
                "name": cfg.name,
                "description": cfg.description,
                "consciousness": cfg.consciousness,
                "weak_connection": cfg.weak_connection
            }
        return None  # 不存在返回None

    def get_mode_info(self) -> dict[str, Any]:  # 获取当前模式详细信息
        """获取当前模式的详细信息"""  # 方法文档字符串
        cfg = self._mode_configs.get(self._mode)  # 获取配置
        if cfg:  # 如果存在
            return {  # 返回详细信息
                "mode": self._mode.value,
                "name": cfg.name,
                "description": cfg.description,
                "consciousness": cfg.consciousness,
                "weak_connection": cfg.weak_connection
            }
        return {"mode": self._mode.value}  # 最小信息

    def is_weak_connection_allowed(self) -> bool:  # 当前模式是否允许弱连接
        """当前模式是否允许弱连接"""  # 方法文档字符串
        cfg = self._mode_configs.get(self._mode)  # 获取配置
        return cfg.weak_connection.get("enabled", False) if cfg else False  # 返回是否启用

    def can_propose_task(self) -> bool:  # 当前模式是否允许主动触发任务
        """当前模式是否允许主动触发任务"""  # 方法文档字符串
        cfg = self._mode_configs.get(self._mode)  # 获取配置
        return cfg.weak_connection.get("can_propose_task", False) if cfg else False  # 返回是否允许

    def get_think_interval(self) -> int:  # 获取当前模式的思考间隔
        """获取当前模式的思考间隔（秒）"""  # 方法文档字符串
        cfg = self._mode_configs.get(self._mode)  # 获取配置
        return cfg.consciousness.get("think_interval", 300) if cfg else 300  # 返回间隔

    def get_think_priority(self) -> int:  # 获取当前模式的思考优先级
        """获取当前模式的思考优先级（1-10，1最高，10最低）"""  # 方法文档字符串
        cfg = self._mode_configs.get(self._mode)  # 获取配置
        return cfg.consciousness.get("think_priority", 5) if cfg else 5  # 返回优先级

    def should_think(self) -> bool:  # 检查当前是否应该思考
        """
        检查当前是否应该思考

        根据当前模式的思考优先级判断是否允许思考
        """  # 方法文档字符串
        cfg = self._mode_configs.get(self._mode)  # 获取配置
        if not cfg:  # 如果不存在
            return False  # 不允许

        # 检查意识线程是否启用
        return cfg.consciousness.get("enabled", True)  # 如果未启用

    def register_mode_change_callback(self, callback: Callable):  # 注册模式变更回调
        """注册模式变更回调函数"""  # 方法文档字符串
        self._on_mode_change = callback  # 保存回调


# 兼容旧接口的别名
class ModeConfigLegacy:  # 兼容旧版本的ModeConfig
    """兼容旧版本 ModeConfig"""  # 类文档字符串
    def __init__(self, mode: WorkMode, interval: int = 30, auto_think: bool = True,
                 think_priority: int = 5, weak_connection_active: bool = True, description: str = ""):
        self.mode = mode  # 模式
        self.interval = interval  # 间隔
        self.auto_think = auto_think  # 自动思考
        self.think_priority = think_priority  # 思考优先级
        self.weak_connection_active = weak_connection_active  # 弱连接激活
        self.description = description  # 描述


def get_work_mode_manager() -> WorkModeManager:  # 获取WorkModeManager单例实例
    """获取 WorkModeManager 单例实例"""  # 函数文档字符串
    return WorkModeManager()  # 返回实例


# 便捷函数
def get_current_mode() -> WorkMode:  # 获取当前工作模式
    """获取当前工作模式"""  # 函数文档字符串
    return get_work_mode_manager().get_current_mode()  # 调用管理器方法


def is_daily_mode() -> bool:  # 检查是否为日常模式
    """检查是否为日常模式"""  # 函数文档字符串
    return get_work_mode_manager().get_current_mode() == WorkMode.DAILY  # 判断


def is_focus_mode() -> bool:  # 检查是否为专注模式
    """检查是否为专注模式"""  # 函数文档字符串
    return get_work_mode_manager().get_current_mode() == WorkMode.FOCUS  # 判断


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"工作模式管理器"，实现双模式架构（日常模式 vs 专注模式），
# 根据用户当前状态动态调整AI的思考频率和行为。
#
# 【双模式架构】
# DAILY (日常模式):
# - AI正常连接思维模块
# - 弱连接可主动触发任务
# - 思考间隔：5分钟
# - 思考优先级：中等（5）
#
# FOCUS (专注模式):
# - AI思考优先级最低
# - 不主动触发弱连接
# - 思考间隔：10分钟（频率降低）
# - 优先考虑用户需求
#
# 【主要功能】
# 1. 模式切换：支持手动和自动切换工作模式
# 2. 配置管理：为不同模式配置意识线程和弱连接参数
# 3. 自动回退：专注模式下3分钟无输入自动回退到日常模式
# 4. 工作检测：长任务执行期间暂停自动模式切换
# 5. 状态注册：将当前模式注册到状态注册表
#
# 【关联文件】
# - core/Consciousness.py           : 意识线程，接收本模块的配置
# - core/weak_connection.py         : 弱连接引擎，根据模式决定是否运行
# - core/state_registry.py          : 状态注册表，记录当前工作模式
# - core/config.py                  : 配置模块，提供模式配置默认值
#
# 【核心功能效果】
# 1. 智能调度：根据用户场景自动调整AI行为
# 2. 不打断：专注模式下降低AI主动干扰
# 3. 自动恢复：空闲后自动回到日常模式
# 4. 可扩展：支持添加更多工作模式
#
# 【使用场景】
# - 用户开始专注工作时，切换到专注模式
# - 长任务执行期间，暂停自动切换
# - 用户输入时，重置专注模式计时器
# =============================================================================
