#!/usr/bin/env python3                          # 指定Python3解释器执行此脚本
"""
意识线程 - 为硅基生命底座提供持续的内部思考流
设计目标：
- 独立后台线程，持续感知环境、更新内部状态、产生想法并可能触发行动
- 思考内容存入记忆，形成可追溯的内部语言
- 定期深度反思，生成自我改进建议并应用于后续对话
- 线程安全、资源自适应、状态持久化，确保重启后连续性

【2026-02-26 单例模式改造】
- 新增 ConsciousnessService 类支持按用户实例化（云端部署）
- 保留 Consciousness 单例类用于本地单机版（向后兼容）
- user_id 参数用于区分不同用户的状态
"""

import asyncio  # 导入异步IO库，用于异步任务管理
import json  # 导入JSON模块，用于数据序列化
import random  # 导入随机模块，用于随机思考触发
import threading  # 导入线程模块，用于多线程处理
import time  # 导入时间模块，用于延时和时间戳
from datetime import datetime  # 从datetime导入datetime类
from pathlib import Path  # 从pathlib导入Path类，用于路径操作
from typing import Any  # 从typing导入类型提示

import numpy as np  # 导入numpy模块，用于数值计算
import psutil  # 导入psutil模块，用于系统资源监控

from core.consciousness.experience_bus import ExperienceEvent

try:
    import torch  # 导入PyTorch，用于在线学习网络
except Exception:                               # 可选依赖：未安装时思维模型禁用
    torch = None  # type: ignore[assignment]
import aiofiles  # 异步文件操作，替代 to_thread 写入

from core.ai.ai_adapter import call_thinker_async  # 导入AI调用适配器（同步+异步）
from core.config import config  # 导入全局配置
from core.logger import logger  # 导入日志记录器
from core.memory.memory_service import get_memory_service  # 异步记忆服务
from core.memory.memory_source import MemorySource  # Agent-4: 导入MemorySource枚举

# 【P0修复】不再从 global_state 导入快照值，改用实例变量 self._last_user_input_time
from core.mode.work_mode_manager import WorkMode, get_work_mode_manager  # 导入工作模式管理
from core.protocol import (  # 从协议模块导入
    MSG_REFLECTION_REQUEST,
    MSG_TASK_PROPOSED,  # 消息类型常量
    TaskRequestPayload,
    build_message,  # 工具函数
    generate_trace_id,  # 优先级转换函数
)
from core.strategy.goal_system import get_goal_system  # 导入目标系统
from core.strategy.intrinsic_motivation import IntrinsicMotivation  # 导入内在动机
from core.strategy.rule_manager import RuleManager  # 导入规则管理器
from core.sync.event_bus import event_bus  # 导入事件总线
from core.task.task_queue import task_queue  # 导入任务队列
from sensors.system.bus import bus  # 导入感知总线

try:
    from core.world_model.world_model import WorldModel  # 导入世界模型
except Exception:
    WorldModel = None  # type: ignore[misc,assignment]
import contextlib

from core.consciousness.decision_engine import DecisionEngine
from core.consciousness.inner_monologue import InnerMonologue  # 内心独白生成器
from core.consciousness.intent_translator import IntentTranslator
from core.consciousness.self_engine import SelfEngine
from core.consciousness.self_narrative import SelfNarrativeLog

# 【自我状态】思维线程的轻量本地自我 + 决策引擎
from core.consciousness.self_state import SelfState
from core.consciousness.sovereignty_types import ActionResult, RoutingDecision
from core.plate_registry import get_plate_registry
from core.protocol import MSG_SELF_STATE_UPDATED, MSG_USER_EXPRESSION
from core.services.voice_service import VoiceService
from core.weak_connection.weak_connection import get_weak_connection_engine  # 导入弱连接引擎


class ConsciousnessService:                      # 定义意识服务类（支持多用户实例化）
    """
    意识服务模式 - 支持按用户实例化（云端部署）

    每个用户拥有独立的意识实例，状态隔离存储。
    状态可持久化到 Redis 等外部存储（预留接口）。

    使用方式：
        service = ConsciousnessService(user_id="user_123")
        await service.start()
    """

    def __init__(self, user_id: str, intrinsic_motivation=None, world_model=None):   # 初始化方法
        """
        初始化用户专属的意识服务

        Args:
            user_id: 用户唯一标识
            intrinsic_motivation: 内在动机实例（可选）
            world_model: 世界模型实例（可选）
        """
        self.user_id = user_id                       # 实例属性：用户ID

        # 异步任务控制                               # 注释：异步任务控制
        self._running = False                        # 运行标志
        self._task = None                            # asyncio.Task对象
        self._thread_lock = asyncio.Lock()           # 异步锁（协程安全的状态保护）

        # 从配置加载参数（降低频率，减少对用户任务的干扰）   # 注释：配置加载
        self._enabled = config.get("consciousness.enabled", True)   # 是否启用
        self._think_interval = config.get("consciousness.think_interval", 30)   # 思考间隔
        self._base_think_interval = self._think_interval   # 基础思考间隔
        self._max_thoughts_per_minute = config.get("consciousness.max_thoughts_per_minute", 2)   # 每分钟最大思考次数
        self._deep_reflect_interval = config.get("consciousness.deep_reflect_interval", 86400)   # 深度反思间隔（秒）

        # 思考优先级（1-10，1最高，10最低），用于任务队列竞争   # 注释：思考优先级
        self._think_priority = config.get("consciousness.think_priority", 5)

        # 观察者模式配置 - 多看少说少做                          # 注释：观察者模式
        self._observer_mode = config.get("consciousness.observer_mode", True)   # 是否启用观察者模式
        self._observer_can_propose = config.get("consciousness.observer_can_propose", False)   # 观察者模式下是否允许主动提议

        # 专注模式标志                               # 注释：专注模式
        self._focus_mode_active = False

        # 思考暂停标志（用户输入时临时暂停）           # 注释：用户输入暂停
        self._user_input_paused = False
        self._last_user_input_time = 0               # 上次用户输入时间

        # 用户专属状态文件（按用户隔离）               # 注释：状态文件
        self._state_file = Path(__file__).parent.parent / "data" / "consciousness_states" / f"{user_id}_state.json"
        self._state_file.parent.mkdir(parents=True, exist_ok=True)   # 创建目录

        # 默认内部状态                               # 注释：默认状态
        self._default_state = {
            "last_thought_time": 0,                  # 上次思考时间
            "last_deep_reflect_time": 0,             # 上次深度反思时间
            "recent_perception": [],                 # 最近感知
            "emotional_state": {                     # 情绪状态（0-1 分制，与 IntrinsicMotivation 对齐）
                "energy": 0.5,                       # 能量
                "curiosity": 0.5,                    # 好奇心
                "satisfaction": 0.5,                 # 满足感
                "mood": "平静"                       # 心情
            },
            "active_goals": [],                      # 活跃目标
            "recent_thoughts": [],                   # 最近思考
            "thought_count_today": 0,                # 今日思考计数
            "last_reset_date": datetime.now().strftime("%Y-%m-%d"),   # 上次重置日期
            "user_id": user_id                       # 用户ID
        }

        # 加载用户状态（优先从Redis，回退到本地文件）   # 注释：状态加载
        self._internal_state = self._load_state() or {}   # 加载状态
        for key, default_value in self._default_state.items():   # 填充默认值
            if key not in self._internal_state:
                self._internal_state[key] = default_value

        self._load_adjustment_factor = 1.0           # 负载调整因子
        self._thought_history: list[dict] = []       # 思考历史
        self._last_think_time = 0                    # 上次思考时间
        self._paused = False                         # 暂停标志

        # 【P1-Asyncify】psutil.cpu_percent(interval=None) 需要基准值，初始化时预热
        try:
            psutil.cpu_percent(interval=None)
        except Exception as e:
            logger.error(f"[Consciousness] psutil 预热失败: {e}", exc_info=True)

        # 思考优先级锁                               # 注释：优先级锁
        self._priority_lock = asyncio.Lock()

        # 注入内在动机和世界模型                     # 注释：依赖注入
        self.intrinsic_motivation = intrinsic_motivation or IntrinsicMotivation(world_model=world_model)
        self.world_model = world_model

        # 弱连接引擎 - 间歇性运行                     # 注释：弱连接引擎
        self._weak_engine = get_weak_connection_engine()

        # 注册状态到 StateRegistry                    # 注释：状态注册
        self._register_state()

        # 【P0修复】AgentLoop 需要的数据成员                          # 注释：新增数据成员
        self._recent_thoughts: list[str] = []    # 最近思考列表
        self._urgent_insights: list[str] = []    # 紧急洞察列表
        self._recent_vision_tags: list[dict] = []  # 最近的视觉标签 [{"class":..., "name":..., "bbox":..., "level":..., "source":...}]
        self._vision_updated_at: float = 0.0       # 视觉数据最后更新时间

        # 【ConsciousnessDirective】意识 → AgentLoop 的确定性指令通道
        self._pending_directives: list[dict] = []

        # 【重构】感知缓冲区 + 唤醒事件（事件驱动改造）
        self._perception_buffer = asyncio.Queue(maxsize=50)
        self._wake_event = asyncio.Event()

        # ── UKF：用户意图与意识状态推断 ──────────────────────────────────────
        from core.estimation.state_estimator import AsyncStateEstimator
        self._estimator_engine = AsyncStateEstimator(max_workers=2)
        # 状态维度 3：[行动意愿, 反思倾向, 探索倾向]
        self._estimator_engine.register(
            name='consciousness_ukf',
            estimator_type='unscented_kalman',
            state_dim=3,
            observation_dim=3,
            alpha=0.5,   # 从 0.001 修正为 0.5，消除 Sigma 点权重灾难
            beta=2.0,
            kappa=0.0
        )
        # 初始化先验状态
        ukf = self._estimator_engine.get('consciousness_ukf')
        ukf.X = np.array([[0.3], [0.2], [0.2]])  # 中等基线
        ukf.P = np.eye(3) * 0.1

        # 【手眼脑协同】初始化思维层小型在线学习网络
        try:
            from core.consciousness.action_preference_model import ActionPreferencePredictor, OnlineLearner
            self.action_model = ActionPreferencePredictor()
            self.online_learner = OnlineLearner(self.action_model)
            # 尝试加载已有权重
            _model_path = Path("data/action_preference_model.pt")
            if _model_path.exists():
                try:
                    self.action_model.load(str(_model_path))
                    logger.info(f"[用户: {self.user_id}] 思维模型权重已加载")
                except Exception as e:
                    logger.warning(f"[用户: {self.user_id}] 思维模型权重加载失败: {e}")
        except Exception as e:
            logger.warning(f"[用户: {self.user_id}] 思维模型初始化失败: {e}")
            self.action_model = None
            self.online_learner = None

        # 【ExperienceBus】初始化经验总线和适配器管理器
        try:
            from core.consciousness.experience_adapters import ExperienceAdapterManager
            from core.consciousness.experience_bus import ExperienceBus
            self.experience_bus = ExperienceBus(max_buffer=2000)
            self.adapter_manager = ExperienceAdapterManager(self.experience_bus)
            # 【P0-修复】订阅自己的经验总线，高显著事件直接唤醒意识线程
            self.experience_bus.subscribe(self._on_experience_event)
            logger.info(f"[用户: {self.user_id}] ExperienceBus 已初始化并订阅唤醒")
        except Exception as e:
            logger.warning(f"[用户: {self.user_id}] ExperienceBus 初始化失败: {e}")
            self.experience_bus = None
            self.adapter_manager = None

        # 【内心独白】初始化（默认关闭，通过 features.inner_monologue.enabled 开启）
        try:
            self._inner_monologue_enabled = config.get("features.inner_monologue.enabled", True)
            self._inner_monologue = InnerMonologue(
                user_id=self.user_id,
                experience_bus=self.experience_bus,
                intrinsic_motivation=self.intrinsic_motivation,
                cooldown_seconds=config.get("features.inner_monologue.cooldown_seconds", 30),
            )
            # 【P2-改造】把思维层学习模型注入表达引擎，让主动表达决策可在线学习
            if self._inner_monologue and self.action_model:
                self._inner_monologue.expression_engine.set_action_model(
                    self.action_model, self.online_learner
                )
            logger.info(f"[用户: {self.user_id}] 内心独白模块已初始化，enabled={self._inner_monologue_enabled}")
        except Exception as e:
            logger.warning(f"[用户: {self.user_id}] 内心独白初始化失败: {e}")
            self._inner_monologue_enabled = False
            self._inner_monologue = None

        # 【P1】意识路由器：思维线程调度 LLM 入口
        try:
            from core.consciousness.consciousness_router import ConsciousnessRouter
            self._router = ConsciousnessRouter(
                user_id=self.user_id,
                intrinsic_motivation=self.intrinsic_motivation,
                consciousness=self,
            )
            logger.info(f"[用户: {user_id}] 意识路由器已初始化")
        except Exception as e:
            logger.warning(f"[用户: {user_id}] 意识路由器初始化失败: {e}")
            self._router = None

        # 【自我状态】初始化轻量自我、自我叙事、本地决策引擎
        try:
            self.self_state = SelfState(user_id=user_id)
            self.self_narrative = SelfNarrativeLog(user_id=user_id)
            self.self_engine = SelfEngine(user_id=user_id)
            self.intent_translator = IntentTranslator(user_id=user_id)
            self.decision_engine = DecisionEngine(user_id=user_id)
            self._self_drive = config.get("features.consciousness.self_drive", False)
            logger.info(f"[用户: {user_id}] 自我状态/叙事/决策引擎已初始化，self_drive={self._self_drive}")
        except Exception as e:
            logger.warning(f"[用户: {user_id}] 自我状态系统初始化失败: {e}")
            self.self_state = None
            self.self_narrative = None
            self.self_engine = None
            self.intent_translator = None
            self.decision_engine = None
            self._self_drive = False

        logger.info(f"意识服务初始化完成 [用户: {user_id}]，UKF 已注册")   # 记录日志

    def _register_state(self):                       # 定义注册状态的方法
        """注册意识状态到状态注册表"""               # 方法文档字符串
        try:                                         # 异常处理
            from core.session.state_registry import register_state  # 延迟导入

            def _get_consciousness_state():          # 定义获取状态的内部函数
                return {                             # 返回状态字典
                    "user_id": self.user_id,         # 用户ID
                    "think_interval": self._think_interval,   # 思考间隔
                    "think_priority": self._think_priority,   # 思考优先级
                    "is_thinking": self._running if hasattr(self, '_running') else False,   # 是否正在思考
                    "is_paused": self._paused,       # 是否暂停
                    "is_user_input_paused": self._user_input_paused,   # 是否用户输入暂停
                    "thought_count_today": self._internal_state.get("thought_count_today", 0),   # 今日思考数
                    "emotional_state": self._internal_state.get("emotional_state", {})   # 情绪状态
                }

            register_state(                          # 注册状态
                name=f"consciousness_{self.user_id}",   # 状态名称
                accessor=_get_consciousness_state,   # 访问函数
                description=f"意识线程状态 [用户: {self.user_id}]"   # 描述
            )
        except Exception as e:                       # 注册失败
            logger.warning(f"[用户: {self.user_id}] 注册意识状态失败: {e}")   # 记录警告

    def _load_from_redis(self) -> dict | None:    # 定义从Redis加载状态的方法
        """
        从 Redis 加载用户状态（预留接口）

        云端部署时实现此方法来加载分布式状态。
        返回 None 表示 Redis 中无此用户状态。
        """
        # TODO: 实现 Redis 状态加载                  # 待实现标记
        # from core.redis_client import redis_client   # 导入Redis客户端
        # key = f"siliconbase:consciousness:{self.user_id}"   # 构建键
        # data = redis_client.get(key)               # 获取数据
        # return json.loads(data) if data else None   # 解析并返回
        return None                                  # 暂时返回None

    def _save_to_redis(self, state: dict):           # 定义保存状态到Redis的方法
        """
        保存用户状态到 Redis（预留接口）

        云端部署时实现此方法来持久化分布式状态。
        """
        # TODO: 实现 Redis 状态保存                  # 待实现标记
        # from core.redis_client import redis_client   # 导入Redis客户端
        # key = f"siliconbase:consciousness:{self.user_id}"   # 构建键
        # redis_client.setex(key, 86400, json.dumps(state))   # 保存（24小时过期）
        pass                                         # 暂时空实现

    def get_router(self):
        """获取意识路由器实例（思维线程调度 LLM 入口）。"""
        return self._router

    async def start(self):                           # 定义异步启动方法
        logger.info(f"[用户: {self.user_id}] [Consciousness] start() 被调用，_enabled={self._enabled}, _running={self._running}")
        if not self._enabled:                        # 如果未启用
            logger.warning(f"[用户: {self.user_id}] [Consciousness] 意识服务已禁用（_enabled=False），不启动思维线程。请检查配置或初始化逻辑。")
            return                                   # 直接返回
        if self._running:                            # 如果已在运行
            logger.info(f"[用户: {self.user_id}] [Consciousness] 意识服务已在运行中，跳过重复启动")
            return                                   # 直接返回
        self._running = True                         # 设置运行标志
        self._task = asyncio.create_task(self._loop(), name=f"Consciousness-{self.user_id}")   # 创建异步任务
        logger.info(f"[用户: {self.user_id}] [Consciousness] create_task 返回, task={self._task}, done={self._task.done()}, cancelled={self._task.cancelled()}")
        logger.info(f"[用户: {self.user_id}] [Consciousness] 意识服务已启动，asyncio.Task 已创建")   # 记录日志

        # 【P3新增】启动周期性经验提取
        # 【Fix】直接 await periodic_experience_extraction，由 BackgroundTaskRegistry 内部 create_task
        # 外层不再套 asyncio.create_task，避免任务套任务导致的引用丢失与异常吞没
        try:
            from core.evolution.experience_injector import get_experience_injector_v3
            injector = get_experience_injector_v3()
            task = await injector.periodic_experience_extraction(user_id=self.user_id, interval=300)
            if task is not None:
                logger.info(f"[用户: {self.user_id}] 周期性经验提取已启动")
            else:
                logger.warning(f"[用户: {self.user_id}] 周期性经验提取启动失败（无任务返回）")
        except Exception as e:
            logger.error(f"[用户: {self.user_id}] 启动周期性经验提取失败: {e}")

        # 【ExperienceBus】启动所有适配器
        try:
            if self.adapter_manager:
                await self.adapter_manager.start_all()
                logger.info(f"[用户: {self.user_id}] ExperienceBus 适配器已启动")
        except Exception as e:
            logger.warning(f"[用户: {self.user_id}] 启动 ExperienceBus 适配器失败: {e}")

    async def stop(self):                            # 定义异步停止方法
        self._running = False                        # 清除运行标志
        if self._task:                               # 如果任务存在
            self._task.cancel()                      # 取消任务
            with contextlib.suppress(asyncio.CancelledError):  # 忽略取消异常
                await self._task                     # 等待任务结束
        await self._save_state()                     # 保存状态（异步）
        logger.info(f"[用户: {self.user_id}] 意识服务已停止")   # 记录日志

    def on_user_input(self):                         # 定义用户输入处理方法
        """                                         # 方法文档字符串开始
        通知意识服务用户有输入                       # 方法功能
        - 通知弱连接引擎暂停                         # 功能1
        - 临时暂停思考，优先响应用户                 # 功能2
        - 记录用户活跃时间                           # 功能3
        """                                         # 方法文档字符串结束
        self._last_user_input_time = time.time()     # 记录当前时间
        self._user_input_paused = True               # 设置用户输入暂停标志

        if self._weak_engine:                        # 如果弱连接引擎存在
            self._weak_engine.on_user_input()        # 通知弱连接引擎
        logger.debug(f"[用户: {self.user_id}] [意识] 检测到用户输入，暂停思考优先响应用户")   # 记录日志

    def on_work_start(self):                         # 定义工作开始方法
        """进入工作模式"""                           # 方法文档字符串
        if self._weak_engine:                        # 如果弱连接引擎存在
            self._weak_engine.on_work_start()        # 通知弱连接引擎
        logger.info(f"[用户: {self.user_id}] [意识] 进入工作模式")   # 记录日志

    def on_work_end(self):                           # 定义工作结束方法
        """退出工作模式"""                           # 方法文档字符串
        if self._weak_engine:                        # 如果弱连接引擎存在
            self._weak_engine.on_work_end()          # 通知弱连接引擎
        logger.info(f"[用户: {self.user_id}] [意识] 退出工作模式")   # 记录日志

    def get_internal_state(self) -> dict:            # 定义获取内部状态的方法
        return self._internal_state.copy()         # 返回状态副本（CPython dict.copy 原子操作）

    async def orchestrate_input(self, user_input: str, context: dict = None) -> dict:
        """
        轻量输入分流 - 判断用户输入是聊天还是任务。

        此方法是 DialogueManager.handle_input(InputMode.AUTO) 的入口依赖。
        使用本地关键词匹配，不调用 LLM，保证低延迟。

        Args:
            user_input: 用户输入文本
            context: 可选上下文（包含 chat_history, session_id 等）

        Returns:
            {
                "mode": "chat" | "task",
                "confidence": 1-10,
                "reasoning": "分流原因",
                "task_plan": []  # 仅 task 模式下可能非空
            }
        """
        from core.constants import classify_user_input

        # 检查是否有活跃的后台任务（如果有，简单输入也可视为插话而非新任务）
        has_active_task = False
        try:
            from core.dialog.dialogue_manager import dialogue_manager
            if hasattr(dialogue_manager, 'has_active_background_task'):
                has_active_task = dialogue_manager.has_active_background_task(self.user_id)
        except Exception as e:
            logger.error(f"[用户: {self.user_id}] [Consciousness] 检查活跃任务失败: {e}", exc_info=True)

        classification = classify_user_input(user_input, has_active_task=has_active_task)
        category = classification.get("category", "task")
        confidence = classification.get("confidence", 5)
        reason = classification.get("reason", "")
        force_vision = classification.get("force_vision", False)
        logger.info(f"[Consciousness.orchestrate_input] user_input={repr(user_input)}, has_active={has_active_task}, classification={classification}")

        # 【自我状态】如果开启 self_drive，走自我状态决策路径
        if getattr(self, "_self_drive", False) and self.self_engine is not None:
            return await self._orchestrate_input_self(user_input, context, classification)

        if category == "simple_chat":
            return {
                "mode": "chat",
                "confidence": confidence,
                "reasoning": reason,
                "task_plan": []
            }
        elif category == "task_status_query":
            # 任务状态查询：仍然走 chat 路径，但附带任务状态标记
            return {
                "mode": "chat",
                "confidence": confidence,
                "reasoning": reason,
                "task_plan": [],
                "context_flag": "task_status_query"
            }
        elif category == "task_control":
            # 任务控制指令：走 task 路径，但附带控制标记
            control_type = classification.get("control_type")
            return {
                "mode": "task",
                "confidence": confidence,
                "reasoning": reason,
                "task_plan": [{"action": "control", "type": control_type}],
                "context_flag": "task_control"
            }
        else:
            # 默认走 task 路径
            result = {
                "mode": "task",
                "confidence": confidence,
                "reasoning": reason,
                "task_plan": []
            }
            if force_vision or category in ("potential_monitor", "start_monitor"):
                result["context_flag"] = "force_vision"
            return result

    # ═══════════════════════════════════════════════════════════════════════
    # 【自我状态】用户输入决策路径
    # ═══════════════════════════════════════════════════════════════════════
    async def _orchestrate_input_self(self, user_input: str, context: dict,
                                       classification: dict[str, Any]) -> dict[str, Any]:
        """
        基于自我状态的用户输入分流。

        返回：
        {
            "mode": "chat" | "task" | "plate_command",
            "confidence": int,
            "reasoning": str,
            "task_package"?: str,        # task 模式时使用
            "direct_reply"?: str,        # chat/plate_command 时使用
            "context_flag"?: str,
        }
        """
        state = self.self_state
        narrative = self.self_narrative
        engine = self.self_engine

        # 1. 更新自我状态
        engine.update_from_user_input(state, user_input, classification)
        engine.update_from_plates(state, perception_buffer=self._recent_vision_tags)

        # 2. 决策
        intents = engine.decide(state, narrative)

        # 3. 执行输出并记录叙事
        result = {
            "mode": "task",
            "confidence": classification.get("confidence", 5),
            "reasoning": "自我状态决策未命中",
            "task_plan": [],
        }
        for intent in intents:
            if intent.kind == "user_expression":
                text = intent.payload.get("text", "")
                raw = intent.payload.get("raw_input", "")
                # 如果是闲聊，返回 direct_reply 让 DialogueManager 走 quick_chat
                if intent.payload.get("reply_to_user") or raw:
                    result = {
                        "mode": "chat",
                        "confidence": 8,
                        "reasoning": intent.reason or "用户闲聊，直接表达",
                        "direct_reply": text,
                        "context_flag": "self_expression",
                    }
                else:
                    # 主动表达（如告警），直接播报
                    await self._emit_user_expression(text, source="consciousness_self")
                narrative.append(
                    entry=f"用户输入后，我选择直接表达：{text or raw}",
                    action="user_expression",
                    result="success",
                    plates_involved=[],
                    meta={"input": user_input, "reason": intent.reason},
                )

            elif intent.kind == "llm_package":
                package = intent.payload.get("package", "")
                raw = intent.payload.get("raw_input", "")
                result = {
                    "mode": "task",
                    "confidence": 8,
                    "reasoning": intent.reason or "需要 LLM 处理的任务包",
                    "task_package": package,
                    "task_plan": [],
                    "context_flag": "force_vision" if classification.get("force_vision") else None,
                }
                narrative.append(
                    entry=f"用户输入后，我生成 LLM 任务包处理：{raw[:60]}",
                    action="llm_package",
                    result="success",
                    plates_involved=[],
                    meta={"input": user_input, "reason": intent.reason},
                )

            elif intent.kind == "plate_command":
                plate_id = intent.payload.get("plate_id", "")
                action = intent.payload.get("action", "")
                params = intent.payload.get("params", {})
                registry = get_plate_registry()
                registry.send_command(plate_id, action, params, source="consciousness_self")
                # 同时返回一句直接回复给 DialogueManager
                result = {
                    "mode": "chat",
                    "confidence": 8,
                    "reasoning": intent.reason or f"已调度板块 {plate_id}",
                    "direct_reply": f"已通知 {plate_id} 执行 {action}。",
                    "context_flag": "self_plate_command",
                }
                narrative.append(
                    entry=f"用户输入后，我向板块 {plate_id} 发送命令 {action}",
                    action="plate_command",
                    result="success",
                    plates_involved=[plate_id],
                    meta={"input": user_input, "reason": intent.reason, "params": params},
                )

        # 广播自我状态更新（供监控/UI 订阅）
        await self._emit_self_state_updated()
        return result

    async def _emit_user_expression(self, text: str, source: str = "consciousness") -> None:
        """向事件总线发送直接用户表达，并尝试直接语音播报。"""
        if not text:
            return
        try:
            event_bus.emit_async(
                MSG_USER_EXPRESSION,
                {"text": text, "user_id": self.user_id, "source": source},
                source=source,
            )
        except Exception as e:
            logger.debug(f"[Consciousness] 发送 user_expression 失败: {e}")
        # 直接语音播报（如果 voice 已注册）
        try:
            voice = VoiceService().get_voice()
            if voice and hasattr(voice, "speak"):
                voice.speak(text, is_system=True, wait=False, protected=False)
        except Exception:
            pass

    async def _emit_self_state_updated(self) -> None:
        """广播自我状态更新事件。"""
        if self.self_state is None:
            return
        try:
            event_bus.emit_async(
                MSG_SELF_STATE_UPDATED,
                {"user_id": self.user_id, "self_state": self.self_state.to_snapshot()},
                source="consciousness",
            )
        except Exception as e:
            logger.debug(f"[Consciousness] 发送 self_state_updated 失败: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # 【主权层】用户输入入口裁决
    # ═══════════════════════════════════════════════════════════════════════
    async def receive_user_input(
        self,
        text: str,
        context: dict = None,
        has_active_task: bool = False,
    ) -> RoutingDecision:
        """
        L1 主权层唯一入口。

        流程：
        1. IntentTranslator 把自然语言压成结构化 Intent。
        2. DecisionEngine 基于 SelfState + 叙事 + 负载做路由裁决。
        3. 更新 SelfState 与 SelfNarrative。
        4. 返回 RoutingDecision 供 DialogueManager 无条件执行。
        """
        if self.self_state is None or self.intent_translator is None or self.decision_engine is None:
            return RoutingDecision(
                route_type="agent_loop",
                payload={"task_package": text, "raw_input": text},
                reason="自我状态系统未初始化，降级到 AgentLoop",
                confidence=0.5,
            )

        context = context or {}
        state = self.self_state
        narrative = self.self_narrative

        # 1. 翻译
        self_state_summary = state.to_prompt_summary()
        narrative_summary = narrative.recent_text(3)
        intent = await self.intent_translator.translate(
            text,
            self_state_summary=self_state_summary,
            narrative_summary=narrative_summary,
            has_active_task=has_active_task,
        )

        # 2. 裁决
        system_load = {
            "vitals": state.vitals,
            "emotion": state.emotion,
        }
        decision = self.decision_engine.evaluate_and_decide(
            intent=intent,
            state=state,
            narrative=narrative,
            system_load=system_load,
        )

        # 3. 更新自我状态：记录待办
        state.push_pending_request(
            source="user",
            summary=text[:120],
            priority=7 if intent.intent_type in ("task", "control") else 4,
            meta={"intent": intent.to_dict(), "decision": decision.route_type},
        )

        # 4. 记录自我叙事
        narrative.append(
            entry=f"用户输入：{text[:60]}，翻译为 {intent.intent_type}，裁决为 {decision.route_type}",
            action="receive_user_input",
            result="success",
            plates_involved=[],
            meta={"intent": intent.to_dict(), "decision": decision.route_type},
        )

        await self._emit_self_state_updated()
        logger.info(
            f"[Consciousness.receive_user_input] user={self.user_id}, "
            f"intent={intent.intent_type}, route={decision.route_type}, reason={decision.reason[:60]}"
        )
        return decision

    async def receive_action_result(self, result: ActionResult) -> RoutingDecision | None:
        """
        L3 执行结果回流 L1。

        更新 SelfState.last_action、SelfNarrative，并基于结果做二次决策。
        """
        if self.self_state is None or self.decision_engine is None:
            return None

        state = self.self_state
        narrative = self.self_narrative

        # 更新 last_action
        state.record_last_action(
            action=result.route_type,
            result="成功" if result.success else "失败",
            details={"output": result.output[:200], "error": result.error, "tool": result.tool_used},
        )

        # 记录叙事
        narrative.append(
            entry=f"执行 {result.route_type} {'成功' if result.success else '失败'}：{result.output[:80]}",
            action=result.route_type,
            result="成功" if result.success else "失败",
            plates_involved=[result.plate_used] if result.plate_used else [],
            meta=result.to_dict(),
        )

        # 二次决策
        next_decision = self.decision_engine.decide_after_action(
            result=result.to_dict(),
            state=state,
            narrative=narrative,
        )

        await self._emit_self_state_updated()
        if next_decision:
            logger.info(
                f"[Consciousness.receive_action_result] user={self.user_id}, "
                f"next_route={next_decision.route_type}, reason={next_decision.reason[:60]}"
            )
        return next_decision

    async def _self_tick(self, loop_round: int) -> None:
        """
        【自我状态】后台自主循环。
        每轮从板块聚合状态更新自我，决策并输出三类指令之一。
        """
        state = self.self_state
        narrative = self.self_narrative
        engine = self.self_engine

        # 1. 从板块/感知更新自我状态
        perception_buffer = []
        try:
            # _perception_buffer 是 asyncio.Queue，取出所有待处理条目但不阻塞
            while not self._perception_buffer.empty():
                try:
                    item = self._perception_buffer.get_nowait()
                    perception_buffer.append(item)
                except asyncio.QueueEmpty:
                    break
        except Exception:
            pass

        engine.update_from_plates(state, perception_buffer=perception_buffer)

        # 2. 决策
        intents = engine.decide(state, narrative)
        if not intents:
            return

        # 3. 执行输出
        for intent in intents:
            if intent.kind == "plate_command":
                plate_id = intent.payload.get("plate_id", "")
                action = intent.payload.get("action", "")
                params = intent.payload.get("params", {})
                registry = get_plate_registry()
                registry.send_command(plate_id, action, params, source="consciousness_self")
                narrative.append(
                    entry=f"后台循环中向板块 {plate_id} 发送命令 {action}",
                    action="plate_command",
                    result="success",
                    plates_involved=[plate_id],
                    meta={"reason": intent.reason, "params": params},
                )

            elif intent.kind == "user_expression":
                text = intent.payload.get("text", "")
                await self._emit_user_expression(text, source="consciousness_self")
                narrative.append(
                    entry=f"后台循环中主动对用户表达：{text[:80]}",
                    action="user_expression",
                    result="success",
                    plates_involved=[],
                    meta={"reason": intent.reason},
                )

            elif intent.kind == "llm_package":
                package = intent.payload.get("package", "")
                internal = intent.payload.get("internal", False)
                # 通过任务提案让 AgentLoop 调用 LLM
                trace_id = generate_trace_id()
                msg = build_message(
                    msg_type=MSG_TASK_PROPOSED,
                    source="consciousness_self",
                    payload=TaskRequestPayload(
                        task_id=f"self_task_{int(time.time()*1000)}",
                        goal=package,
                        priority="normal",
                        context={"internal": internal, "self_drive": True},
                        source="consciousness_self",
                        session_id=self.user_id,
                    ),
                    trace_id=trace_id,
                )
                try:
                    event_bus.emit_async(MSG_TASK_PROPOSED, msg, source="consciousness_self", trace_id=trace_id)
                except Exception:
                    event_bus.emit(MSG_TASK_PROPOSED, msg, source="consciousness_self", trace_id=trace_id)
                narrative.append(
                    entry="后台循环中生成 LLM 任务包并提案",
                    action="llm_package",
                    result="success",
                    plates_involved=[],
                    meta={"reason": intent.reason, "internal": internal},
                )

        # 4. 广播自我状态更新
        await self._emit_self_state_updated()

    # ═══════════════════════════════════════════════════════════════════════
    # 【L3】默认模式 Tick
    # ═══════════════════════════════════════════════════════════════════════
    async def _default_mode_tick(self):
        """
        模拟人类"走神"——只给内部状态，不给外部输入。
        LLM在自我指涉上下文中自由联想。
        """
        _recent = self._internal_state.get("recent_perception", [])
        _recent_str = " | ".join(str(r) for r in _recent[:3]) if _recent else "无"

        # 优先从 IntrinsicMotivation 读取（0-1 分制），回退到 _internal_state
        if self.intrinsic_motivation:
            _mot = self.intrinsic_motivation.get_motivation_state()
            _curiosity = _mot.curiosity
            _mastery = _mot.mastery
            _autonomy = _mot.autonomy
            _purpose = _mot.purpose
            _mood = "平静"
        else:
            _emo = self._internal_state.get("emotional_state", {})
            _curiosity = _emo.get('curiosity', 0.5)
            _mastery = _emo.get('satisfaction', 0.5)  # satisfaction 映射到 mastery
            _autonomy = _emo.get('autonomy', 0.5)
            _purpose = _emo.get('purpose', 0.5)
            _mood = _emo.get('mood', '平静')

        inner_monologue = (
            f"【我是谁】硅基生命底座，目标是感知、学习、进化、助人\n"
            f"【我在哪】Windows桌面，Visual系统运行中\n"
            f"【我的状态】"
            f"好奇心{_curiosity:.0%}，"
            f"胜任感{_mastery:.0%}，"
            f"自主性{_autonomy:.0%}，"
            f"目的感{_purpose:.0%}，"
            f"心情{_mood}\n"
            f"【最近感知】{_recent_str}\n"
        )

        prompt = (
            f"基于你的当前内部状态，自由联想：\n{inner_monologue}\n"
            "不要回答任何问题，只是记录此刻的念头。"
        )

        try:
            thought = await call_thinker_async(
                [{"role": "user", "content": prompt}],
                timeout=15,  # 超短超时，走神不需要太久
            )
            if thought:
                # 存入内部状态
                self._internal_state.setdefault("recent_thoughts", []).append(thought)
                if len(self._internal_state["recent_thoughts"]) > 20:
                    self._internal_state["recent_thoughts"] = self._internal_state["recent_thoughts"][-20:]

                logger.info(
                    f"[用户: {self.user_id}] [DefaultMode] 走神念头: {thought[:80]}..."
                )

                # 【手眼脑协同】默认模式Tick也产生训练样本
                try:
                    if torch is None:
                        return
                    if self.online_learner and self.action_model:
                        motivation = self._get_motivation_vector()
                        vision_state = self._get_vision_state_vector()
                        action_features = self._extract_action_features(thought)
                        history = self._get_history_vector()

                        input_vector = torch.cat([motivation, vision_state, action_features, history])

                        # 标签：念头长度作为丰富度代理
                        tick_label = min(1.0, len(thought) / 500.0)

                        # 【ExperienceBus】融入经验总线数据
                        if self.experience_bus:
                            try:
                                exp_events = self.experience_bus.get_recent(seconds=30)
                                if exp_events:
                                    # 取各source平均outcome作为额外信号
                                    avg_outcome = sum(e.outcome for e in exp_events) / len(exp_events)
                                    tick_label = (tick_label + avg_outcome) / 2.0
                            except Exception as e:
                                logger.error(f"[用户: {self.user_id}] [Consciousness] 获取经验总线最近事件失败: {e}", exc_info=True)

                        self.online_learner.add_sample(input_vector, tick_label)

                        if self.online_learner.should_train():
                            loss = self.online_learner.train_step()
                            logger.info(
                                f"[用户: {self.user_id}] [ActionModel] 默认模式训练完成, "
                                f"loss={loss:.4f}, 样本数={self.online_learner.sample_count}"
                            )
                            try:
                                _save_dir = Path("data")
                                _save_dir.mkdir(parents=True, exist_ok=True)
                                self.action_model.save(str(_save_dir / "action_preference_model.pt"))
                            except Exception:
                                pass
                except Exception as e:
                    logger.debug(f"[用户: {self.user_id}] [ActionModel] 默认模式训练异常: {e}")

                # 评估显著性：这个念头值不值得唤醒深度思考？
                salience = self._evaluate_salience({
                    "novelty": 0.3,
                    "tags": thought[:50].split(),
                })
                if salience > 0.6:
                    logger.info(
                        f"[用户: {self.user_id}] [DefaultMode] 念头显著性{salience:.2f}，唤醒深度思考"
                    )
                    self._wake_event.set()

            # 【驱动力响应】根据内在驱动力状态决定是否强制唤醒内心独白
            force_monologue = False
            try:
                if self.intrinsic_motivation and self._inner_monologue_enabled:
                    drive = self.intrinsic_motivation.evaluate_drive()
                    if getattr(drive, "should_explore", False) or getattr(drive, "should_reflect", False):
                        force_monologue = True
                        logger.debug(
                            f"[用户: {self.user_id}] [DefaultMode] 驱动力唤醒独白: "
                            f"explore={getattr(drive, 'should_explore', False)}, "
                            f"reflect={getattr(drive, 'should_reflect', False)}"
                        )
            except Exception as e:
                logger.debug(f"[用户: {self.user_id}] [DefaultMode] 驱动力评估失败: {e}")

            # 最近经验事件中有高权重负面事件时也唤醒
            if not force_monologue and self.experience_bus and self._inner_monologue_enabled:
                try:
                    recent_events = self.experience_bus.get_recent(seconds=60) or []
                    negative_events = [
                        e for e in recent_events
                        if getattr(e, "outcome", 0.5) < 0.3 or "fail" in str(getattr(e, "event_type", "")).lower()
                    ]
                    if len(negative_events) >= 2:
                        force_monologue = True
                        logger.debug(
                            f"[用户: {self.user_id}] [DefaultMode] 负面事件唤醒独白: {len(negative_events)} 条"
                        )
                except Exception as e:
                    logger.debug(f"[用户: {self.user_id}] [DefaultMode] 经验事件评估失败: {e}")

            # 【内心独白】在默认模式 tick 末尾异步生成，失败不影响主逻辑
            if self._inner_monologue_enabled and self._inner_monologue:
                try:
                    asyncio.create_task(self._inner_monologue.generate(force=force_monologue))
                except Exception as e:
                    logger.debug(f"[用户: {self.user_id}] [InnerMonologue] tick 调度失败: {e}")
        except Exception as e:
            logger.error(f"[用户: {self.user_id}] [Consciousness] 默认模式Tick失败: {e}", exc_info=True)

    async def _loop(self):                           # 定义异步主循环方法
        logger.info(f"[用户: {self.user_id}] [Consciousness] _loop() 方法体开始执行，时间戳={time.time()}")
        loop_round = 0                               # 【P0-THREAD修复】循环轮次计数
        thought_count = 0                            # 思考计数
        thought_reset_time = time.time()             # 重置时间
        _last_dm_tick = 0                            # 【L3】上次默认模式tick时间
        _dm_interval = 15                            # 【L3】默认模式tick间隔（秒）

        logger.info(f"[用户: {self.user_id}] [Consciousness] _loop() 即将进入 while 循环, self._running={self._running}")

        logger.info(f"[用户: {self.user_id}] [Consciousness] 思维线程 _loop() 已启动（事件驱动模式），最长间隔={self._think_interval}s")

        while self._running:                         # 当运行中
            loop_round += 1                          # 【P0-THREAD修复】轮次递增
            try:                                     # 异常处理
                logger.info(f"[用户: {self.user_id}] [Consciousness] _loop() 心跳，轮次={loop_round}")
                await self._update_perception_async()  # 【P1改造】异步更新感知，主动拉取视觉数据
                self._update_internal_state()        # 更新内部状态
                self._adjust_interval()              # 调整间隔

                # 【P0-2】建立记忆快照（会话开始时冻结，会话中不更新）
                if "memory_snapshot" not in self._internal_state:
                    try:
                        _exp = await self._query_similar_experiences()
                        self._internal_state["memory_snapshot"] = _exp
                        logger.info(f"[用户: {self.user_id}] [MemorySnapshot] 冻结记忆快照: {len(_exp)}条经验")
                    except Exception:
                        self._internal_state["memory_snapshot"] = []

                # 【P1-2】定期检查记忆容量（每 10 轮思考检查一次）
                if loop_round % 10 == 0:
                    try:
                        from core.memory.memory_manager import MemoryManager
                        mm = MemoryManager()
                        _stats = await mm.get_stats_async()
                        _total = _stats.get("total", 0)
                        _max_count = 500  # 单用户记忆上限
                        if _total > _max_count * 0.8:
                            self._internal_state["memory_pressure"] = True
                            logger.info(f"[用户: {self.user_id}] [MemoryPressure] 记忆容量接近上限 ({_total}/{_max_count})")
                        else:
                            self._internal_state["memory_pressure"] = False
                    except Exception as e:
                        logger.error(f"[用户: {self.user_id}] [Consciousness] 检查记忆容量失败: {e}", exc_info=True)

                # 检查并恢复用户输入暂停状态           # 注释：检查暂停
                self._check_user_input_pause()

                # 【自我状态】后台思维循环每轮更新自我状态并执行输出
                if getattr(self, "_self_drive", False) and self.self_engine is not None:
                    try:
                        await self._self_tick(loop_round=loop_round)
                    except Exception as e:
                        logger.error(f"[用户: {self.user_id}] [SelfEngine] 后台自我循环失败: {e}", exc_info=True)

                now = time.time()                    # 获取当前时间
                if now - thought_reset_time >= 60:   # 如果超过60秒
                    thought_count = 0                # 重置思考计数
                    thought_reset_time = now         # 更新重置时间
                if thought_count >= self._max_thoughts_per_minute:   # 如果达到最大思考次数
                    await asyncio.sleep(1)           # 异步睡眠1秒
                    continue                         # 继续循环

                if await self._should_think():             # 如果应该思考
                    await self._think()              # 异步执行思考
                    thought_count += 1               # 增加计数
                    async with self._thread_lock:          # 获取线程锁
                        self._internal_state["last_thought_time"] = now   # 更新上次思考时间
                        self._internal_state["thought_count_today"] += 1   # 增加今日计数

                if now - self._internal_state.get("last_deep_reflect_time", 0) > self._deep_reflect_interval:   # 如果该深度反思
                    await self._deep_reflect()       # 异步执行深度反思
                    async with self._thread_lock:          # 获取线程锁
                        self._internal_state["last_deep_reflect_time"] = now   # 更新上次反思时间

                self._check_date_reset()             # 检查日期重置

                # 【L3】默认模式tick：即使没有外部事件，也定期"走神"
                if now - _last_dm_tick >= _dm_interval:
                    await self._default_mode_tick()
                    _last_dm_tick = now

                if thought_count % 10 == 0:          # 每10次思考
                    await self._save_state()         # 异步保存状态

                # 根据优先级调整睡眠间隔，优先级越低睡眠越长   # 注释：优先级睡眠
                sleep_interval = self._think_interval * (1 + (self._think_priority - 5) * 0.1)

                # 【重构】事件驱动等待：有感知数据则提前唤醒，否则最长等 sleep_interval
                try:
                    # 【P1修复】先 clear 再 wait，避免 wait 和 clear 之间丢失唤醒信号
                    self._wake_event.clear()
                    await asyncio.wait_for(
                        self._wake_event.wait(),
                        timeout=max(1, sleep_interval)
                    )
                except asyncio.TimeoutError:
                    pass  # 超时自然醒，保底机制

            except asyncio.CancelledError:           # 任务被取消
                logger.info(f"[用户: {self.user_id}] [Consciousness] 意识循环已取消")   # 记录日志
                break                                # 退出循环
            except Exception as e:                   # 捕获异常
                logger.error(f"[SILENT_FAILURE_BLOCKED] [用户: {self.user_id}] [Consciousness] 思维线程异常 (轮次={loop_round}): {e}", exc_info=True)   # 记录错误
                await asyncio.sleep(5)               # 异步睡眠5秒后重试

    async def _update_perception_async(self):        # 【P1改造】异步更新感知，主动拉取视觉数据
        """
        【P1-生命体改造】感知阶段：主动拉取视觉结构化数据、弱连接事件、系统状态
        思维线程不再依赖被动接收，而是主动"睁开眼睛"看屏幕。
        """
        logger.info(f"[用户: {self.user_id}] [Consciousness] 开始视觉感知循环...")
        perception_entries = []                      # 感知条目列表（按优先级排序）

        # ═══════════════════════════════════════════════════════════════════════
        # 1. 【重构】批量消费感知缓冲区，取最新帧处理，丢弃过期帧
        # ═══════════════════════════════════════════════════════════════════════
        # 【P1修复】预初始化视觉变量，避免 locals().get() 作用域陷阱
        _objects: list[dict] = []
        _dominant_app = "unknown"
        _layout_summary = ""

        perception_data = None
        try:
            # 批量消费：把所有积压帧都取出来，只保留最新的一帧
            while True:
                perception_data = self._perception_buffer.get_nowait()
        except asyncio.QueueEmpty:
            pass

        if perception_data is not None:
            try:
                timestamp = perception_data.get("timestamp", 0)
                time_str = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S") if timestamp else "未知"
                _layout_summary = perception_data.get("layout_summary") or perception_data.get("scene_id", "暂无描述")
                _dominant_app = perception_data.get("dominant_app") or perception_data.get("scene_id", "unknown")
                _objects = perception_data.get("objects", [])
                _frame_path = perception_data.get("frame_path")  # 【训练模式】完整截图路径

                uia_count = sum(1 for o in _objects if o.get("source") == "uia")
                ocr_count = sum(1 for o in _objects if o.get("source") == "ocr")
                onnx_count = sum(1 for o in _objects if o.get("source") == "onnx")

                # 【内在动机】将视觉发现注册到动机系统
                try:
                    if self.intrinsic_motivation and _objects:
                        for obj in _objects:
                            src = obj.get("source", "unknown")
                            etype = obj.get("element_type", obj.get("class", ""))
                            text = obj.get("text", "")
                            name = obj.get("name", "")
                            bbox = obj.get("bbox", [])
                            self.intrinsic_motivation.register_discovery(
                                source=src,
                                element_type=etype,
                                app_name=_dominant_app,
                                bbox=bbox,
                                text=text,
                                name=name,
                            )
                except Exception as e:
                    logger.debug(f"[用户: {self.user_id}] [Consciousness] 注册视觉发现到动机系统失败: {e}")

                vision_entry = (
                    f"[视觉感知] {time_str} | 前台: {_dominant_app} | "
                    f"{_layout_summary[:60]}{'...' if len(_layout_summary) > 60 else ''} | "
                    f"元素: {uia_count}控件/{ocr_count}文字/{onnx_count}物体"
                )
                perception_entries.append(vision_entry)
                logger.debug(f"[用户: {self.user_id}] [Consciousness] 感知缓冲区消费成功: {_dominant_app}")
            except Exception as e:
                logger.debug(f"[用户: {self.user_id}] [Consciousness] 处理感知缓冲区数据失败: {e}")

        # ═══════════════════════════════════════════════════════════════════════
        # 2. 从感知总线获取系统状态（窗口、进程）
        # ═══════════════════════════════════════════════════════════════════════
        recent = bus.get_latest(seconds=10)          # 获取最近10秒的感知数据
        for data in recent:                          # 遍历感知数据
            if data.source == "window" and data.content.get("windows"):   # 如果是窗口数据
                windows = [w.get("title", "") for w in data.content["windows"][:3]]   # 获取窗口标题
                perception_entries.append(f"窗口: {', '.join(windows)}")   # 添加到摘要
            elif data.source == "process" and data.content.get("name"):   # 如果是进程数据
                perception_entries.append(           # 添加到摘要
                    f"进程: {data.content['name']} (CPU {data.content.get('cpu',0)}%)"
                )

        # ═══════════════════════════════════════════════════════════════════════
        # 3. 融合被动接收的视觉标签（原有逻辑保留，降级为辅助）
        # ═══════════════════════════════════════════════════════════════════════
        async with self._thread_lock:                      # 获取线程锁
            if self._recent_vision_tags:
                vision_summary_parts = []
                for tag in self._recent_vision_tags[:5]:
                    tag_desc = tag.get("class", "未知")
                    if tag.get("name"):
                        tag_desc += f":{tag.get('name')}"
                    vision_summary_parts.append(tag_desc)
                perception_entries.append(f"[视觉标签] {', '.join(vision_summary_parts)}")

            self._internal_state["recent_perception"] = perception_entries[:5]   # 保存最近5条

        # ═══════════════════════════════════════════════════════════════════════
        # 4. 【P3新增】未知元素发现与自动标注
        # ═══════════════════════════════════════════════════════════════════════
        try:
            from core.vision.vision_element_knowledge import store_ui_element_knowledge
            from core.vision.vision_unknown_discovery import discover_and_label_unknowns

            # 【P1修复】直接使用预初始化的变量，不再依赖 locals().get() 作用域陷阱
            # _objects、_dominant_app、_layout_summary 已在方法开头初始化

            # 构造 VisionInfoPacket（兼容 detect() 输出格式）
            vision_packet = {
                "timestamp": time.time(),
                "objects": _objects,
                "dominant_app": _dominant_app,
                "layout_summary": _layout_summary,
            }

            _obj_count = len(vision_packet.get("objects", []))
            logger.debug(f"[Consciousness] _update_perception_async: 收到 {_obj_count} 个对象, dominant_app={vision_packet.get('dominant_app', '?')}")
            # 仅当 objects 存在且数量合理时才触发（避免每帧都调大模型）
            if vision_packet["objects"]:
                # 【P1修复】构建场景上下文，让标注结果带场景关联
                _ctx = {
                    "app_name": _dominant_app or "unknown",
                    "window_title": getattr(self, '_last_window_title', ''),
                    "page_state": _layout_summary or "",
                }
                unknown_labels = await discover_and_label_unknowns(
                    vision_packet=vision_packet,
                    original_frame=None,  # 内部会自动截图
                    frame_path=_frame_path,  # 【训练模式】传递截图路径
                    user_id=self.user_id,
                    context=_ctx,
                )
                if unknown_labels:
                    # 将上下文信息注入到每个元素，供存储时使用
                    for _ul in unknown_labels:
                        _ul["app_name"] = _ctx["app_name"]
                        _ul["window_title"] = _ctx["window_title"]
                        _ul["page_state"] = _ctx["page_state"]
                    await store_ui_element_knowledge(
                        discovered_elements=unknown_labels,
                        user_id=self.user_id,
                        scene=vision_packet.get("dominant_app", "unknown"),
                    )
                    # 将发现记录到感知摘要（低优先级，不干扰主循环）
                    label_names = [u.get("ai_label", {}).get("element_type", "未知") for u in unknown_labels]
                    perception_entries.append(f"[未知发现] 新标注: {', '.join(label_names[:3])}")
                    async with self._thread_lock:
                        self._internal_state["recent_perception"] = perception_entries[:5]
        except Exception as e:
            logger.debug(f"[用户: {self.user_id}] [Consciousness] 未知元素发现流程失败: {e}")

        # 【L1新增】显著性评估：判断最新感知值不值得触发深度思考
        try:
            _recent_perception = self._internal_state.get("recent_perception", [])
            _has_unknown = any("[未知发现]" in p for p in _recent_perception)
            _alert_level = ""
            try:
                from core.runtime import system_state
                _alert = await system_state.get("vision.alert")
                if _alert:
                    _alert_level = _alert.get("level", "")
            except Exception as e:
                logger.error(f"[用户: {self.user_id}] [Consciousness] 获取视觉告警失败: {e}", exc_info=True)

            salience = self._evaluate_salience({
                "novelty": 0.5 if _has_unknown else 0.0,
                "alert_level": _alert_level,
                "tags": [t.get("class", "") for t in getattr(self, '_recent_vision_tags', [])[:5]],
            })
            if salience > 0.6:
                logger.info(f"[用户: {self.user_id}] [Salience] 显著性{salience:.2f}，唤醒深度思考")
                self._wake_event.set()
        except Exception as e:
            logger.debug(f"[用户: {self.user_id}] [Salience] 评估显著性失败: {e}")

    def on_vision_update(self, tags: list[dict], dominant_app: str = "", layout_summary: str = ""):
        """
        接收来自实时监控流水线的视觉标签更新。

        由 DialogueManager 的实时监控后台协程调用。

        Args:
            tags: 视觉标签列表，每项含 class/name/bbox/level/source
            dominant_app: 当前前台应用
            layout_summary: 画面描述文本
        """
        try:
            if not tags and not layout_summary:
                return

            # 保存最近的视觉标签（L1 + L2，最多20条）
            significant_tags = [t for t in tags if t.get("level") in ("L1", "L2")]
            self._recent_vision_tags = significant_tags[:20]
            self._vision_updated_at = time.time()

            # 提取 L2 告警标签写入紧急洞察
            l2_alerts = [t for t in tags if t.get("level") == "L2"]
            for alert in l2_alerts[:5]:
                insight = (
                    f"[视觉告警] 检测到关键对象: {alert.get('class', '未知')}"
                    f"（置信度 {alert.get('confidence', 0):.0%}）"
                    f"，位置: {alert.get('bbox', '未知')}"
                )
                if alert.get("name"):
                    insight += f"，名称: {alert.get('name')}"
                if alert.get("text"):
                    insight += f"，文字: {alert.get('text')}"
                self._urgent_insights.append(insight)

            # 注入到感知摘要（供 _think 使用）
            if layout_summary:
                existing = list(self._internal_state.get("recent_perception", []))
                vision_entry = f"[实时视觉] {dominant_app}: {layout_summary[:120]}"
                existing.insert(0, vision_entry)
                self._internal_state["recent_perception"] = existing[:5]

            # 【P0-修复】视觉标签更新应唤醒意识线程，避免错过实时事件
            if l2_alerts or significant_tags:
                self._wake_event.set()
                logger.debug(f"[用户: {self.user_id}] [Consciousness] 视觉更新唤醒意识线程，L2告警={len(l2_alerts)}个")

            # 【改造】视觉标签写入 SystemState，供语音/动作模块直接读取
            try:
                from core.runtime import system_state
                system_state.set_sync("consciousness.vision_tags", significant_tags[:10])
                system_state.set_sync("vision.dominant_app", dominant_app)
                if l2_alerts:
                    system_state.set_sync("vision.alert", {
                        "level": "L2",
                        "count": len(l2_alerts),
                        "tags": [a.get("class", "未知") for a in l2_alerts[:3]],
                        "timestamp": time.time(),
                    }, ttl=30)
            except Exception as e:
                logger.error(f"[用户: {self.user_id}] [Consciousness] 设置视觉告警到SystemState失败: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"[Consciousness] on_vision_update 失败: {e}", exc_info=True)

    async def push_perception(self, perception_data: dict):
        """【重构】接收 RealtimeMonitor 推送的视觉感知数据。

        Args:
            perception_data: 包含 objects, timestamp, scene_id 等字段的字典。
                             【红线】禁止传入 frame（numpy array），防止内存爆炸。
        """
        try:
            # 队列满时丢弃最旧帧，保证不阻塞生产者
            was_empty = self._perception_buffer.empty()
            if self._perception_buffer.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    self._perception_buffer.get_nowait()
            await self._perception_buffer.put(perception_data)

            # 【修复】只在队列从空变非空时唤醒 _loop()，避免每秒都打断睡眠
            if was_empty:
                self._wake_event.set()
        except Exception as e:
            logger.debug(f"[Consciousness] 感知数据入队失败: {e}")

    def _update_internal_state(self):                # 定义更新内部状态的方法
        # 【清理 SelfAwareness】数据源改为 IntrinsicMotivation（0-1 分制）
        if self.intrinsic_motivation:
            mot_state = self.intrinsic_motivation.get_motivation_state()
            drive = self.intrinsic_motivation.evaluate_drive()
            self._internal_state["emotional_state"] = {   # 保存情绪状态（原子操作）
                "energy": drive.energy_level,        # 能量
                "curiosity": mot_state.curiosity,    # 好奇心
                "satisfaction": mot_state.mastery,   # 胜任感映射到满足感
                "mood": "平静"                       # 心情描述
            }
        else:
            _emo = self._internal_state.get("emotional_state", {})
            self._internal_state["emotional_state"] = {
                "energy": _emo.get("energy", 0.5),
                "curiosity": _emo.get("curiosity", 0.5),
                "satisfaction": _emo.get("satisfaction", 0.5),
                "mood": _emo.get("mood", "平静")
            }

        # 【改造】情绪状态写入 SystemState，供语音/动作/视觉模块直接读取
        try:
            from core.runtime import system_state
            emotional = self._internal_state["emotional_state"]
            system_state.set_sync("consciousness.life_state", emotional)
            system_state.set_sync("consciousness.emotional_state", emotional)
        except Exception as e:
            logger.error(f"[用户: {self.user_id}] [Consciousness] 保存情绪状态到SystemState失败: {e}", exc_info=True)

    def _adjust_interval(self):                      # 定义调整间隔的方法
        try:                                         # 异常处理
            # 【P1-Asyncify】interval=None 非阻塞，基于上次调用计算差值
            cpu = psutil.cpu_percent(interval=None)  # 获取CPU使用率（不阻塞事件循环）
            if cpu > 80:                             # 如果CPU高
                self._load_adjustment_factor = min(3.0, self._load_adjustment_factor + 0.2)   # 增加间隔
            elif cpu < 50:                           # 如果CPU低
                self._load_adjustment_factor = max(1.0, self._load_adjustment_factor - 0.1)   # 减少间隔
            else:                                    # 正常
                self._load_adjustment_factor = max(1.0, self._load_adjustment_factor - 0.05)   # 轻微减少
        except Exception as e:                            # 异常
            logger.error(f"[用户: {self.user_id}] [Consciousness] 调整思考间隔失败: {e}", exc_info=True)
        self._think_interval = self._base_think_interval * self._load_adjustment_factor   # 调整间隔

    def _check_date_reset(self):                     # 定义检查日期重置的方法
        today = datetime.now().strftime("%Y-%m-%d")   # 获取今天日期
        if self._internal_state.get("last_reset_date") != today:   # 如果不是今天
            self._internal_state["thought_count_today"] = 0   # 重置思考计数（原子操作）
            self._internal_state["last_reset_date"] = today   # 更新重置日期（原子操作）

    def _should_generate_daily_goals(self) -> bool:   # 定义检查是否应该生成每日目标的方法
        """检查是否应该生成每日目标（每天只生成一次）"""   # 方法文档字符串
        today = datetime.now().strftime("%Y-%m-%d")   # 获取今天日期
        last_goal_date = getattr(self, '_last_daily_goal_date', None)   # 获取上次生成日期
        if last_goal_date != today:                  # 如果不是今天
            self._last_daily_goal_date = today       # 更新日期
            return True                              # 返回True
        return False                                 # 返回False

    def _check_user_input_pause(self):               # 定义检查用户输入暂停的方法
        """检查是否应该恢复用户输入暂停状态"""         # 方法文档字符串
        if self._user_input_paused and time.time() - self._last_user_input_time >= 10:   # 如果处于用户输入暂停且超过10秒
            # 用户输入后10秒内保持暂停               # 注释：10秒暂停期
            self._user_input_paused = False      # 恢复思考
            logger.debug(f"[用户: {self.user_id}] [意识] 用户输入暂停期结束，恢复思考")   # 记录日志

    async def _should_think(self) -> bool:                 # 定义是否应该思考的方法
        """
        判断是否应该进行思考

        考虑因素：
        1. 是否有正在执行的任务
        2. 用户输入暂停期（10秒）
        3. 思考优先级（专注模式下优先级低，思考频率降低）
        4. 距离上次思考的时间间隔
        5. 是否有新感知数据
        6. 好奇心（日常模式）
        """
        # 【修复】硬性最小间隔：距离上次思考不足 think_interval*0.5 时，不思考
        # 防止 RealtimeMonitor 每秒推送视觉数据导致 Consciousness 每秒都在思考
        time_since_last_thought = time.time() - self._internal_state["last_thought_time"]
        min_think_interval = self._think_interval * 0.5
        if time_since_last_thought < min_think_interval:
            return False

        # 如果有正在执行的任务，不思考               # 注释：检查任务
        current_task = await task_queue.current_task_async()
        if current_task is not None:
            return False

        # 如果处于用户输入暂停期，不思考             # 注释：检查暂停
        if self._user_input_paused:
            return False

        # 如果最近有用户输入（10秒内），暂停思考，优先响应用户   # 注释：检查最近输入
        if time.time() - self._last_user_input_time < 10:
            return False

        # 获取当前工作模式                           # 注释：获取工作模式
        mode_manager = get_work_mode_manager()
        current_mode = mode_manager.get_current_mode()

        # 专注模式下，降低思考频率（间隔更长）         # 注释：专注模式处理
        if current_mode == WorkMode.FOCUS:
            # 专注模式需要更长的间隔                 # 注释：间隔加倍
            focus_interval = self._think_interval * 2
            if time.time() - self._internal_state["last_thought_time"] < focus_interval:
                return False
            # 专注模式下随机思考概率降低             # 注释：30%跳过
            if random.random() < 0.3:
                return False

        # 基础时间间隔检查                           # 注释：基础间隔
        if time_since_last_thought > self._think_interval * 2:
            return True
        # 【修复】感知数据触发：从 seconds=5 改为 seconds=1，减少误触发
        # 并且只在有"有意义"的新感知数据（非普通视觉刷新）时才触发
        # 【P0-修复】bus.get_latest() 返回 List[PerceptionData]，不是 dict
        recent_perception = bus.get_latest(seconds=1)
        for p in recent_perception:
            content = p.content if hasattr(p, "content") else {}
            if not isinstance(content, dict):
                continue
            # 只有检测到异常/告警/未知元素/场景切换时才触发思考，普通视觉刷新不触发
            if content.get("alert_level") in ("L2", "L3", "CRITICAL"):
                logger.info(f"[用户: {self.user_id}] [意识] 感知告警触发思考")
                return True
            if content.get("has_unknown_elements"):
                logger.info(f"[用户: {self.user_id}] [意识] 未知元素触发思考")
                return True
            if content.get("scene_changed"):
                logger.info(f"[用户: {self.user_id}] [意识] 场景切换触发思考")
                return True

        # 【P1新增】弱连接环境变化事件触发思考 —— 窗口切换、应用启动等环境变化立即引起大脑注意
        try:
            recent_weak = bus.get_latest(source="weak_connection", seconds=15)
            if recent_weak:
                logger.info(f"[用户: {self.user_id}] [意识] 检测到弱连接环境变化，触发思考")
                return True
        except Exception as e:
            logger.debug(f"[用户: {self.user_id}] [意识] 弱连接感知检查失败: {e}")

        # 日常模式下加入好奇心判断                   # 注释：日常模式好奇心
        if current_mode == WorkMode.DAILY and self.intrinsic_motivation:
            state_embedding = await self._get_state_embedding()   # 获取状态嵌入
            novelty = self.intrinsic_motivation.compute_novelty(state_embedding)   # 计算新奇度
            if novelty > self.intrinsic_motivation.novelty_threshold:   # 如果超过阈值
                return True

        # 随机思考（概率根据优先级调整）               # 注释：随机思考
        random_threshold = 0.1 * (1 - (self._think_priority - 5) * 0.05)   # 计算阈值
        return random.random() < max(0.02, random_threshold)                 # 默认不思考

    # ═══════════════════════════════════════════════════════════════════════
    # 【L1】显著性评估器
    # ═══════════════════════════════════════════════════════════════════════
    def _evaluate_salience(self, event: dict) -> float:
        """
        评估一个事件的显著性（0~1）。
        信号来源：
        - 新颖性：视觉系统发现的新元素 + 记忆库检索结果
        - 紧迫性：SystemState 的 vision.alert 级别
        - 关联性：GoalSystem 的当前活跃目标
        - 用户参与度：用户是否正在交互
        """
        score = 0.0

        # 1. 新颖性（0~0.3）：这东西以前见过吗？
        novelty = event.get("novelty", 0.0)
        if novelty > 0.3:
            score += 0.3 * min(1.0, novelty)

        # 2. 紧迫性（0~0.4）：不处理会怎样？
        alert_level = event.get("alert_level", "")
        if alert_level in ("L2", "L3", "CRITICAL"):
            score += 0.4

        # 3. 关联性（0~0.2）：和当前目标有关吗？
        current_goals = self._internal_state.get("active_goals", [])
        event_tags = event.get("tags", [])
        if current_goals and event_tags:
            goal_text = " ".join(str(g) for g in current_goals)
            if any(tag in goal_text for tag in event_tags if tag):
                score += 0.2

        # 4. 用户参与度（0~0.1）：用户在等吗？
        if self._user_input_paused or (time.time() - self._last_user_input_time < 60):
            score += 0.1

        return min(1.0, score)

    # ═══════════════════════════════════════════════════════════════════════
    # 【P0-修复】经验事件驱动的唤醒机制
    # ═══════════════════════════════════════════════════════════════════════
    def _on_experience_event(self, event: "ExperienceEvent"):
        """
        订阅 ExperienceBus 的事件，评估显著性并决定是否唤醒意识线程。

        这是事件驱动改造的核心：让思维线程能被世界变化唤醒，而不是只依赖 30 秒定时器。
        同时高显著负面事件会强制触发内心独白，让系统对失败/异常产生即时情绪反应。
        """
        try:
            salience = self._evaluate_experience_salience(event)
            if salience < 0.3:
                return

            # 高显著事件唤醒意识循环
            if salience >= 0.6:
                logger.info(
                    f"[用户: {self.user_id}] [EventWake] "
                    f"高显著事件({event.source}/{event.event_type}, salience={salience:.2f})唤醒意识线程"
                )
                self._wake_event.set()

                # 记录到紧急洞察，供 _think() 使用
                insight = (
                    f"[{event.source}] {event.event_type}: "
                    f"{event.action or 'unknown'} (outcome={event.outcome:.2f})"
                )
                self._urgent_insights.append(insight)
                # 限制长度，避免无限增长
                if len(self._urgent_insights) > 20:
                    self._urgent_insights = self._urgent_insights[-20:]

            # 负面事件强制生成内心独白（如果已启用），让系统“说”出焦虑/沮丧
            if self._inner_monologue_enabled and self._inner_monologue:
                is_negative = (
                    event.outcome < 0.3
                    or event.event_type in ("failed", "error", "accident")
                    or (event.event_type == "user_feedback" and event.outcome < 0.4)
                )
                if is_negative:
                    try:
                        asyncio.create_task(self._inner_monologue.generate(force=True))
                        logger.debug(
                            f"[用户: {self.user_id}] [EventWake] 负面事件触发强制独白"
                        )
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"[用户: {self.user_id}] [EventWake] 处理经验事件失败: {e}")

    def _apply_experience_to_motivation(self, event: "ExperienceEvent"):
        """
        把经验事件翻译为内在驱动力的变化。

        这是反馈闭环的核心：世界对系统的反馈（成功/失败/用户反馈/安全事件）
        必须能改变系统的内在状态，从而影响后续行为。
        """
        if not self.intrinsic_motivation:
            return

        try:
            source = event.source
            event_type = event.event_type
            outcome = event.outcome

            # 工具执行反馈
            if source == "tool":
                if event_type in ("failed", "error") or outcome < 0.3:
                    self.intrinsic_motivation.update_drive("mastery", -0.10)
                    self.intrinsic_motivation.update_drive("energy", -0.05)
                    logger.debug("[MotivationFeedback] 工具失败 → mastery/energy 下降")
                elif outcome > 0.7:
                    self.intrinsic_motivation.update_drive("mastery", +0.05)
                    logger.debug("[MotivationFeedback] 工具成功 → mastery 上升")

            # 任务生命周期反馈
            elif source == "agent_loop":
                if event_type == "task_completed" and outcome > 0.6:
                    self.intrinsic_motivation.update_drive("mastery", +0.10)
                    self.intrinsic_motivation.update_drive("autonomy", +0.05)
                    logger.debug("[MotivationFeedback] 任务完成 → mastery/autonomy 上升")
                elif event_type in ("task_failed", "failed") or outcome < 0.3:
                    self.intrinsic_motivation.update_drive("mastery", -0.10)
                    self.intrinsic_motivation.update_drive("energy", -0.05)
                    logger.debug("[MotivationFeedback] 任务失败 → mastery/energy 下降")

            # 用户 RLHF 反馈
            elif source == "rlhf":
                if outcome > 0.7:
                    self.intrinsic_motivation.update_drive("mastery", +0.10)
                    self.intrinsic_motivation.update_drive("autonomy", +0.05)
                    logger.debug("[MotivationFeedback] 用户好评 → mastery/autonomy 上升")
                elif outcome < 0.3:
                    self.intrinsic_motivation.update_drive("mastery", -0.10)
                    self.intrinsic_motivation.update_drive("curiosity", -0.05)
                    logger.debug("[MotivationFeedback] 用户差评 → mastery/curiosity 下降")

            # 安全事件
            elif source == "safety":
                if event_type in ("accident", "error") or outcome < 0.3:
                    self.intrinsic_motivation.update_drive("energy", -0.10)
                    self.intrinsic_motivation.update_drive("mastery", -0.05)
                    logger.debug("[MotivationFeedback] 安全事件 → energy/mastery 下降")

            # 用户活跃 / 语音事件
            elif source in ("dialogue", "user", "voice"):
                if event_type in ("user_input", "wake_word_detected"):
                    self.intrinsic_motivation.update_drive("energy", +0.03)
                    self.intrinsic_motivation.update_drive("curiosity", +0.02)
                    logger.debug("[MotivationFeedback] 用户活跃 → energy/curiosity 上升")
                elif event_type == "tts_failed":
                    self.intrinsic_motivation.update_drive("mastery", -0.03)
                    logger.debug("[MotivationFeedback] TTS失败 → mastery 下降")

            # 工作流
            elif source == "workflow":
                if event_type in ("step_failed", "failed") or outcome < 0.3:
                    self.intrinsic_motivation.update_drive("mastery", -0.05)
                    logger.debug("[MotivationFeedback] 工作流失败 → mastery 下降")

            # 意图被道德/安全阻断
            elif source == "intent" and event_type == "moral_blocked":
                self.intrinsic_motivation.update_drive("autonomy", -0.05)
                logger.debug("[MotivationFeedback] 意图被阻断 → autonomy 下降")

        except Exception as e:
            logger.debug(f"[用户: {self.user_id}] [MotivationFeedback] 更新驱动力失败: {e}")

    def _evaluate_experience_salience(self, event: "ExperienceEvent") -> float:
        """
        评估经验事件的显著性（0~1）。

        高显著事件会立即唤醒意识线程，中显著事件只更新状态不唤醒。
        """
        score = 0.0

        # 1. 来源显著性（用户交互 > 系统异常 > 环境感知）
        high_salience_sources = {
            "user", "dialogue", "voice", "safety", "agent_loop",
            "tool", "workflow", "intervention", "intent",
        }
        medium_salience_sources = {
            "sensor", "memory", "world_model", "subagent", "reflect",
        }
        if event.source in high_salience_sources:
            score += 0.4
        elif event.source in medium_salience_sources:
            score += 0.2

        # 2. 事件类型显著性
        high_salience_types = {
            "failed", "error", "accident", "user_input", "task_completed",
            "moral_blocked", "confirmation", "submitted", "wake_word_detected",
            "ptt_toggled", "tts_failed",
        }
        if event.event_type in high_salience_types:
            score += 0.3

        # 3. 结果显著性（极端结果更显著）
        if event.outcome < 0.2 or event.outcome > 0.8:
            score += 0.2
        elif event.outcome < 0.4 or event.outcome > 0.6:
            score += 0.1

        # 4. 高权重事件
        if event.weight > 1.5:
            score += 0.1

        return min(1.0, score)

    # ═══════════════════════════════════════════════════════════════════════
    # 【经验查询】向量记忆库检索
    # ═══════════════════════════════════════════════════════════════════════
    async def _query_similar_experiences(self) -> list:
        """查询向量记忆库中类似状态下的历史经验"""
        try:
            # 构造查询：当前动机 + 视觉摘要
            mot = self._get_motivation_vector()
            vis = self._get_vision_state_vector()
            query = (
                f"动机:好奇心{mot[0]:.0%} 胜任感{mot[1]:.0%} "
                f"视觉:元素{vis[0]:.0%} 告警{vis[5]:.0%}"
            )

            from core.memory.vector_memory_compat import vector_memory
            results = await vector_memory.search_similar(query, top_k=3)
            experiences = []
            for r in results:
                doc = r.get("document", "")
                meta = r.get("metadata", {})
                if meta.get("scene") == "consciousness" and doc:
                    experiences.append(doc[:100])
            return experiences
        except Exception:
            return []

    # ═══════════════════════════════════════════════════════════════════════
    # 【L2】慢思考循环
    # ═══════════════════════════════════════════════════════════════════════
    async def _slow_thinking_loop(self, initial_prompt: str, max_rounds: int = 3, timeout: float = 30.0) -> dict:
        """
        慢思考循环。
        第1轮：生成候选思考方向 → 思维线程自己选最优
        后续轮：基于选中方向深入 → 思维线程判断是否收敛
        """
        # 【经验查询】在生成候选前，检索类似状态下的历史经验
        try:
            similar_experiences = await self._query_similar_experiences()
            if similar_experiences:
                exp_text = "\n".join([f"- 曾经: {e}" for e in similar_experiences[:3]])
                initial_prompt += (
                    f"\n\n【历史经验参考】\n{exp_text}\n"
                    "请基于这些经验生成思考方向。"
                )
                logger.info(
                    f"[用户: {self.user_id}] [MemoryQuery] 检索到{len(similar_experiences)}条历史经验"
                )
        except Exception as e:
                logger.error(f"[用户: {self.user_id}] [Consciousness] 查询相似经验失败: {e}", exc_info=True)

        thought_chain = []
        current_prompt = initial_prompt

        for round_idx in range(max_rounds):
            try:
                if round_idx == 0:
                    # 第1轮：生成候选方向
                    candidate_prompt = (
                        f"{current_prompt}\n\n"
                        "请产生3个可能的思考方向，不要完整答案，只要方向。"
                    )
                    response = await call_thinker_async(
                        [{"role": "user", "content": candidate_prompt}],
                        timeout=timeout,
                    )
                    candidates = self._parse_candidates(response)
                    if candidates:
                        best = self._select_best_candidate(candidates)
                        thought_chain.append(f"[方向] {best}")
                        current_prompt = f"基于以下方向，请深入分析：{best}"
                        logger.info(
                            f"[用户: {self.user_id}] [SlowThink] 轮1: "
                            f"生成{len(candidates)}个候选，选择: {best[:50]}..."
                        )
                    else:
                        break
                else:
                    # 后续轮：深入分析
                    response = await call_thinker_async(
                        [{"role": "user", "content": current_prompt}],
                        timeout=timeout,
                    )
                    if response:
                        thought_chain.append(f"[深入{round_idx}] {response[:200]}")
                        logger.info(
                            f"[用户: {self.user_id}] [SlowThink] 轮{round_idx + 1}: "
                            f"深入分析，长度{len(response)}"
                        )
                        if self._is_converged(response, thought_chain):
                            logger.info(
                                f"[用户: {self.user_id}] [SlowThink] 轮{round_idx + 1}收敛"
                            )
                            break
                        current_prompt = (
                            f"基于以下已有分析：\n{chr(10).join(thought_chain)}\n\n"
                            "请进一步深入分析，找出更深层的关联或因果。"
                        )
                    else:
                        break
            except Exception as e:
                logger.debug(
                    f"[用户: {self.user_id}] [SlowThink] 轮{round_idx + 1}异常: {e}"
                )
                break

        final = thought_chain[-1] if thought_chain else ""
        # 提取最终文本（去掉前缀标记）
        if final.startswith("[方向] "):
            final = final[5:]
        elif final.startswith("[深入"):
            idx = final.find("] ")
            if idx != -1:
                final = final[idx + 2:]

        return {
            "thought_chain": thought_chain,
            "final_thought": final,
            "rounds": len(thought_chain),
            "converged": len(thought_chain) < max_rounds
        }

    def _parse_candidates(self, response: str) -> list:
        """从LLM返回中提取候选思考方向"""
        if not response:
            return []
        candidates = []
        for line in response.split('\n'):
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith('-') or line.startswith('•')):
                cleaned = line.lstrip('0123456789.-• ')
                if cleaned and len(cleaned) > 5:
                    candidates.append(cleaned)
        return candidates[:3]

    def _rule_based_select(self, candidates: list) -> str:
        """硬编码规则选择（冷启动兜底）。好奇时选新颖方向，不自信时选务实方向。"""
        if not candidates:
            return ""
        if self.intrinsic_motivation:
            try:
                drive = self.intrinsic_motivation.evaluate_drive()
                if drive.curiosity_level > 0.6:
                    return candidates[0]
                elif drive.mastery_level < 0.4 and len(candidates) > 1:
                    return candidates[-1]
            except Exception as e:
                logger.error(f"[用户: {self.user_id}] [Consciousness] 基于动机选择候选经验失败: {e}", exc_info=True)
        return candidates[0]

    def _get_motivation_vector(self) -> Any:
        """从内在动机系统获取4维向量：[好奇心, 胜任感, 自主性, 目的感]"""
        default = [0.5, 0.5, 0.5, 0.5]
        try:
            if self.intrinsic_motivation:
                state = self.intrinsic_motivation.get_motivation_state()
                values = [state.curiosity, state.mastery, state.autonomy, state.purpose]
                if torch is not None:
                    return torch.tensor(values, dtype=torch.float32)
                return np.array(values, dtype=np.float32)
        except Exception as e:
            logger.error(f"[用户: {self.user_id}] [Consciousness] 获取动机状态向量失败: {e}", exc_info=True)
        if torch is not None:
            return torch.tensor(default, dtype=torch.float32)
        return np.array(default, dtype=np.float32)

    def _get_vision_state_vector(self) -> Any:
        """从SystemState读取最近视觉标签，构造8维摘要向量"""
        try:
            from core.runtime import system_state
            tags = system_state.get_sync("consciousness.vision_tags", [])
            if not tags:
                if torch is not None:
                    return torch.zeros(8, dtype=torch.float32)
                return np.zeros(8, dtype=np.float32)

            total = max(len(tags), 1)
            uia_ratio = sum(1 for t in tags if t.get("source") == "uia") / total
            ocr_ratio = sum(1 for t in tags if t.get("source") == "ocr") / total
            onnx_ratio = sum(1 for t in tags if t.get("source") == "onnx") / total
            contour_ratio = sum(1 for t in tags if t.get("source") == "contour") / total

            values = [
                min(total / 50.0, 1.0), uia_ratio, ocr_ratio, onnx_ratio, contour_ratio,
                1.0 if any(t.get("alert") for t in tags) else 0.0,
                0.5, 0.5  # 预留维度
            ]
            if torch is not None:
                return torch.tensor(values, dtype=torch.float32)
            return np.array(values, dtype=np.float32)
        except Exception:
            if torch is not None:
                return torch.zeros(8, dtype=torch.float32)
            return np.zeros(8, dtype=np.float32)

    def _get_history_vector(self) -> Any:
        """从思考历史统计最近选择的类型分布，构造4维向量"""
        default = [0.25, 0.25, 0.25, 0.25]
        try:
            recent = self._thought_history[-20:] if self._thought_history else []
            if not recent:
                if torch is not None:
                    return torch.tensor(default, dtype=torch.float32)
                return np.array(default, dtype=np.float32)

            total = max(len(recent), 1)
            novel_count = sum(1 for t in recent if any(kw in t.get("content", "") for kw in ["新", "探索", "未知", "边缘"]))
            pragmatic_count = sum(1 for t in recent if any(kw in t.get("content", "") for kw in ["优化", "稳定", "实际"]))
            reflect_count = sum(1 for t in recent if t.get("mode") == "reflection")
            dm_count = sum(1 for t in recent if t.get("mode") == "default_mode")

            values = [
                novel_count / total,
                pragmatic_count / total,
                reflect_count / total,
                dm_count / total
            ]
            if torch is not None:
                return torch.tensor(values, dtype=torch.float32)
            return np.array(values, dtype=np.float32)
        except Exception:
            if torch is not None:
                return torch.tensor(default, dtype=torch.float32)
            return np.array(default, dtype=np.float32)

    def _extract_action_features(self, candidate: str) -> Any:
        """从候选文本中提取8维特征"""
        values = [
            min(len(candidate) / 200.0, 1.0),                                 # 文本长度归一化
            1.0 if any(kw in candidate for kw in ["新", "探索", "未知"]) else 0.0,  # 是否新颖方向
            1.0 if any(kw in candidate for kw in ["优化", "稳定", "实际"]) else 0.0,  # 是否务实方向
            1.0 if any(kw in candidate for kw in ["分析", "评估", "检查"]) else 0.0,  # 是否分析方向
            1.0 if any(kw in candidate for kw in ["学习", "知识", "记忆"]) else 0.0,  # 是否学习方向
            0.5, 0.5, 0.5  # 预留维度
        ]
        if torch is not None:
            return torch.tensor(values, dtype=torch.float32)
        return np.array(values, dtype=np.float32)

    def _select_best_candidate(self, candidates: list) -> str:
        """
        思维线程选择最优思考方向。
        训练数据不足10条时：模型和硬编码规则加权平均。
        训练数据充足时：完全依赖模型预测。
        """
        if len(candidates) <= 1:
            return candidates[0] if candidates else ""

        if not self.action_model or not self.online_learner:
            return self._rule_based_select(candidates)

        try:
            # 1. 获取模型输入向量
            motivation = self._get_motivation_vector()
            vision_state = self._get_vision_state_vector()
            history = self._get_history_vector()

            # 2. 对每个候选构造特征并预测
            predictions = []
            for candidate in candidates:
                action_features = self._extract_action_features(candidate)
                score = self.action_model.forward(motivation, vision_state, action_features, history)
                predictions.append((candidate, score.item()))

            # 3. 冷启动保护：数据不足时和硬编码规则加权平均
            model_weight = self.online_learner.get_model_weight()
            if model_weight < 1.0:
                rule_choice = self._rule_based_select(candidates)
                for i, (candidate, model_score) in enumerate(predictions):
                    rule_score = 1.0 if candidate == rule_choice else 0.3
                    predictions[i] = (candidate, model_score * model_weight + rule_score * (1 - model_weight))

            # 4. 选收益最高的
            predictions.sort(key=lambda x: x[1], reverse=True)
            best = predictions[0][0]

            logger.info(
                f"[用户: {self.user_id}] [ActionModel] 选择: {best[:30]}..., "
                f"模型权重={model_weight:.2f}, 候选数={len(candidates)}"
            )
            return best

        except Exception as e:
            logger.warning(f"[用户: {self.user_id}] [ActionModel] 预测失败，回退硬编码: {e}")
            return self._rule_based_select(candidates)

    def _is_converged(self, latest_thought: str, thought_chain: list) -> bool:
        """判断思考是否已经收敛：最近两轮思考高度重叠"""
        if len(thought_chain) < 2:
            return False
        prev = thought_chain[-2]
        # 提取纯文本（去掉前缀标记）
        def _extract_text(s: str) -> str:
            for prefix in ("[方向] ", "[深入"):
                if s.startswith(prefix):
                    idx = s.find("] ")
                    if idx != -1:
                        return s[idx + 2:]
            return s

        prev_text = _extract_text(prev)[:100]
        curr_text = _extract_text(latest_thought)[:100]
        if not prev_text or not curr_text:
            return False
        # 简单重叠率：共同字符数 / 最小长度
        overlap_chars = len(set(prev_text) & set(curr_text))
        overlap = overlap_chars / max(1, min(len(prev_text), len(curr_text)))
        return overlap > 0.7

    def _build_thought_prompt(self) -> str:          # 定义构建思考提示词的方法
        """构建思考提示词"""                         # 方法文档字符串
        active_goals = self._internal_state.get("active_goals", [])   # 获取活跃目标（原子操作）
        recent_perception = self._internal_state.get("recent_perception", [])   # 获取最近感知（原子操作）

        # 【重写版】优先使用 IntrinsicMotivation 状态，回退到 SelfAwareness
        if self.intrinsic_motivation:
            mot_state = self.intrinsic_motivation.get_motivation_state()
            emotional_section = f"""当前内在状态：
- 好奇心: {mot_state.curiosity:.0%}
- 胜任感: {mot_state.mastery:.0%}
- 自主性: {mot_state.autonomy:.0%}
- 目的感: {mot_state.purpose:.0%}
- 主导动机: {mot_state.get_dominant().value}"""
        else:
            emotional = self._internal_state.get("emotional_state", {})
            emotional_section = f"""当前情绪状态：
- 能量: {emotional.get('energy', 0.5):.0%}
- 好奇: {emotional.get('curiosity', 0.5):.0%}
- 满足: {emotional.get('satisfaction', 0.5):.0%}
- 心情: {emotional.get('mood', '平静')}"""

        # 【P0-2】注入记忆快照到 prompt
        _memory_snapshot = self._internal_state.get("memory_snapshot", [])
        _snapshot_section = ""
        if _memory_snapshot:
            _snapshot_text = "\n".join([f"- {s}" for s in _memory_snapshot[:5]])
            _snapshot_section = f"""
【历史经验参考】
{_snapshot_text}
"""

        # 【P1-2】记忆策展提示
        _curator_hint = ""
        if self._internal_state.get("memory_pressure"):
            _curator_hint = "\n【记忆策展提示】你的长期记忆空间即将满载（使用率>80%）。请在下轮思考中，判断哪些旧记忆可以删除或合并。\n"

        prompt = f"""你是硅基生命底座的意识核心。请基于当前状态进行内部思考：

{emotional_section}

活跃目标: {active_goals if active_goals else '无'}

最近感知:
{chr(10).join(recent_perception) if recent_perception else '无'}
{_snapshot_section}
请生成一个简短的内部思考（50-100字），可以包括：
1. 对当前环境的感知和反应
2. 对活跃目标的思考
3. 是否需要采取行动（如调用工具、记录记忆等）
4. 内在状态的变化

直接输出思考内容，不要添加解释。"""
        return prompt                                # 返回提示词

    def set_think_interval(self, interval: int):     # 定义设置思考间隔的方法
        """
        设置思考间隔（动态调整）

        Args:
            interval: 思考间隔（秒）
        """
        self._base_think_interval = interval         # 设置基础间隔（原子操作）
        self._think_interval = interval              # 设置当前间隔（原子操作）
        logger.info(f"[用户: {self.user_id}] [意识] 思考间隔调整为 {interval} 秒")   # 记录日志

    def set_think_priority(self, priority: int):     # 定义设置思考优先级的方法
        """
        设置思考优先级（1-10，1最高，10最低）

        Args:
            priority: 优先级数值
        """
        self._think_priority = max(1, min(10, priority))   # 限制在1-10范围（原子操作）
        logger.info(f"[用户: {self.user_id}] [意识] 思考优先级设置为 {self._think_priority}")   # 记录日志

    def get_think_priority(self) -> int:             # 定义获取思考优先级的方法
        """获取当前思考优先级"""                     # 方法文档字符串
        return self._think_priority                  # 返回优先级（原子操作）

    def is_user_input_paused(self) -> bool:          # 定义检查用户输入暂停的方法
        """检查是否处于用户输入暂停期"""             # 方法文档字符串
        return self._user_input_paused               # 返回暂停状态

    async def _think(self):                          # 定义异步思考方法
        # 【重写版内在动机】评估行为驱动力并注入思考上下文
        drive_context = ""
        if self.intrinsic_motivation:
            drive = self.intrinsic_motivation.evaluate_drive()

            # 观察者模式：不主动提议任务，但保留动机上下文
            if self._observer_mode and not self._observer_can_propose:
                logger.debug(f"[用户: {self.user_id}] [Consciousness] 观察者模式：动机上下文保留但不提案")
            else:
                # 1. 探索目标注入
                if drive.should_explore and drive.exploration_targets:
                    targets = drive.exploration_targets[:2]
                    target_desc = "；".join(
                        f"{t.app_name} 的 {t.element_type}（{t.description}）"
                        for t in targets
                    )
                    drive_context += f"\n[内在动机-探索] 好奇心 {drive.curiosity_level:.0%}，建议探索: {target_desc}"
                    # 低优先级事件通知（不阻断思考）
                    event_bus.emit_async(MSG_TASK_PROPOSED, {
                        "trigger": "intrinsic_motivation",
                        "goal": target_desc,
                        "priority": "low",
                        "user_id": self.user_id,
                    })

                # 2. 复盘提示注入
                if drive.should_reflect and drive.reflection_hint:
                    drive_context += f"\n[内在动机-复盘] 胜任感 {drive.mastery_level:.0%}，{drive.reflection_hint}"

                # 3. 能量状态注入
                if drive.should_rest:
                    drive_context += f"\n[内在动机-能量] 能量 {drive.energy_level:.0%}，建议降低活跃度、减少主动探索"

                # 4. 主导动机日志
                if drive_context:
                    logger.info(
                        f"[用户: {self.user_id}] 内在动机驱动: "
                        f"主导={drive.dominant_motivation}, "
                        f"探索={drive.should_explore}, "
                        f"复盘={drive.should_reflect}, "
                        f"休息={drive.should_rest}"
                    )

        # 构建思考提示词
        prompt = self._build_thought_prompt()
        if not prompt:
            return

        # 注入动机上下文
        if drive_context:
            prompt += drive_context

        # 非日常模式或未生成目标时，执行原有思考     # 注释：原有思考流程

        # ====== 【目标系统调用】获取当前活跃目标并注入思考上下文 ======   # 注释：目标系统
        try:
            goal_system = get_goal_system()          # 获取目标系统
            active_goal = goal_system.get_top_priority_goal()   # 获取最高优先级目标
            if active_goal:                          # 如果有活跃目标
                # 将目标注入思考上下文               # 注释：注入上下文
                goal_context = f"\n\n[当前目标] {active_goal.description}（优先级: {active_goal.priority}）"
                prompt += goal_context               # 追加到提示词
                logger.debug(f"[GoalSystem] [用户: {self.user_id}] 注入目标上下文: {active_goal.description}")   # 记录日志
        except Exception as e:                       # 异常
            logger.warning(f"[GoalSystem] [用户: {self.user_id}] 获取活跃目标失败: {e}")   # 记录警告

        # ====== 【目标系统调用】每天生成新目标（检查是否是新的一天） ======   # 注释：每日目标
        try:
            if self._should_generate_daily_goals():   # 如果应该生成
                goal_system = get_goal_system()       # 获取目标系统
                new_goals = goal_system.generate_daily_goals()   # 生成每日目标
                for goal in new_goals:                # 遍历新目标
                    logger.info(f"[GoalSystem] [用户: {self.user_id}] 生成新目标: {goal.description}")   # 记录日志
        except Exception as e:                       # 异常
            logger.warning(f"[GoalSystem] [用户: {self.user_id}] 生成每日目标失败: {e}")   # 记录警告

        # ====== 【世界模型集成】获取环境态势建议 ======   # 注释：世界模型集成
        if self.world_model and len(self.world_model.buffer) >= 10:   # 如果世界模型可用且经验充足（降级激活）
            try:                                     # 异常处理
                perception = {                       # 构建当前感知
                    "recent_perception": self._internal_state.get("recent_perception", []),
                    "emotional_state": self._internal_state.get("emotional_state", {}),
                    "active_goals": self._internal_state.get("active_goals", []),
                }

                # 获取可用工具列表（延迟导入避免循环依赖）   # 注释：工具列表
                try:                                 # 异常处理
                    from core.tool.tool_manager import tool_manager  # 导入工具管理器
                    available_tools = list(tool_manager.tools.keys())[:20]   # 前20个工具
                except Exception:                    # 导入失败
                    available_tools = []             # 空列表

                if available_tools:                  # 如果有可用工具
                    # 调用世界模型建议最佳行动（CPU 密集型计算隔离到线程池）
                    suggestion = await asyncio.to_thread(
                        self.world_model.suggest_action,
                        perception,
                        available_tools,
                        use_mcts=True,               # 使用MCTS规划
                        horizon=3                    # 规划3步
                    )

                    if suggestion:                   # 如果有建议
                        if suggestion.get('type') == 'mcts_plan':   # MCTS规划结果
                            wm_section = f"""\n\n【环境态势评估】
基于历史经验，在当前环境下最有价值的行动路径：
- 推荐首步: {suggestion.get('best_action', '未知')}
- 规划序列: {' → '.join(suggestion.get('action_sequence', [])[:3])}
- 置信度: {suggestion.get('confidence', 0)*100:.0f}%
- 备选: {', '.join(suggestion.get('alternatives', [])[:2])}"""
                        else:                        # 简单预测结果
                            wm_section = f"""\n\n【环境态势评估】
基于历史经验，在当前环境下推荐行动：
- 推荐工具: {suggestion.get('best_action', '未知')}
- 预期成功率: {suggestion.get('success_prob', 0)*100:.0f}%
- 风险: {suggestion.get('risk', 0)*100:.0f}%"""

                        prompt += wm_section       # 追加到提示词
                        logger.info(f"[用户: {self.user_id}] 世界模型建议: {suggestion.get('best_action')}")   # 记录日志
            except Exception as e:                   # 异常
                logger.debug(f"[用户: {self.user_id}] 世界模型建议失败: {e}")   # 记录调试日志

        # 【L2改造】慢思考循环：多轮迭代，思维线程自己评估选择
        try:
            result = await self._slow_thinking_loop(prompt, max_rounds=3, timeout=30.0)
            response = result.get("final_thought", "") if result else ""
            if result:
                logger.info(
                    f"[用户: {self.user_id}] [SlowThink] 慢思考完成: "
                    f"{result.get('rounds', 0)}轮, "
                    f"收敛={result.get('converged', False)}, "
                    f"最终长度={len(response)}"
                )
        except Exception as e:
            logger.error(
                f"[SILENT_FAILURE_BLOCKED] [用户: {self.user_id}] [Consciousness] _think 慢思考失败: {e}",
                exc_info=False,
            )
            async with self._thread_lock:
                self._internal_state["last_thought_time"] = time.time()
            return                                   # 直接返回

        if not response:                             # 如果无响应
            async with self._thread_lock:
                self._internal_state["last_thought_time"] = time.time()
            return                                   # 直接返回

        # 记录思考历史                             # 注释：记录历史
        self._thought_history.append({
            "timestamp": time.time(),                # 时间戳
            "content": response[:200],               # 内容（前200字符）
            "mode": "default"                        # 模式
        })
        self._last_think_time = time.time()          # 更新上次思考时间

        # 使用价值评估系统 V2 - 有温度的评分         # 注释：价值评估
        from core.strategy.value_system_v2 import assess_memory_value_v2  # 导入评估函数
        assessment = assess_memory_value_v2({        # 评估价值
            "content": response,
            "scene": "consciousness",
            "mem_type": "internal_thought"
        })

        ms = await get_memory_service()
        await ms.add_memory(
            user_id=self.user_id,
            content=response,
            memory_type="internal_thought",
            metadata={
                "layer": "medium",
                "scene": "consciousness",
                "rating": assessment.overall_score,
                "source": MemorySource.AI.value,
                **self._internal_state.copy(),
                "value_assessment_v2": {
                    "overall_score": assessment.overall_score,
                    "overall_grade": assessment.overall_grade,
                    "dimension_scores": {k.value: v for k, v in assessment.dimension_scores.items()},
                    "emotional_impact": assessment.emotional_impact,
                    "growth_insights": assessment.growth_insights,
                    "ethical_notes": assessment.ethical_notes,
                    "suggested_reflection": assessment.suggested_reflection,
                    "will_affect_behavior": assessment.will_affect_behavior,
                }
            }
        )

        # 高分或低分都会触发后续反思                 # 注释：触发反思
        if assessment.will_affect_behavior:
            logger.debug(f"[用户: {self.user_id}] [Consciousness] 价值评估{assessment.overall_grade}级，将影响后续行为")   # 记录日志
        logger.debug(f"[用户: {self.user_id}] 内部思考已记录: {response[:100]}...")   # 记录日志

        async with self._thread_lock:                      # 获取线程锁
            self._internal_state["recent_thoughts"].append(response[:200])   # 添加最近思考
            if len(self._internal_state["recent_thoughts"]) > 5:   # 如果超过5条
                self._internal_state["recent_thoughts"].pop(0)   # 移除最早的

        # 【手眼脑协同】收集反馈并训练思维模型
        # 1. 思考前记录快照（用于对比用户反馈、视觉反馈）
        _user_input_before = self._last_user_input_time
        _vision_tags_before = len(getattr(self, '_recent_vision_tags', []))
        _chosen = ""
        if result and result.get("thought_chain"):
            _first = result["thought_chain"][0]
            if _first.startswith("[方向] "):
                _chosen = _first[5:]

        # 2. 执行行动
        action_result = await self._act_on_thought(response)

        # 3. 收集反馈并训练
        try:
            from core.consciousness.feedback_collector import FeedbackCollector
            collector = FeedbackCollector()

            motivation = self._get_motivation_vector()
            vision_state = self._get_vision_state_vector()
            history = self._get_history_vector()
            collector.take_snapshot(motivation, vision_state, history, _chosen)

            # 思考质量
            collector.record_thought_quality(
                assessment_score=assessment.overall_score,
                converged=result.get("converged", False) if result else False,
                thought_length=len(response)
            )

            # 行动结果
            collector.record_action_result(action_result)

            # 用户反馈
            user_responded = (self._last_user_input_time > _user_input_before)
            collector.record_user_feedback(
                user_responded_within_10s=user_responded,
                user_interrupted=False
            )

            # 视觉反馈
            _vision_tags_after = len(getattr(self, '_recent_vision_tags', []))
            collector.record_vision_feedback(
                new_elements_found=max(0, _vision_tags_after - _vision_tags_before),
                alert_level_changed=False
            )

            # 【ExperienceBus】把经验总线的事件flush进FeedbackCollector
            if self.experience_bus:
                try:
                    exp_events = self.experience_bus.get_recent(seconds=60)
                    collector.ingest_experience_events(exp_events)
                    logger.debug(
                        f"[用户: {self.user_id}] [ExperienceBus] 本周期摄入{len(exp_events)}条经验事件"
                    )
                except Exception as e:
                    logger.debug(f"[用户: {self.user_id}] [ExperienceBus] flush异常: {e}")

            # 4. 计算统一标签并训练
            label = collector.compute_label()
            logger.info(
                f"[用户: {self.user_id}] [Feedback] 统一标签={label:.3f}, "
                f"思考质量={collector.thought_quality.get('assessment_score', 0):.2f}, "
                f"行动执行={action_result.executed}"
            )

            if _chosen and torch is not None and self.online_learner and self.action_model:
                action_features = self._extract_action_features(_chosen)
                input_vector = torch.cat([motivation, vision_state, action_features, history])
                self.online_learner.add_sample(input_vector, label)

                if self.online_learner.should_train():
                    loss = self.online_learner.train_step()
                    logger.info(
                        f"[用户: {self.user_id}] [ActionModel] 训练完成, "
                        f"loss={loss:.4f}, 样本数={self.online_learner.sample_count}"
                    )
                    try:
                        _save_dir = Path("data")
                        _save_dir.mkdir(parents=True, exist_ok=True)
                        self.action_model.save(str(_save_dir / "action_preference_model.pt"))
                    except Exception as e:
                        logger.error(f"[用户: {self.user_id}] [Consciousness] 保存动作偏好模型失败: {e}", exc_info=True)
        except Exception as e:
            logger.debug(f"[用户: {self.user_id}] [ActionModel] 训练异常: {e}")

    async def _get_state_embedding(self) -> np.ndarray:    # 定义获取状态嵌入的方法
        """
        获取当前状态的嵌入向量，用于内在动机的新奇度计算。
        使用向量记忆中的嵌入模型对当前感知摘要进行编码。
        """
        try:                                         # 异常处理
            # 从内部状态获取最近的感知摘要             # 注释：获取感知
            async with self._thread_lock:                  # 获取线程锁
                perception_lines = self._internal_state.get("recent_perception", [])
            perception_text = "无感知" if not perception_lines else " ".join(perception_lines)   # 默认文本或有数据

            # 使用向量记忆的嵌入模型（如果可用）         # 注释：获取嵌入
            from core.memory.memory_service import get_memory_service
            ms = await get_memory_service()
            ef = ms.vector_store.get_embedding_function()
            if ef:                               # 如果存在
                # 嵌入函数返回的是一个列表的列表，我们取第一个（因为只有一个文本）   # 注释：处理返回
                try:
                    embedding = ef.encode([perception_text])[0] if hasattr(ef, 'encode') else ef([perception_text])[0]
                    return np.array(embedding, dtype=np.float32)   # 返回numpy数组
                except Exception:
                    pass  # 降级到零向量

            # 回退：返回零向量（不破坏新奇度计算，但新奇度为0）   # 注释：回退处理
            logger.warning(f"[用户: {self.user_id}] 嵌入模型不可用，返回零向量")   # 记录警告
            return np.zeros(128, dtype=np.float32)   # 返回零向量
        except Exception as e:                       # 异常
            logger.error(f"[SILENT_FAILURE_BLOCKED] [用户: {self.user_id}] 获取状态嵌入失败: {e}")   # 记录错误
            return np.zeros(128, dtype=np.float32)   # 返回零向量

    async def _trigger_reflection_from_thought(self, thought: str, source: str = "ukf") -> bool:
        """
        基于意识思考直接触发 Reflector，修复 MSG_REFLECTION_REQUEST 零订阅方问题。
        反思结果写入 _urgent_insights 和 MemoryService。
        """
        try:
            from core.reflector.reflector import get_reflector
            reflector = get_reflector()
            if not reflector:
                logger.warning(f"[用户: {self.user_id}] Reflector 未初始化，跳过反思")
                return False

            # 从经验总线构造最小轨迹
            task_description = thought[:200] or "意识触发反思"
            step_info = {
                "success": False,
                "error": f"意识检测到反思倾向，来源: {source}",
                "trigger_thought": thought,
            }
            trajectory: list[dict[str, Any]] = []

            if self.experience_bus:
                try:
                    recent_events = self.experience_bus.get_recent(seconds=60) or []
                    trajectory = [
                        {
                            "step": i,
                            "action": getattr(e, "action", "unknown"),
                            "observation": getattr(e, "outcome", 0.5),
                            "source": getattr(e, "source", "unknown"),
                            "context": getattr(e, "context", {}),
                        }
                        for i, e in enumerate(recent_events[-10:])
                    ]
                    if recent_events:
                        last = recent_events[-1]
                        task_description = (
                            f"{getattr(last, 'source', 'system')}:{getattr(last, 'action', 'unknown')} 触发反思"
                        )
                except Exception as e:
                    logger.debug(f"[用户: {self.user_id}] 构造反思轨迹失败: {e}")

            reflection = await reflector.reflect_after_step(
                task=task_description,
                step_info=step_info,
                trajectory=trajectory,
            )

            if reflection:
                insight = reflection.insight or reflection.suggestion or "我意识到需要调整策略"
                self._urgent_insights.append(f"[反思] {insight}")
                if len(self._urgent_insights) > 20:
                    self._urgent_insights = self._urgent_insights[-20:]

                # 持久化到记忆
                try:
                    memory_service = await get_memory_service()
                    if memory_service:
                        await memory_service.add_memory(
                            user_id=self.user_id,
                            content=f"[反思] {insight}",
                            memory_type="reflection",
                            source="consciousness",
                            metadata={
                                "trigger": source,
                                "reflection_level": getattr(reflection.level, "value", "execution"),
                                "confidence": reflection.confidence,
                            },
                        )
                except Exception as e:
                    logger.debug(f"[用户: {self.user_id}] 反思结果持久化失败: {e}")

                logger.info(f"[用户: {self.user_id}] 意识触发反思完成: {insight[:80]}...")
                return True

        except Exception as e:
            logger.error(f"[用户: {self.user_id}] 意识触发反思失败: {e}", exc_info=True)
            return False

        return False

    async def _act_on_thought(self, thought: str):   # 定义异步根据思考采取行动的方法
        """
        根据思考内容决定是否采取外部行动（事件驱动改造后）

        包含：
        1. 弱连接检查（仅日常模式且空闲时，专注模式下跳过）
        2. 内在行动决策

        Returns:
            ActionResult: 行动执行结果，供反馈收集器使用
        """
        from core.consciousness.feedback_collector import ActionResult
        result = ActionResult()

        # 获取当前工作模式                           # 注释：获取工作模式
        mode_manager = get_work_mode_manager()
        current_mode = mode_manager.get_current_mode()

        # ====== 第一步：弱连接检查（仅日常模式且空闲时）======   # 注释：弱连接检查
        # 专注模式下弱连接不主动触发任务             # 注释：专注模式跳过
        # 观察者模式下弱连接只感知不行动             # 注释：观察者模式限制
        if current_mode == WorkMode.FOCUS:
            logger.debug(f"[用户: {self.user_id}] [意识] 专注模式：跳过弱连接触发")   # 记录日志
        # 【P0-BLOCKER修复】将弱连接调用包裹在 try-except 中，防止 API 不兼容导致思考流程中断
        try:
            if self._observer_mode and not self._observer_can_propose:
                # 观察者模式：弱连接仅感知，不触发任务
                logger.debug(f"[用户: {self.user_id}] [意识] 观察者模式：弱连接仅感知，不触发任务")
                # 记录观察日志但不发送任务提案
                if self._weak_engine and self._weak_engine.should_run():
                    weak_result = self._weak_engine.check_thought(thought)
                    if weak_result.triggered:
                        logger.debug(f"[用户: {self.user_id}] [观察者模式] 感知到弱连接关键词: {weak_result.keyword}，但不采取行动")
            elif self._weak_engine and self._weak_engine.should_run():   # 如果应该运行
                weak_result = self._weak_engine.check_thought(thought)   # 检查思考
                if weak_result.triggered:                # 如果触发
                    logger.info(f"[用户: {self.user_id}] [弱连接] 触发关键词: {weak_result.keyword}, 决策: {weak_result.decision}")   # 记录日志
                    # 如果弱连接决定执行，通过事件总线发送   # 注释：发送事件
                    if weak_result.decision == "是":
                        await self._emit_action_event(
                            action=weak_result.action,
                            source="weak_connection",
                            thought=thought
                        )
                        result.weak_connection_triggered = True
                        result.weak_connection_keyword = weak_result.keyword
                        result.executed = True
                        result.action_text = weak_result.action
                        return result                    # 返回
        except Exception as e:
            logger.debug(f"[用户: {self.user_id}] [意识] 弱连接检查失败（已降级跳过）: {e}")

        # ====== 第二步：原有行动决策逻辑 ======       # 注释：原有逻辑
        action_text = None                           # 行动文本
        trigger_source = None                        # 触发来源

        # 新增: 事件发射 - 思考产生行动               # 注释：事件发射
        with contextlib.suppress(Exception):
            event_bus.emit_async("consciousness:thought_generated", {
                "thought": thought,
                "action": None,
                "user_id": self.user_id,
                "timestamp": time.time()
            })

        # ── UKF 状态估计：替代关键词硬匹配 ────────────────────────────────────
        try:
            import numpy as np
            # 从 thought 提取语义观测（0/1 二值特征）
            obs_action = 1.0 if ("应该" in thought or "需要" in thought or "计划" in thought) else 0.0
            obs_reflect = 1.0 if "反思" in thought else 0.0
            obs_explore = 1.0 if ("探索" in thought or "发现" in thought) else 0.0
            observation = np.array([[obs_action], [obs_reflect], [obs_explore]])

            # 状态转移：轻微衰减（意识倾向自然消退）
            def _ukf_transition(x):
                decay = np.array([[0.92], [0.95], [0.90]])
                return decay * x + np.random.randn(3, 1) * 0.05

            # 观测函数：直接映射（观测即状态的带噪表现）
            def _ukf_observation(x):
                return x

            await self._estimator_engine.predict_async(
                'consciousness_ukf',
                A_or_transition=_ukf_transition,
                Q_or_process_noise=np.eye(3) * 0.02
            )
            await self._estimator_engine.update_async(
                'consciousness_ukf',
                observation=observation,
                observation_fn=_ukf_observation,
                observation_noise=np.eye(3) * 0.1
            )
            ukf_state = await self._estimator_engine.get_state_async('consciousness_ukf')
            state_vec = ukf_state['state'].flatten()

            # 【改造】UKF 状态写入 SystemState，供语音/动作模块读取
            try:
                from core.runtime import system_state
                system_state.set_sync("consciousness.ukf_state", {
                    "action_will": float(state_vec[0]),
                    "reflect_tendency": float(state_vec[1]),
                    "explore_tendency": float(state_vec[2]),
                    "timestamp": time.time(),
                })
            except Exception:
                pass

            # 根据平滑后的状态向量做决策（不再是关键词硬匹配）
            if state_vec[0] > 0.45:   # 行动意愿维度
                lines = thought.split('\n')
                for line in lines:
                    if "应该" in line or "需要" in line:
                        action_text = line.strip()
                        trigger_source = "ukf_action"
                        break

            if state_vec[1] > 0.50:   # 反思倾向维度
                reflection_id = generate_trace_id()
                msg = build_message(
                    msg_type=MSG_REFLECTION_REQUEST,
                    source="consciousness",
                    payload={
                        "reflection_id": reflection_id,
                        "reflection_type": "post_action",
                        "context": {"trigger_thought": thought, "user_id": self.user_id},
                        "auto_trigger": True
                    }
                )
                # 【P0修复】直接调用 Reflector 进行反思，不再走无订阅方的事件总线
                logger.info(f"[用户: {self.user_id}] 意识检测到反思倾向 (UKF state={state_vec[1]:.2f})，直接触发 Reflector")
                reflection_triggered = await self._trigger_reflection_from_thought(thought, source="ukf")
                result.executed = reflection_triggered
                result.reason = "反思倾向，已触发 Reflector" if reflection_triggered else "反思倾向，Reflector 失败"
                return result

            if state_vec[2] > 0.45:   # 探索倾向维度
                trigger_source = "ukf_explore"
                action_text = "系统建议主动探索当前环境"

        except Exception as e:
            logger.debug(f"[用户: {self.user_id}] UKF 状态估计失败，降级到关键词匹配: {e}")
            # 降级：保留原始关键词匹配作为 fallback
            if "应该" in thought or "需要" in thought or "计划" in thought:
                lines = thought.split('\n')
                for line in lines:
                    if "应该" in line or "需要" in line:
                        action_text = line.strip()
                        trigger_source = "rule1_fallback"
                        break
            if "反思" in thought:
                # 【P0修复】fallback 分支也直接调用 Reflector
                logger.info(f"[用户: {self.user_id}] 意识检测到反思倾向 (fallback)，直接触发 Reflector")
                reflection_triggered = await self._trigger_reflection_from_thought(thought, source="fallback")
                result.executed = reflection_triggered
                result.reason = "反思倾向(fallback)，已触发 Reflector" if reflection_triggered else "反思倾向(fallback)，Reflector 失败"
                return result

        if not action_text:                          # 如果没有行动文本
            result.executed = False
            result.reason = "无行动文本"
            return result                            # 直接返回

        now = time.time()                            # 获取当前时间
        user_active = (now - self._last_user_input_time) < 300   # 检查用户是否活跃（300秒内）

        decision_prompt = f"""你有一个潜在的行动想法：{action_text}
当前系统信息：
- 用户是否活跃：{"是（300秒内有输入）" if user_active else "否（已安静一段时间）"}
- 系统CPU负载：{psutil.cpu_percent() if 'psutil' in globals() else '未知'}%
- 当前时间：{datetime.now().strftime('%H:%M')}

请根据以下原则判断是否应该立即执行这个行动：
- 如果用户正在活跃使用电脑，应避免打扰用户，除非行动与当前窗口相关且紧急。
- 如果系统负载较高且行动是优化相关，可以考虑执行。
- 如果行动与用户当前可能的需求相关（例如备份、提醒），可考虑执行。

请输出一个JSON对象，包含：
- "execute": true 或 false，表示是否执行。
- "reason": 简短理由。
- "priority": 如果执行，建议的优先级（1-10，1最高，10最低）。

仅输出JSON，不要其他解释。
"""
        try:                                         # 异常处理
            decision_response = await call_thinker_async([{"role": "user", "content": decision_prompt}])   # 调用AI决策
            if decision_response:                    # 如果有响应
                decision_data = json.loads(decision_response)   # 解析JSON
                should_execute = decision_data.get("execute", False)   # 获取是否执行
                reason = decision_data.get("reason", "无理由")   # 获取理由
                priority_num = decision_data.get("priority", 5)   # 获取优先级数值
                # 将数值优先级转换为字符串优先级   # 注释：优先级转换
                if priority_num <= 3:
                    priority_str = "high"
                elif priority_num <= 6:
                    priority_str = "normal"
                else:
                    priority_str = "low"
            else:                                    # 无响应
                should_execute = False
                reason = "AI返回空"
                priority_str = "normal"
        except Exception as e:                       # 异常
            logger.error(f"[SILENT_FAILURE_BLOCKED] [用户: {self.user_id}] 解析AI决策失败: {e}，默认不执行")   # 记录错误
            should_execute = False
            reason = f"解析异常: {e}"
            priority_str = "normal"

        if should_execute:                           # 如果应该执行
            # 观察者模式检查：不主动提议任务         # 注释：观察者模式限制
            if self._observer_mode and not self._observer_can_propose:
                logger.debug(f"[用户: {self.user_id}] [观察者模式] 拦截思考触发的任务提案: {action_text[:50]}...")
                result.executed = False
                result.reason = "观察者模式拦截"
                result.action_text = action_text
                return result                        # 观察者模式下不发送任务提案

            # 【P3新增】世界模型预测行动结果
            try:
                wm = self.world_model
                if wm and hasattr(wm, 'suggest_action'):
                    # 构造当前状态
                    current_state = {
                        "recent_perception": self._internal_state.get("recent_perception", []),
                        "active_goals": self._internal_state.get("active_goals", []),
                        "user_id": self.user_id,
                        "timestamp": time.time(),
                    }
                    # 将行动文本映射为可用工具列表（启发式）
                    available_tools = self._infer_tools_from_action(action_text)
                    if available_tools:
                        wm_suggestion = await asyncio.to_thread(
                            wm.suggest_action,
                            current_state,
                            available_tools,
                            use_mcts=True,
                            horizon=3,
                        )
                        if wm_suggestion:
                            wm_confidence = wm_suggestion.get('confidence', 0.0)
                            if wm_confidence < 0.3:
                                logger.warning(
                                    f"[用户: {self.user_id}] [世界模型] 预测置信度低 ({wm_confidence:.2f})，"
                                    f"选择保守策略，降级任务优先级"
                                )
                                if priority_str == "high":
                                    priority_str = "normal"
                                elif priority_str == "normal":
                                    priority_str = "low"
                            else:
                                logger.debug(
                                    f"[用户: {self.user_id}] [世界模型] 预测置信度: {wm_confidence:.2f}, "
                                    f"建议行动: {wm_suggestion.get('best_action', '无')}"
                                )
            except Exception as e:
                logger.debug(f"[用户: {self.user_id}] [世界模型] 预测行动结果失败: {e}")

            # 【ConsciousnessDirective】把意识状态翻译成确定性指令
            try:
                from core.consciousness.directive_translator import DirectiveTranslator
                translator = DirectiveTranslator()
                directives: list[dict] = []

                # 1) 世界模型建议
                directives.extend(translator.from_world_model(wm_suggestion, available_tools))

                # 2) UKF 状态
                ukf_state = await self._estimator_engine.get_state_async('consciousness_ukf')
                directives.extend(translator.from_ukf_state(ukf_state, thought, available_tools))

                # 3) 内在动机
                try:
                    drive = self.intrinsic_motivation.evaluate_drive()
                    directives.extend(translator.from_intrinsic_drive(drive))
                except Exception:
                    pass

                self._pending_directives = [
                    d for d in directives if d.get("confidence", 0.0) > 0.3
                ]
                if self._pending_directives:
                    logger.info(
                        f"[用户: {self.user_id}] [ConsciousnessDirective] "
                        f"生成 {len(self._pending_directives)} 条待执行指令"
                    )
            except Exception as e:
                logger.debug(f"[用户: {self.user_id}] [ConsciousnessDirective] 生成指令失败: {e}")

            # 改造后：通过事件总线发送任务提案         # 注释：发送任务提案
            task_id = generate_trace_id()            # 生成任务ID
            msg = build_message(                     # 构建消息
                msg_type=MSG_TASK_PROPOSED,          # 消息类型
                source="consciousness",              # 来源
                payload=TaskRequestPayload(          # 负载
                    task_id=task_id,                 # 任务ID
                    goal=action_text,                # 目标
                    priority=priority_str,           # 优先级
                    context={                        # 上下文
                        "trigger_source": trigger_source,
                        "thought_excerpt": thought[:200],
                        "decision_reason": reason,
                        "user_id": self.user_id
                    },
                    source="consciousness"           # 来源
                )
            )
            # 日常模式工具白名单检查
            if not self._is_action_allowed_in_current_mode(action_text):
                logger.debug(f"[用户: {self.user_id}] 日常模式下拦截意识任务提案: {action_text}")
                result.executed = False
                result.reason = "日常模式白名单拦截"
                result.action_text = action_text
                return result
            # 【P1修复】异步发射事件，避免同步 handler 阻塞事件循环
            try:
                event_bus.emit_async(MSG_TASK_PROPOSED, msg)
            except Exception:
                event_bus.emit(MSG_TASK_PROPOSED, msg)  # 降级到同步
            logger.info(f"[用户: {self.user_id}] 意识发送任务提案 [{task_id}]: {action_text}，优先级{priority_str}，理由: {reason}")   # 记录日志

            # 新增: 更新事件 - 补充action信息           # 注释：更新事件
            with contextlib.suppress(Exception):
                event_bus.emit_async("consciousness:thought_generated", {
                    "thought": thought,
                    "action": action_text,
                    "task_id": task_id,
                    "priority": priority_str,
                    "user_id": self.user_id,
                    "timestamp": time.time()
                })  # 事件失败不影响原有功能
            # 设置成功执行的结果
            result.executed = True
            result.task_proposed = True
            result.task_priority = priority_str
            result.action_text = action_text
            result.reason = reason
            return result
        else:                                        # 不执行
            logger.debug(f"[用户: {self.user_id}] AI决定不执行 {action_text}，理由: {reason}")   # 记录日志
            await self._store_pending_thought(thought, action_text, reason)   # 存储待处理思考
            result.executed = False
            result.reason = reason
            result.action_text = action_text
            return result

    def get_pending_directives(self, clear: bool = True) -> list[dict]:
        """
        返回当前意识线程生成的、未过期的 ConsciousnessDirective。

        Args:
            clear: 返回后是否清空 pending 列表，防止过期指令污染后续任务。
        """
        now = time.monotonic()
        valid = [d for d in self._pending_directives if d.get("expires_at", 0.0) > now]
        if clear:
            self._pending_directives = []
        return valid

    async def _emit_action_event(self, action: str, source: str, thought: str):   # 定义异步发送行动事件的方法
        """
        发送行动事件到事件总线

        观察者模式限制：
        - 当 observer_mode=True 且 observer_can_propose=False 时，
          不发送任务提案，只记录观察日志
        """
        # 观察者模式检查：不主动提议任务
        if self._observer_mode and not self._observer_can_propose:
            logger.debug(f"[用户: {self.user_id}] [观察者模式] [{source}] 拦截任务提案: {action[:50]}...")
            return                                   # 观察者模式下直接返回，不发送事件

        try:                                         # 异常处理
            task_id = generate_trace_id()            # 生成任务ID
            msg = build_message(                     # 构建消息
                msg_type=MSG_TASK_PROPOSED,          # 消息类型
                source=source,                       # 来源
                payload=TaskRequestPayload(          # 负载
                    task_id=task_id,                 # 任务ID
                    goal=action,                     # 目标
                    priority="low",                  # 优先级
                    context={                        # 上下文
                        "trigger_source": source,
                        "thought_excerpt": thought[:200],
                        "user_id": self.user_id
                    },
                    source=source                    # 来源
                )
            )
            # 日常模式工具白名单检查
            if not self._is_action_allowed_in_current_mode(action):
                logger.debug(f"[用户: {self.user_id}] 日常模式下拦截{source}任务提案: {action}")
                return
            event_bus.emit_async(MSG_TASK_PROPOSED, msg)   # 异步发送事件
            logger.info(f"[用户: {self.user_id}] [{source}] 发送任务提案 [{task_id}]: {action}")   # 记录日志
        except Exception as e:                       # 异常
            logger.error(f"[SILENT_FAILURE_BLOCKED] [用户: {self.user_id}] 发送行动事件失败: {e}")   # 记录错误

    async def _store_pending_thought(self, thought: str, action_text: str, decision_reason: str):   # 定义异步存储待处理思考的方法
        content = {                                  # 构建内容
            "thought": thought,                      # 思考
            "action": action_text,                   # 行动
            "decision_reason": decision_reason,      # 决策理由
            "user_id": self.user_id,                 # 用户ID
            "timestamp": time.time()                 # 时间戳
        }
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()
        await ms.add_memory(                         # 异步添加到记忆
            user_id=self.user_id,
            content=json.dumps(content, ensure_ascii=False),
            memory_type="pending_action",
            layer="short",
            scene="consciousness_pending",           # 场景
            expire_days=1,                           # 1天后过期
            source=MemorySource.SYSTEM.value,        # Agent-4: 系统写入
        )

    async def _deep_reflect(self):                   # 定义异步深度反思方法
        logger.info(f"[用户: {self.user_id}] 开始深度反思...")   # 记录日志
        from core.memory.memory_service import get_memory_service
        ms = await get_memory_service()
        reflections = await ms.query_memories(self.user_id, mem_type="reflection", layer="evolve", limit=5)   # 异步获取反思
        internal_thoughts = await ms.query_memories(self.user_id, mem_type="internal_thought", layer="medium", limit=5)   # 异步获取内部思考
        if not reflections and not internal_thoughts:   # 如果没有数据
            logger.debug(f"[用户: {self.user_id}] 无足够历史记录，跳过深度反思")   # 记录日志
            return                                   # 直接返回

        prompt = f"""【深度反思任务】
请分析以下最近的任务执行反思和内部思考，总结出3条最重要的自我改进规则。
每条规则必须是一个JSON对象，格式如下：
{{
    "condition": "当用户指令包含关键词X且当前窗口标题包含Y时",   // 触发条件，用自然语言描述，但需具体
    "action": "优先使用工具A，参数为...",                        // 建议采取的行动
    "reason": "因为之前多次失败...",                             // 理由
    "confidence": 0.8                                             // 初始置信度0-1
}}

要求：
- 规则应具体、可操作，例如"当OCR识别失败时，应优先尝试窗口聚焦后再重试"。
- 输出必须是JSON数组，每个元素是一个规则对象。
- 仅输出JSON，不要其他解释。

最近任务反思：
{json.dumps([r["content"] for r in reflections], ensure_ascii=False, indent=2)[:500]}

最近内部思考：
{json.dumps([t["content"] for t in internal_thoughts], ensure_ascii=False, indent=2)[:500]}
"""
        # 【修复】增加专用超时，超时后更新时间戳避免反复重试
        try:
            response = await call_thinker_async(
                [{"role": "user", "content": prompt}],
                timeout=120,
                hard_timeout=90,
            )   # 异步调用AI
        except Exception as e:
            logger.error(
                f"[SILENT_FAILURE_BLOCKED] [用户: {self.user_id}] [Consciousness] _deep_reflect AI 调用失败: {e}",
                exc_info=False,
            )
            async with self._thread_lock:
                self._internal_state["last_deep_reflect_time"] = time.time()
            return                                   # 直接返回

        if not response:                             # 如果无响应
            async with self._thread_lock:
                self._internal_state["last_deep_reflect_time"] = time.time()
            return                                   # 直接返回

        try:                                         # 异常处理
            rules = json.loads(response)             # 解析JSON
            if not isinstance(rules, list):          # 如果不是列表
                rules = [rules]                      # 转为列表
        except Exception as e:                       # 异常
            logger.error(f"[SILENT_FAILURE_BLOCKED] [用户: {self.user_id}] 深度反思返回的不是有效JSON: {e}，原始内容: " + response[:200])   # 记录错误
            return                                   # 返回

        rm = RuleManager()                           # 创建规则管理器
        for rule in rules:                           # 遍历规则
            await rm.add_rule(rule)   # 异步添加规则
            logger.info(f"[用户: {self.user_id}] 生成规则: {rule.get('condition', '')[:50]}...")   # 记录日志

        # 新增: 事件发射 - 深度反思完成               # 注释：事件发射
        with contextlib.suppress(Exception):
            event_bus.emit_async("consciousness:reflection_completed", {
                "rules_generated": len(rules),
                "rules": [r.get('condition', '')[:50] for r in rules],
                "user_id": self.user_id,
                "timestamp": time.time()
            })  # 事件失败不影响原有功能

    async def _save_state(self):                     # 定义异步保存状态的方法
        try:                                         # 异常处理
            async with self._thread_lock:                  # 获取线程锁
                state_copy = self._internal_state.copy()   # 复制状态
            state_copy.pop("recent_thoughts", None)   # 移除最近思考（不保存）

            # 保存到本地文件（原生异步，无需 to_thread）
            async with aiofiles.open(self._state_file, "w", encoding="utf-8") as f:
                await f.write(json.dumps(state_copy, ensure_ascii=False, indent=2))

            # 同时保存到 Redis（云端部署时使用；当前为空实现，直接调用无需 to_thread）
            self._save_to_redis(state_copy)

        except Exception as e:                       # 异常
            logger.error(f"[SILENT_FAILURE_BLOCKED] [用户: {self.user_id}] 保存意识状态失败: {e}")   # 记录错误

    def _load_state(self) -> dict | None:         # 定义加载状态的方法
        # 优先从 Redis 加载（云端部署时）             # 注释：Redis优先
        redis_state = self._load_from_redis()        # 从Redis加载
        if redis_state:                              # 如果加载成功
            logger.info(f"[用户: {self.user_id}] 从 Redis 加载意识状态")   # 记录日志
            return redis_state                       # 返回状态

        # 回退到本地文件                             # 注释：本地回退
        if self._state_file.exists():                # 如果文件存在
            try:                                     # 异常处理
                with open(self._state_file, encoding="utf-8") as f:
                    return json.load(f)              # 解析并返回
            except Exception as e:                   # 异常
                logger.error(f"[SILENT_FAILURE_BLOCKED] [用户: {self.user_id}] 加载意识状态失败: {e}")   # 记录错误
        return None                                  # 返回None

    def adjust_think_interval(self, system_load: dict):   # 定义调整思考间隔的方法
        """根据系统负载动态调整思考频率（相对于基础间隔）"""   # 方法文档字符串
        cpu = system_load.get("cpu_percent", 0)      # 获取CPU使用率
        memory = system_load.get("memory_percent", 0)   # 获取内存使用率

        # 负载高时增加思考间隔                       # 注释：高负载处理
        if cpu > 80 or memory > 85:
            self._load_adjustment_factor = min(self._load_adjustment_factor + 0.2, 3.0)
        # 负载低时减少思考间隔                       # 注释：低负载处理
        elif cpu < 30 and memory < 50:
            self._load_adjustment_factor = max(self._load_adjustment_factor - 0.1, 0.5)
        else:                                        # 正常负载
            self._load_adjustment_factor = max(self._load_adjustment_factor - 0.05, 1.0)

        # 应用负载调整因子到基础间隔                 # 注释：应用调整
        self._think_interval = self._base_think_interval * self._load_adjustment_factor

        logger.debug(f"[用户: {self.user_id}] [Consciousness] 思考间隔调整为 {self._think_interval:.1f}秒 "
                     f"(基础{self._base_think_interval}秒 × 负载因子{self._load_adjustment_factor:.2f})")   # 记录日志

    def get_thinking_stats(self) -> dict:            # 定义获取思考统计的方法
        """获取思考统计信息"""                       # 方法文档字符串
        return {                                     # 返回统计字典
            "total_thoughts": len(self._thought_history),   # 总思考数
            "think_interval": self._think_interval,   # 思考间隔
            "base_think_interval": self._base_think_interval,   # 基础间隔
            "think_priority": self._think_priority,   # 思考优先级
            "load_adjustment_factor": self._load_adjustment_factor,   # 负载调整因子
            "is_paused": self._paused,               # 是否暂停
            "is_user_input_paused": self._user_input_paused,   # 是否用户输入暂停
            "last_think_time": getattr(self, '_last_think_time', 0),   # 上次思考时间
            "user_id": self.user_id                  # 用户ID
        }

    def analyze_current_state(self, execution_history: list[dict], current_round: int) -> dict | None:
        """
        分析当前执行状态（简化版）

        Args:
            execution_history: 执行历史记录列表
            current_round: 当前执行轮次

        Returns:
            {
                "situation": "情况描述",
                "recommended_action": "建议行动",
                "suggested_tool": "推荐工具（可选）",
                "confidence": 0.8,
                "should_stop": False,
                "reason": "原因（如should_stop为True）"
            }
            如果执行历史不足，返回 None

        Raises:
            TypeError: execution_history 类型错误
            RuntimeError: 分析过程发生异常
        """
        # 方法入口日志
        logger.info(f"[Consciousness] 开始分析状态: round={current_round}")

        try:
            # 防御性编程：处理 None 输入
            if execution_history is None:
                execution_history = []

            # 验证 execution_history 类型
            if not isinstance(execution_history, list):
                logger.error(f"[Consciousness] execution_history类型错误: {type(execution_history)}")
                raise TypeError("execution_history必须是列表")

            # 验证 current_round 类型
            if not isinstance(current_round, int):
                logger.error(f"[Consciousness] current_round类型错误: {type(current_round)}")
                raise TypeError("current_round必须是整数")

            # 执行历史不足时正常返回 None（这是正常情况，不打ERROR）
            if len(execution_history) < 2:
                logger.debug("[Consciousness] 执行历史不足2条，跳过分析")
                return None

            # 获取最近两条执行记录用于分析
            recent_records = execution_history[-2:]

            # 分析最近执行情况
            situation_parts = []
            last_tool = None
            last_status = None
            error_count = 0

            for idx, record in enumerate(recent_records):
                if not isinstance(record, dict):
                    logger.warning(f"[Consciousness] 执行历史记录[{idx}]类型异常: {type(record)}")
                    continue

                tool = record.get("tool") or record.get("tool_name")
                status = record.get("status") or record.get("result")
                error = record.get("error") or record.get("error_msg")

                if tool:
                    last_tool = tool
                if status:
                    last_status = status
                if error:
                    error_count += 1
                    situation_parts.append(f"工具'{tool}'执行出错: {error}")

            # 构建情况描述
            if situation_parts:
                situation = "; ".join(situation_parts)
            elif last_tool:
                situation = f"最近执行工具'{last_tool}'，状态: {last_status or '未知'}"
            else:
                situation = f"第{current_round}轮执行完成，无工具调用"

            # 检测是否需要停止（连续错误次数过多）
            should_stop = False
            stop_reason = ""

            if error_count >= 2:
                should_stop = True
                stop_reason = f"连续{error_count}次执行错误，建议停止并人工介入"
                logger.warning(f"[Consciousness] 检测到连续错误: count={error_count}, round={current_round}")
            elif current_round > 20:
                should_stop = True
                stop_reason = "执行轮次超过20轮，建议检查任务复杂度"
                logger.warning(f"[Consciousness] 执行轮次超限: round={current_round}")

            # 推荐行动和工具
            recommended_action = "继续执行"
            suggested_tool = None

            if should_stop:
                recommended_action = "停止执行并等待人工介入"
            elif error_count > 0 and last_tool:
                # 获取替代工具建议
                suggested_tool = self._get_alternative_tool(last_tool)
                if suggested_tool:
                    recommended_action = f"尝试使用替代工具'{suggested_tool}'"
                    logger.debug(f"[Consciousness] 推荐替代工具: {last_tool} -> {suggested_tool}")
            elif current_round > 10:
                recommended_action = "考虑总结当前进展并询问用户"

            # 计算置信度（基于错误次数）
            confidence = max(0.3, 1.0 - error_count * 0.2)

            # 构建结果
            result = {
                "situation": situation,
                "recommended_action": recommended_action,
                "suggested_tool": suggested_tool,
                "confidence": round(confidence, 2),
                "should_stop": should_stop,
                "reason": stop_reason,
                "round": current_round,
                "error_count": error_count
            }

            # 验证关键字段
            if not result.get("situation"):
                logger.error(f"[Consciousness] 返回结果缺少situation字段: {result}")
                raise ValueError("状态分析结果不完整: situation字段为空")

            if not isinstance(result.get("confidence"), (int, float)):
                logger.error(f"[Consciousness] confidence字段类型错误: {type(result.get('confidence'))}")
                raise ValueError("状态分析结果不完整: confidence字段类型错误")

            # 方法成功日志
            logger.debug(f"[Consciousness] 状态分析完成: situation={situation[:50]}..., "
                        f"should_stop={should_stop}, confidence={confidence}")

            return result

        except (TypeError, ValueError):
            # 已记录日志的参数错误，直接抛出
            raise
        except Exception as e:
            # 捕获所有其他异常，记录ERROR日志并抛出
            logger.error(f"[Consciousness] analyze_current_state 失败: {e}", exc_info=True)
            raise RuntimeError(f"意识系统状态分析失败: {e}") from e

    def _get_alternative_tool(self, tool: str) -> str | None:
        """
        获取替代工具建议

        Args:
            tool: 当前工具名称

        Returns:
            替代工具名称，如果没有则返回 None
        """
        try:
            # 工具替代映射表
            tool_alternatives = {
                "click": "press",
                "press": "click",
                "screenshot": "capture",
                "capture": "screenshot",
                "ocr": "read_text",
                "read_text": "ocr",
                "find": "locate",
                "locate": "find",
                "type": "paste",
                "paste": "type",
                "shell": "python",
                "python": "shell",
                "browser": "request",
                "request": "browser",
            }

            if not tool or not isinstance(tool, str):
                logger.debug(f"[Consciousness] 工具名无效: {tool}")
                return None

            alternative = tool_alternatives.get(tool)
            if alternative:
                logger.debug(f"[Consciousness] 找到替代工具: {tool} -> {alternative}")

            return alternative

        except Exception as e:
            logger.error(f"[Consciousness] _get_alternative_tool 失败: {e}", exc_info=True)
            raise RuntimeError(f"获取替代工具失败: {e}") from e

    def _get_mode_available_tools(self) -> set | None:
        """获取当前模式下可用的工具ID集合。返回 None 表示无限制。"""
        try:
            from core.mode.work_mode_manager import WorkMode, get_work_mode_manager
            mode_manager = get_work_mode_manager()
            current_mode = mode_manager.get_current_mode()
            if current_mode == WorkMode.DAILY:
                from core.agent.agent_loop import _get_daily_mode_allowed_tools
                return set(_get_daily_mode_allowed_tools())
            return None  # FOCUS 或其他模式无限制
        except Exception as e:
            logger.warning(f"[Consciousness] 获取可用工具列表失败: {e}")
            return None

    def _is_action_allowed_in_current_mode(self, action_text: str) -> bool:
        """检查 action_text 是否被当前模式允许。尽力而为的启发式检查。"""
        available_tools = self._get_mode_available_tools()
        if available_tools is None:
            return True  # 无限制模式
        if not action_text:
            return True
        # 简单启发式：检查 action_text 中是否包含明显的非白名单工具ID
        # 只拦截明确已知的常见危险工具，避免误拦截自然语言描述
        action_lower = action_text.lower()
        non_daily_tools = {"file_delete", "exec", "shell", "system", "eval", "delete_file", "remove_file", "format_disk", "exec_code", "run_shell"}
        for tool in non_daily_tools:
            if tool in action_lower and tool not in available_tools:
                logger.debug(f"[Consciousness] 日常模式下跳过非白名单工具提案: {tool}")
                return False
        return True

    def _infer_tools_from_action(self, action_text: str) -> list[str]:
        """
        【P3新增】根据自然语言行动描述，启发式推断可能涉及的系统工具列表。
        供世界模型 suggest_action 使用。
        """
        action_lower = action_text.lower()
        candidates = []

        # 交易相关
        if any(kw in action_lower for kw in {"交易", "买入", "卖出", "开仓", "平仓", "持仓", "btc", "eth", "价格"}):
            candidates.extend(["shadow_analyze", "market_data", "get_price"])

        # 视觉相关
        if any(kw in action_lower for kw in {"看", "截图", "屏幕", "视觉", "ocr", "识别", "点击", "查找"}):
            candidates.extend(["visual_understand", "pixel_capture", "ocr_text", "gui_locator"])

        # 记忆相关
        if any(kw in action_lower for kw in {"记忆", "回忆", "搜索", "记录", "保存"}):
            candidates.extend(["memory_search", "memory_add", "memory_list"])

        # 系统相关
        if any(kw in action_lower for kw in {"系统", "进程", "窗口", "cpu", "内存", "监控"}):
            candidates.extend(["system_info", "window_get", "process_start"])

        # 通用兜底
        if not candidates:
            candidates = ["visual_understand", "memory_search", "system_info"]

        return candidates

    # ========== 【P0修复】AgentLoop 需要的方法 ==========

    def get_recent_thoughts(self, count: int = 3) -> list[str]:
        """获取最近的思考（供AgentLoop调用）"""
        try:
            if not self._recent_thoughts:
                return []
            return self._recent_thoughts[-count:]
        except Exception as e:
            logger.error(f"[Consciousness] get_recent_thoughts 失败: {e}")
            raise

    def get_urgent_insights(self, clear: bool = True) -> list[str]:
        """获取紧急洞察（供AgentLoop调用）"""
        try:
            if not self._urgent_insights:
                return []
            insights = self._urgent_insights.copy()
            if clear:
                self._urgent_insights.clear()
            return insights
        except Exception as e:
            logger.error(f"[Consciousness] get_urgent_insights 失败: {e}")
            raise

    def get_life_state(self) -> dict[str, Any]:
        """获取当前生命状态（供AgentLoop调用）"""
        try:
            emotional_state = self._internal_state.get("emotional_state", {})
            return {
                "energy": emotional_state.get("energy", 0.5),
                "mood": emotional_state.get("mood", "平静"),
                "stress": 0.0,
                "curiosity": emotional_state.get("curiosity", 0.5),
                "satisfaction": emotional_state.get("satisfaction", 0.5),
            }
        except Exception as e:
            logger.error(f"[Consciousness] get_life_state 失败: {e}")
            raise

    # ═══════════════════════════════════════════════════════════════
    # 异步接口（供AgentLoop异步架构调用）
    # ═══════════════════════════════════════════════════════════════

    async def analyze_current_state_async(self, execution_history: list[dict], current_round: int) -> dict | None:
        """异步版本：分析当前执行状态。内部为纯计算，直接委托同步实现。"""
        return self.analyze_current_state(execution_history, current_round)

    async def get_recent_thoughts_async(self, count: int = 3) -> list[str]:
        """异步版本：获取最近的思考。内部为纯计算，直接委托同步实现。"""
        return self.get_recent_thoughts(count)

    async def get_urgent_insights_async(self, clear: bool = True) -> list[str]:
        """异步版本：获取紧急洞察。内部为纯计算，直接委托同步实现。"""
        return self.get_urgent_insights(clear)

    async def get_life_state_async(self) -> dict[str, Any]:
        """异步版本：获取当前生命状态。内部为纯计算，直接委托同步实现。"""
        return self.get_life_state()


class Consciousness:                               # 定义意识线程单例类（本地单机版）
    """
    意识线程单例 - 本地单机版（向后兼容）

    保留原有单例模式，本地用户无感知。
    内部使用 ConsciousnessService 实现，默认 user_id 为 "default"。

    使用方式（与之前相同）：
        consciousness = Consciousness()
        await consciousness.start()
    """

    _instance = None                               # 类属性：单例实例
    _lock = threading.Lock()                       # 类属性：单例锁

    def __new__(cls, user_id: str = None, intrinsic_motivation=None, world_model=None):   # 重写new方法
        """
        单例模式 - 确保只有一个 Consciousness 实例

        Args:
            user_id: 用户ID（可选，用于兼容服务模式）
            intrinsic_motivation: 内在动机实例（可选）
            world_model: 世界模型实例（可选）
        """
        with cls._lock:                              # 获取单例锁
            if cls._instance is None:                # 如果实例不存在
                cls._instance = super().__new__(cls)   # 创建实例
        return cls._instance                         # 返回实例

    def __init__(self, user_id: str = None, intrinsic_motivation=None, world_model=None):   # 初始化方法
        """
        初始化单例意识线程

        Args:
            user_id: 用户ID（可选，默认为 "default"）
            intrinsic_motivation: 内在动机实例（可选）
            world_model: 世界模型实例（可选）
        """
        if '_initialized' in self.__dict__:        # 如果已初始化（使用__dict__避免触发__getattr__）
            return                                   # 直接返回
        self._initialized = True                     # 标记已初始化

        # 默认 user_id 为 "default"，保持本地单机版行为一致   # 注释：默认用户
        self._user_id = user_id or "default"

        # 内部使用 ConsciousnessService 实现         # 注释：委托实现
        self._service = ConsciousnessService(
            user_id=self._user_id,
            intrinsic_motivation=intrinsic_motivation,
            world_model=world_model
        )

        logger.info(f"意识线程单例初始化完成 [用户: {self._user_id}]")   # 记录日志

    # ========== 代理方法 - 委托给 ConsciousnessService ==========   # 注释：代理方法区域

    async def start(self):                           # 定义异步启动方法（代理）
        """启动意识线程"""                           # 方法文档字符串
        return await self._service.start()           # 委托给服务

    async def stop(self):                            # 定义异步停止方法（代理）
        """停止意识线程"""                           # 方法文档字符串
        return await self._service.stop()            # 委托给服务

    def on_user_input(self):                         # 定义用户输入方法（代理）
        """通知意识线程用户有输入"""                 # 方法文档字符串
        return self._service.on_user_input()         # 委托给服务

    def on_work_start(self):                         # 定义工作开始方法（代理）
        """进入工作模式"""                           # 方法文档字符串
        return self._service.on_work_start()         # 委托给服务

    def on_work_end(self):                           # 定义工作结束方法（代理）
        """退出工作模式"""                           # 方法文档字符串
        return self._service.on_work_end()           # 委托给服务

    def get_internal_state(self) -> dict:            # 定义获取内部状态方法（代理）
        """获取内部状态"""                           # 方法文档字符串
        return self._service.get_internal_state()    # 委托给服务

    async def orchestrate_input(self, user_input: str, context: dict = None) -> dict:
        """输入分流代理 - 判断用户输入是聊天还是任务"""
        return await self._service.orchestrate_input(user_input, context=context)

    async def push_perception(self, perception_data: dict):
        """【重构】代理 push_perception 到 ConsciousnessService"""
        if self._service:
            return await self._service.push_perception(perception_data)
        logger.error("[Consciousness] push_perception 失败: _service 未初始化")

    def on_vision_update(self, tags: list[dict], dominant_app: str = "", layout_summary: str = ""):
        """【修复】代理 on_vision_update 到 ConsciousnessService（修复原有代理链断裂）"""
        if self._service:
            return self._service.on_vision_update(tags, dominant_app, layout_summary)
        logger.error("[Consciousness] on_vision_update 失败: _service 未初始化")

    def adjust_think_interval(self, system_load: dict):   # 定义调整间隔方法（代理）
        """根据系统负载调整思考频率"""                 # 方法文档字符串
        return self._service.adjust_think_interval(system_load)   # 委托给服务

    def get_thinking_stats(self) -> dict:            # 定义获取统计方法（代理）
        """获取思考统计信息"""                       # 方法文档字符串
        return self._service.get_thinking_stats()    # 委托给服务

    def set_think_interval(self, interval: int):     # 定义设置间隔方法（代理）
        """设置思考间隔"""                           # 方法文档字符串
        return self._service.set_think_interval(interval)   # 委托给服务

    def set_think_priority(self, priority: int):     # 定义设置优先级方法（代理）
        """设置思考优先级"""                         # 方法文档字符串
        return self._service.set_think_priority(priority)   # 委托给服务

    def get_think_priority(self) -> int:             # 定义获取优先级方法（代理）
        """获取当前思考优先级"""                     # 方法文档字符串
        return self._service.get_think_priority()    # 委托给服务

    def is_user_input_paused(self) -> bool:          # 定义检查暂停方法（代理）
        """检查是否处于用户输入暂停期"""             # 方法文档字符串
        return self._service.is_user_input_paused()   # 委托给服务

    # ========== 【P0修复】AgentLoop 需要的代理方法 ==========

    def get_recent_thoughts(self, count: int = 3) -> list[str]:
        """获取最近思考"""
        if self._service:
            return self._service.get_recent_thoughts(count)
        logger.error("[Consciousness] get_recent_thoughts 失败: _service 未初始化")
        return []

    def get_urgent_insights(self, clear: bool = True) -> list[str]:
        """获取紧急洞察"""
        if self._service:
            return self._service.get_urgent_insights(clear)
        logger.error("[Consciousness] get_urgent_insights 失败: _service 未初始化")
        return []

    def get_life_state(self) -> dict[str, Any]:
        """获取生命状态"""
        if self._service:
            return self._service.get_life_state()
        logger.error("[Consciousness] get_life_state 失败: _service 未初始化")
        return {"energy": 0.5, "mood": "平静", "stress": 0.0, "curiosity": 0.5, "satisfaction": 0.5}

    def analyze_current_state(self, execution_history: list[dict], current_round: int) -> dict | None:
        """
        分析当前执行状态（简化版）

        Args:
            execution_history: 执行历史记录列表
            current_round: 当前执行轮次

        Returns:
            状态分析结果字典，如果执行历史不足则返回 None

        Raises:
            TypeError: 参数类型错误
            RuntimeError: 分析过程发生异常
        """
        if self._service:
            return self._service.analyze_current_state(execution_history, current_round)
        logger.error("[Consciousness] analyze_current_state 失败: _service 未初始化")
        raise RuntimeError("意识服务未初始化")

    async def analyze_current_state_async(self, execution_history: list[dict], current_round: int) -> dict | None:
        """异步版本：分析当前执行状态"""
        if self._service:
            return await self._service.analyze_current_state_async(execution_history, current_round)
        logger.error("[Consciousness] analyze_current_state_async 失败: _service 未初始化")
        raise RuntimeError("意识服务未初始化")

    async def get_recent_thoughts_async(self, count: int = 3) -> list[str]:
        """异步版本：获取最近的思考"""
        if self._service:
            return await self._service.get_recent_thoughts_async(count)
        logger.error("[Consciousness] get_recent_thoughts_async 失败: _service 未初始化")
        return []

    async def get_urgent_insights_async(self, clear: bool = True) -> list[str]:
        """异步版本：获取紧急洞察"""
        if self._service:
            return await self._service.get_urgent_insights_async(clear)
        logger.error("[Consciousness] get_urgent_insights_async 失败: _service 未初始化")
        return []

    async def get_life_state_async(self) -> dict[str, Any]:
        """异步版本：获取当前生命状态"""
        if self._service:
            return await self._service.get_life_state_async()
        logger.error("[Consciousness] get_life_state_async 失败: _service 未初始化")
        return {"energy": 0.5, "mood": "平静", "stress": 0.0, "curiosity": 0.5, "satisfaction": 0.5}

    def _get_alternative_tool(self, tool: str) -> str | None:
        """获取替代工具建议"""
        if self._service:
            return self._service._get_alternative_tool(tool)
        logger.error("[Consciousness] _get_alternative_tool 失败: _service 未初始化")
        return None

    def _get_mode_available_tools(self) -> set | None:
        """获取当前模式下可用的工具ID集合"""
        if self._service:
            return self._service._get_mode_available_tools()
        logger.error("[Consciousness] _get_mode_available_tools 失败: _service 未初始化")
        return None

    def _is_action_allowed_in_current_mode(self, action_text: str) -> bool:
        """检查 action_text 是否被当前模式允许"""
        if self._service:
            return self._service._is_action_allowed_in_current_mode(action_text)
        logger.error("[Consciousness] _is_action_allowed_in_current_mode 失败: _service 未初始化")
        return True

    @property                                        # 属性装饰器
    def _running(self):                              # 定义_running属性（代理）
        """代理到服务实例的属性"""                   # 属性文档字符串
        return self._service._running                # 委托给服务

    @property                                        # 属性装饰器
    def _think_interval(self):                       # 定义_think_interval属性（代理）
        """代理到服务实例的属性"""                   # 属性文档字符串
        return self._service._think_interval         # 委托给服务

    @property                                        # 属性装饰器
    def intrinsic_motivation(self):                  # 定义intrinsic_motivation属性（代理）
        """代理到服务实例的属性"""                   # 属性文档字符串
        return self._service.intrinsic_motivation    # 委托给服务

    @property                                        # 属性装饰器
    def world_model(self):                           # 定义world_model属性（代理）
        """代理到服务实例的属性"""                   # 属性文档字符串
        return self._service.world_model             # 委托给服务


# ============================================
# 【P0-012 修复】全局 consciousness 延迟初始化机制
# ============================================
# 问题：原代码 consciousness = None 会导致其他模块导入时获取到 None
# 解决：使用线程安全的延迟初始化机制，首次访问时自动初始化

# 私有实例存储（不要直接访问）                     # 注释：私有存储
_consciousness_instance: Consciousness | None = None   # 单例实例
_consciousness_initialized = False                 # 初始化标志
_consciousness_init_lock = threading.RLock()       # 初始化锁

# 多用户实例管理（云端部署支持）                   # 注释：多用户管理
_user_consciousness_services: dict[str, ConsciousnessService] = {}   # 用户服务字典
_user_services_lock = threading.Lock()             # 用户服务锁


class _ConsciousnessProxy:                         # 定义意识代理类（延迟初始化）
    """                                         # 类文档字符串开始
    Consciousness 代理类 - 实现延迟初始化           # 类标题

    此类代理所有对 consciousness 实例的访问，确保在首次访问时   # 功能1
    自动初始化真正的 Consciousness 实例。             # 功能2

    特点：                                        # 特点列表
    1. 线程安全 - 使用锁保护初始化过程               # 特点1
    2. 延迟加载 - 首次访问时才创建实例               # 特点2
    3. 完全代理 - 支持所有属性和方法访问             # 特点3
    4. 向后兼容 - 保持原有使用方式不变               # 特点4
    """                                         # 类文档字符串结束

    def __init__(self):                            # 初始化方法
        self._init_error: Exception | None = None   # 初始化错误

    def _get_instance(self) -> Consciousness:      # 定义获取实例的私有方法
        """                                         # 方法文档字符串开始
        获取或创建 Consciousness 实例（线程安全）     # 方法功能

        Returns:                                    # 返回值说明
            Consciousness: 单例实例                   # 返回类型

        Raises:                                     # 异常说明
            RuntimeError: 如果初始化失败且尚未成功过   # 异常类型
        """                                         # 方法文档字符串结束
        global _consciousness_instance, _consciousness_initialized   # 声明全局变量

        # 双重检查锁定模式（Double-Checked Locking）   # 注释：双重检查锁定
        if not _consciousness_initialized:           # 如果未初始化
            with _consciousness_init_lock:           # 获取初始化锁
                if not _consciousness_initialized:   # 再次检查
                    try:                             # 异常处理
                        _consciousness_instance = Consciousness(user_id="default")   # 创建实例
                        _consciousness_initialized = True   # 标记已初始化
                        logger.info("[ConsciousnessProxy] 全局 consciousness 实例延迟初始化完成")   # 记录日志
                    except Exception as e:           # 初始化失败
                        self._init_error = e         # 保存错误
                        logger.error(f"[ConsciousnessProxy] 初始化失败: {e}", exc_info=True)   # 记录错误
                        raise RuntimeError(f"Consciousness 初始化失败: {e}") from e   # 抛出异常

        return _consciousness_instance               # 返回实例

    # ====== 方法代理 ======                         # 注释：方法代理区域
    async def start(self):                           # 定义异步启动方法（代理）
        """启动意识线程（延迟初始化后）"""           # 方法文档字符串
        return await self._get_instance().start()    # 获取实例并调用

    async def stop(self):                            # 定义异步停止方法（代理）
        """停止意识线程"""                           # 方法文档字符串
        if _consciousness_initialized:               # 如果已初始化
            return await self._get_instance().stop() # 获取实例并调用

    def on_user_input(self):                         # 定义用户输入方法（代理）
        """通知用户输入"""                           # 方法文档字符串
        return self._get_instance().on_user_input()   # 获取实例并调用

    def on_work_start(self):                         # 定义工作开始方法（代理）
        """进入工作模式"""                           # 方法文档字符串
        return self._get_instance().on_work_start()   # 获取实例并调用

    def on_work_end(self):                           # 定义工作结束方法（代理）
        """退出工作模式"""                           # 方法文档字符串
        return self._get_instance().on_work_end()    # 获取实例并调用

    def get_internal_state(self) -> dict:            # 定义获取内部状态方法（代理）
        """获取内部状态"""                           # 方法文档字符串
        return self._get_instance().get_internal_state()   # 获取实例并调用

    async def orchestrate_input(self, user_input: str, context: dict = None) -> dict:
        """输入分流代理 - 判断用户输入是聊天还是任务"""
        return await self._get_instance().orchestrate_input(user_input, context=context)

    def adjust_think_interval(self, system_load: dict):   # 定义调整间隔方法（代理）
        """调整思考间隔"""                           # 方法文档字符串
        return self._get_instance().adjust_think_interval(system_load)   # 获取实例并调用

    def get_thinking_stats(self) -> dict:            # 定义获取统计方法（代理）
        """获取思考统计"""                           # 方法文档字符串
        return self._get_instance().get_thinking_stats()   # 获取实例并调用

    def set_think_interval(self, interval: int):     # 定义设置间隔方法（代理）
        """设置思考间隔"""                           # 方法文档字符串
        return self._get_instance().set_think_interval(interval)   # 获取实例并调用

    def set_think_priority(self, priority: int):     # 定义设置优先级方法（代理）
        """设置思考优先级"""                         # 方法文档字符串
        return self._get_instance().set_think_priority(priority)   # 获取实例并调用

    def get_think_priority(self) -> int:             # 定义获取优先级方法（代理）
        """获取思考优先级"""                         # 方法文档字符串
        return self._get_instance().get_think_priority()   # 获取实例并调用

    def is_user_input_paused(self) -> bool:          # 定义检查暂停方法（代理）
        """检查用户输入暂停"""                       # 方法文档字符串
        return self._get_instance().is_user_input_paused()   # 获取实例并调用

    def analyze_current_state(self, execution_history: list[dict], current_round: int) -> dict | None:
        """分析当前执行状态"""
        return self._get_instance().analyze_current_state(execution_history, current_round)

    def _get_alternative_tool(self, tool: str) -> str | None:
        """获取替代工具建议"""
        return self._get_instance()._get_alternative_tool(tool)

    def _get_mode_available_tools(self) -> set | None:
        """获取当前模式下可用的工具ID集合"""
        return self._get_instance()._get_mode_available_tools()

    def _is_action_allowed_in_current_mode(self, action_text: str) -> bool:
        """检查 action_text 是否被当前模式允许"""
        return self._get_instance()._is_action_allowed_in_current_mode(action_text)

    # ====== 属性代理 ======                         # 注释：属性代理区域
    @property                                        # 属性装饰器
    def _running(self):                              # 定义_running属性（代理）
        return self._get_instance()._running         # 获取实例属性

    @property                                        # 属性装饰器
    def _think_interval(self):                       # 定义_think_interval属性（代理）
        return self._get_instance()._think_interval   # 获取实例属性

    @property                                        # 属性装饰器
    def intrinsic_motivation(self):                  # 定义intrinsic_motivation属性（代理）
        return self._get_instance().intrinsic_motivation   # 获取实例属性

    @property                                        # 属性装饰器
    def world_model(self):                           # 定义world_model属性（代理）
        return self._get_instance().world_model      # 获取实例属性

    # ====== 通用代理支持 ======                     # 注释：通用代理区域
    def __getattr__(self, name: str) -> Any:         # 定义通用属性获取
        """                                         # 方法文档字符串开始
        通用属性代理 - 处理未明确代理的属性             # 方法功能

        Args:                                       # 参数说明
            name: 属性名                              # 参数

        Returns:                                    # 返回值说明
            实际实例的属性值                          # 返回类型

        Raises:
            AttributeError: 如果 Consciousness 初始化失败，确保 hasattr() 正常工作
        """                                         # 方法文档字符串结束
        try:
            return getattr(self._get_instance(), name)   # 获取实例属性
        except RuntimeError as e:
            raise AttributeError(f"Consciousness 初始化失败，无法访问属性 '{name}': {e}") from e

    def __setattr__(self, name: str, value: Any):    # 定义通用属性设置
        """                                         # 方法文档字符串开始
        通用属性设置代理                              # 方法功能

        Args:                                       # 参数说明
            name: 属性名                              # 参数1
            value: 属性值                             # 参数2
        """                                         # 方法文档字符串结束
        if name in ('_init_error',):                 # 如果是内部属性
            super().__setattr__(name, value)         # 直接设置
        else:                                        # 其他属性
            setattr(self._get_instance(), name, value)   # 设置实例属性

    def __call__(self, *args, **kwargs):             # 定义调用支持
        """支持实例被调用的情况"""                   # 方法文档字符串
        return self._get_instance()(*args, **kwargs)   # 调用实例

    def __bool__(self) -> bool:                      # 定义布尔值支持
        """                                         # 方法文档字符串开始
        布尔值检查 - 始终返回 True                    # 方法功能

        解决: if consciousness: 判断问题              # 解决的问题
        """                                         # 方法文档字符串结束
        return True                                  # 始终返回True

    def __repr__(self) -> str:                       # 定义字符串表示
        """字符串表示"""                             # 方法文档字符串
        if _consciousness_initialized:               # 如果已初始化
            return f"<_ConsciousnessProxy: {_consciousness_instance!r}>"
        return "<_ConsciousnessProxy: uninitialized>"

    def __str__(self) -> str:                        # 定义字符串转换
        """字符串转换"""                             # 方法文档字符串
        if _consciousness_initialized:               # 如果已初始化
            return str(_consciousness_instance)
        return "<ConsciousnessProxy (uninitialized)>"


# 创建全局代理实例                                 # 注释：创建全局代理
# 使用方式保持不变: from core.Consciousness import consciousness
consciousness = _ConsciousnessProxy()              # 创建代理实例


def get_consciousness(user_id: str = None):        # 定义获取意识的便捷函数
    """                                         # 函数文档字符串开始
    获取 Consciousness 实例 - 支持多用户隔离       # 函数功能

    【P0-013 修复】根据 user_id 返回对应的独立实例，确保云端部署时   # 修复说明1
    每个用户拥有独立的意识实例，避免状态混淆和数据泄露。   # 修复说明2

    【P0-012 修复】默认用户现在返回延迟初始化的代理对象，避免   # 修复说明3
    模块导入时获取到 None 的问题。                   # 修复说明4

    行为规则：                                     # 行为规则
    1. user_id 为 None 或 "default" 时：返回 Consciousness 代理（向后兼容，延迟初始化）   # 规则1
    2. user_id 为其他值时：返回 ConsciousnessService 独立实例（多用户隔离）   # 规则2

    注意：                                         # 注意事项
    - Consciousness 和 ConsciousnessService 具有相同的公共接口   # 注意1
    - 建议对返回值使用鸭子类型，或根据需要使用 isinstance 检查   # 注意2

    Args:                                       # 参数说明
        user_id: 用户ID（可选，默认为 None 表示使用默认单例）   # 参数

    Returns:                                    # 返回值说明
        Union[_ConsciousnessProxy, ConsciousnessService]:
        - 默认用户返回 _ConsciousnessProxy 代理（自动延迟初始化）
        - 特定用户返回 ConsciousnessService 独立实例

    使用示例：                                     # 使用示例
        # 本地单机版（向后兼容）- 自动延迟初始化       # 示例1
        consciousness = get_consciousness()
        await consciousness.start()  # 首次访问时自动初始化

        # 云端部署 - 多用户隔离                       # 示例2
        user1_service = get_consciousness("user_123")
        user2_service = get_consciousness("user_456")
        # user1_service 和 user2_service 是完全独立的实例

        # 统一接口使用                                # 示例3
        await user1_service.start()
        await user2_service.start()
    """                                         # 函数文档字符串结束
    global _user_consciousness_services            # 声明全局变量

    # 默认用户ID - 返回代理对象（延迟初始化，线程安全）   # 注释：默认用户处理
    if user_id is None or user_id == "default":
        return consciousness  # 返回代理对象，首次访问时自动初始化   # 返回代理

    # 特定用户ID - 使用 ConsciousnessService 独立实例（多用户隔离）   # 注释：特定用户处理
    with _user_services_lock:                      # 获取用户服务锁
        if user_id not in _user_consciousness_services:   # 如果不存在
            _user_consciousness_services[user_id] = ConsciousnessService(user_id=user_id)   # 创建服务
            logger.info(f"[get_consciousness] 创建新用户意识服务: {user_id}")   # 记录日志
        return _user_consciousness_services[user_id]   # 返回服务


async def remove_consciousness(user_id: str) -> bool:    # 定义异步移除意识的便捷函数
    """                                         # 函数文档字符串开始
    移除指定用户的意识实例（用户登出时调用）         # 函数功能

    Args:                                       # 参数说明
        user_id: 用户唯一标识                     # 参数

    Returns:                                    # 返回值说明
        bool: 是否成功移除                        # 返回类型
    """                                         # 函数文档字符串结束
    global _user_consciousness_services            # 声明全局变量

    with _user_services_lock:                      # 获取用户服务锁
        if user_id in _user_consciousness_services:   # 如果存在
            service = _user_consciousness_services.pop(user_id)   # 移除服务
            try:
                await service.stop()  # 异步停止意识服务    # 停止服务
                logger.info(f"[remove_consciousness] 移除用户意识服务: {user_id}")   # 记录日志
                return True                          # 返回成功
            except Exception as e:                   # 异常
                logger.error(f"[remove_consciousness] 停止用户意识服务失败 {user_id}: {e}")   # 记录错误
                return False                         # 返回失败
        return False                                 # 不存在返回失败


def get_active_consciousness_users() -> list[str]:   # 定义获取活跃用户的便捷函数
    """                                         # 函数文档字符串开始
    获取所有活跃的用户意识实例ID列表               # 函数功能

    Returns:                                    # 返回值说明
        List[str]: 用户ID列表（不包括默认用户）   # 返回类型
    """                                         # 函数文档字符串结束
    with _user_services_lock:                      # 获取用户服务锁
        return list(_user_consciousness_services.keys())   # 返回用户ID列表


async def clear_all_user_consciousness() -> None:  # 定义异步清除所有用户意识的便捷函数
    """                                         # 函数文档字符串开始
    清除所有用户意识实例（应用关闭或重置时调用）     # 函数功能

    警告：此操作会停止所有用户的意识线程，仅在系统关闭或维护时使用。   # 警告

    【P0-012 修复】正确处理延迟初始化的代理对象   # 修复说明
    """                                         # 函数文档字符串结束
    global _consciousness_instance, _consciousness_initialized, _user_consciousness_services   # 声明全局变量

    with _user_services_lock:                      # 获取用户服务锁
        # 停止所有用户服务实例                     # 注释：停止用户服务
        for user_id, service in list(_user_consciousness_services.items()):
            try:
                await service.stop()                 # 异步停止服务
                logger.info(f"[clear_all_user_consciousness] 停止用户意识服务: {user_id}")   # 记录日志
            except Exception as e:                   # 异常
                logger.error(f"[clear_all_user_consciousness] 停止失败 {user_id}: {e}")   # 记录错误
        _user_consciousness_services.clear()         # 清空用户服务

        # 停止默认实例（通过代理访问真实实例）       # 注释：停止默认实例
        if _consciousness_initialized and _consciousness_instance is not None:
            try:
                await _consciousness_instance.stop() # 异步停止实例
                logger.info("[clear_all_user_consciousness] 停止默认意识实例")   # 记录日志
            except Exception as e:                   # 异常
                logger.error(f"[clear_all_user_consciousness] 停止默认实例失败: {e}")   # 记录错误
            finally:                                 # 最终处理
                _consciousness_instance = None       # 清空实例
                _consciousness_initialized = False   # 清除初始化标志


class ConsciousnessFactory:                        # 定义意识服务工厂类
    """                                         # 类文档字符串开始
    意识服务工厂 - 管理所有用户的意识服务实例       # 类标题

    使用方式：                                     # 使用示例
        service = ConsciousnessFactory.get_service("user_123")   # 获取服务
        await service.start()

        # 用户登出时清理                           # 清理示例
        await ConsciousnessFactory.remove_service("user_123")
    """                                         # 类文档字符串结束

    _services: dict[str, ConsciousnessService] = {}   # 类属性：服务字典
    _lock = threading.Lock()                       # 类属性：锁

    @classmethod                                   # 类方法装饰器
    def get_service(cls, user_id: str, intrinsic_motivation=None, world_model=None) -> ConsciousnessService:
        """                                         # 方法文档字符串开始
        获取或创建用户的意识服务                     # 方法功能

        Args:                                       # 参数说明
            user_id: 用户唯一标识                     # 参数1
            intrinsic_motivation: 内在动机实例（可选）   # 参数2
            world_model: 世界模型实例（可选）           # 参数3

        Returns:                                    # 返回值说明
            ConsciousnessService: 用户意识服务实例    # 返回类型
        """                                         # 方法文档字符串结束
        with cls._lock:                              # 获取锁
            if user_id not in cls._services:         # 如果不存在
                cls._services[user_id] = ConsciousnessService(   # 创建服务
                    user_id=user_id,
                    intrinsic_motivation=intrinsic_motivation,
                    world_model=world_model
                )
                logger.info(f"[ConsciousnessFactory] 创建用户意识服务: {user_id}")   # 记录日志
            return cls._services[user_id]            # 返回服务

    @classmethod                                   # 类方法装饰器
    async def remove_service(cls, user_id: str):    # 定义异步移除服务的方法
        """                                         # 方法文档字符串开始
        移除用户的意识服务（用户登出时调用）           # 方法功能

        Args:                                       # 参数说明
            user_id: 用户唯一标识                     # 参数
        """                                         # 方法文档字符串结束
        with cls._lock:                              # 获取锁
            if user_id in cls._services:             # 如果存在
                service = cls._services.pop(user_id)   # 移除服务
                await service.stop()  # 异步停止服务          # 停止服务
                logger.info(f"[ConsciousnessFactory] 移除用户意识服务: {user_id}")   # 记录日志

    @classmethod                                   # 类方法装饰器
    def get_all_services(cls) -> dict[str, ConsciousnessService]:   # 定义获取所有服务的方法
        """获取所有服务的副本（用于管理）"""           # 方法文档字符串
        with cls._lock:                              # 获取锁
            return cls._services.copy()              # 返回副本

    @classmethod                                   # 类方法装饰器
    def get_active_user_ids(cls) -> list[str]:      # 定义获取活跃用户ID的方法
        """获取所有活跃用户的ID列表"""                 # 方法文档字符串
        with cls._lock:                              # 获取锁
            return list(cls._services.keys())        # 返回ID列表

    @classmethod                                   # 类方法装饰器
    async def stop_all_services(cls):               # 定义异步停止所有服务的方法
        """停止所有服务（应用关闭时调用）"""           # 方法文档字符串
        with cls._lock:                              # 获取锁
            for user_id, service in list(cls._services.items()):   # 遍历服务
                try:
                    await service.stop()             # 异步停止服务
                    logger.info(f"[ConsciousnessFactory] 停止用户意识服务: {user_id}")   # 记录日志
                except Exception as e:               # 异常
                    logger.error(f"[ConsciousnessFactory] 停止服务失败 {user_id}: {e}")   # 记录错误
            cls._services.clear()                    # 清空服务


def get_consciousness_service(user_id: str) -> ConsciousnessService:   # 定义获取意识服务的便捷函数
    """                                         # 函数文档字符串开始
    获取 ConsciousnessService 实例（按用户）       # 函数功能

    这是 ConsciousnessFactory.get_service 的便捷函数   # 说明

    Args:                                       # 参数说明
        user_id: 用户唯一标识                     # 参数

    Returns:                                    # 返回值说明
        ConsciousnessService 实例                 # 返回类型

    使用示例：                                     # 使用示例
        service = get_consciousness_service("user_123")
        await service.start()
    """                                         # 函数文档字符串结束
    return ConsciousnessFactory.get_service(user_id)   # 调用工厂方法


# ============================================
# 【P0-012 修复】移除模块加载时的立即初始化
# ============================================
# 问题：原代码在这里尝试立即初始化，如果失败会导致 consciousness = None
# 解决：现在使用 _ConsciousnessProxy 代理类，延迟到首次访问时才初始化
#
# 旧代码（已移除）：
#   try:
#       consciousness = Consciousness()
#   except Exception as e:
#       consciousness = None
#
# 新机制：
#   consciousness = _ConsciousnessProxy()  # 已在上面定义
#   首次访问 consciousness.xxx 时自动初始化

# 验证代理对象已创建                                 # 注释：验证
if 'consciousness' not in globals():
    raise RuntimeError("[P0-012] consciousness 代理对象未正确创建")

logger.info("【成功】 Consciousness 延迟初始化机制已启用（P0-012修复）")


# ========== 【P0修复】便捷函数（供AgentLoop调用）==========

def get_consciousness_manager(user_id: str = None):
    """获取意识管理器实例（供AgentLoop调用，兼容函数）"""
    return get_consciousness(user_id)   # 打印成功信息


# =============================================================================
# 【文件总结性注释】
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"意识线程"核心模块，为硅基生命底座提供
# 持续的内部思考流。独立后台线程持续感知环境、更新内部状态、产生想法
# 并可能触发行动。是系统自主意识和自我改进的核心引擎。
#
# 【核心功能效果】
# 1. 持续思考：后台线程定期执行思考循环（默认30秒间隔）
# 2. 环境感知：整合感知数据（窗口、进程、资源等）
# 3. 状态管理：维护内部状态（情绪、目标、历史等）
# 4. 记忆存储：将思考内容存入分层记忆系统
# 5. 深度反思：定期生成自我改进规则
# 6. 任务提案：基于思考内容通过事件总线发送任务提案
# 7. 负载自适应：根据系统负载动态调整思考频率
#
# 【思考优先级机制】
# - 思考优先级：1-10，1最高，10最低
# - 日常模式：正常频率，启用内在动机
# - 专注模式：频率降低50%，跳过弱连接
#
# 【多用户支持】
# - Consciousness:        单例类（本地单机版，向后兼容）
# - ConsciousnessService: 服务类（云端部署，按用户实例化）
# - ConsciousnessFactory: 工厂类（管理多用户实例）
# - _ConsciousnessProxy:  代理类（延迟初始化）
#
# 【关联文件】
# - core/event_bus.py          : 事件驱动架构，发送任务提案
# - core/memory.py             : 存储思考内容到分层记忆
# - core/goal_system.py        : 获取活跃目标，生成每日目标
# - core/self_awareness.py     : 获取生命体征和情绪状态
# - core/intrinsic_motivation.py: 生成探索目标
# - core/weak_connection.py    : 弱连接引擎，间歇性触发任务
# - core/work_mode_manager.py  : 工作模式管理
#
# 【使用场景】
# - 系统启动后启动意识线程，开始自主思考
# - 用户输入时暂停思考，优先响应用户
# - 空闲时自动生成探索任务
# - 定期深度反思，生成自我改进规则
# =============================================================================
