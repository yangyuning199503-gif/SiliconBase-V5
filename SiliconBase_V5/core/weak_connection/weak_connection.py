#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
弱连接引擎 - 事件驱动版（整合V2功能）
职责：感知场景 → 生成建议 → 推送通知（不监听回应）
整合内容：话术轮换、时段感知、增强防重机制
"""  # 文档字符串结束

import json  # 导入JSON模块，用于AI响应解析
import random  # 导入随机模块，用于话术轮换（V2新增）
import threading  # 导入线程模块，用于单例模式
import time  # 导入时间模块，用于冷却计时
from collections import deque  # 从collections导入双端队列（V2新增）
from dataclasses import dataclass  # 从dataclasses导入数据类装饰器
from datetime import datetime  # 从datetime导入datetime类（V2新增）

from core.logger import logger  # 从日志模块导入日志记录器
from core.memory.phase_anchor import get_phase_anchor_manager, save_anchor  # 导入阶段锚点相关函数
from core.mode.work_mode_manager import WorkMode, get_work_mode_manager  # 导入工作模式管理器和枚举


@dataclass  # 数据类装饰器
class WeakProposal:  # 定义弱连接提议数据类，表示AI生成的建议
    """弱连接提议数据结构"""  # 类文档字符串
    anchor_id: str           # 阶段锚点ID（关键！），用于关联上下文
    message: str             # 显示给用户的消息内容
    context_summary: str     # 上下文摘要，用于AI理解场景
    confidence: int          # 置信度 0-10，表示建议的可靠程度
    suggested_action: str    # 建议行动，说明AI建议做什么
    auto_hide: int = 30      # 自动消失时间（秒），默认30秒后自动隐藏


# ═══════════════════════════════════════════════════════════════════════════════
# V2新增：话术轮换器
# ═══════════════════════════════════════════════════════════════════════════════
class MessageRotator:
    """
    话术轮换器
    同一类场景，提供多种表达方式，轮换使用
    """

    def __init__(self):
        # 话术模板库
        self._templates = {
            "excel_open": [
                "{context}。{memory}需要我帮你做个自动化脚本吗？",
                "{context}。{memory}上次好像花了挺长时间，这次要不要我帮忙？",
                "{context}。{memory}我有个想法可以帮你提速，要听听吗？",
                "看你打开了表格。{memory}需要智能助手出手吗？",
            ],
            "code_open": [
                "{context}。{memory}遇到问题了叫我。",
                "{context}。{memory}需要我查查资料吗？",
                "写代码呢？{memory}有我在旁边呢。",
                "{context}。{memory}要不要我帮你测试一下？",
            ],
            "idle_detected": [
                "{context}，正好有空。{memory}需要整理一下吗？",
                "休息一会儿？{memory}顺便让我帮你整理整理？",
                "{context}。{memory}我帮你处理一下？",
            ],
            "multi_app_switch": [
                "{context}。看起来挺忙的，需要我帮忙整合一下这些工作吗？",
                "{context}。在多个任务间切换？我可以帮你自动化一些流程。",
                "{context}。我注意到你在忙多个事，需要智能协助吗？",
            ]
        }

        # 最近使用过的话术（防重复）
        self._recent_variants: deque = deque(maxlen=10)

    def get_message(self, template_key: str, context: str, memory: str) -> str:
        """获取一条话术，确保不重复"""
        templates = self._templates.get(template_key, ["{context}。{memory}"])

        # 过滤掉最近用过的
        available = [t for t in templates if t not in self._recent_variants]
        if not available:
            available = templates

        # 随机选择
        template = random.choice(available)
        self._recent_variants.append(template)

        # 填充变量
        memory_text = f"{memory}，" if memory else ""
        return template.format(context=context, memory=memory_text)


# ═══════════════════════════════════════════════════════════════════════════════
# V2新增：时段管理器
# ═══════════════════════════════════════════════════════════════════════════════
class TimePhaseManager:
    """
    时段管理器
    根据时间调整弱连接行为
    """

    PHASE_MORNING = "morning"      # 早上 6-12点
    PHASE_WORK = "work"            # 工作时间 12-18点
    PHASE_EVENING = "evening"      # 晚上 18-24点（原18-22点，放宽至24点）
    PHASE_NIGHT = "night"          # 深夜 0-5点（原22-6点，收窄至0-5点）

    def get_current_phase(self) -> str:
        """获取当前时段（Fix-Agent-5: 收窄深夜时段，22-24点允许弱连接）"""
        hour = datetime.now().hour
        if 6 <= hour < 12:
            return self.PHASE_MORNING
        elif 12 <= hour < 18:
            return self.PHASE_WORK
        elif 18 <= hour < 24:  # 【放宽】晚上时段扩展到24点
            return self.PHASE_EVENING
        else:  # 0 <= hour < 5
            return self.PHASE_NIGHT

    def should_propose(self, phase: str, task_type: str) -> bool:
        """
        判断某时段是否应该提议某类任务
        规则：
        - 深夜：不说话（除非紧急）
        - 早上：简短提醒
        - 工作时间：效率类提议
        - 晚上：整理类提议
        """
        if phase == self.PHASE_NIGHT:
            return False

        return not (phase == self.PHASE_MORNING and task_type == "heavy_task")

    def get_phase_prefix(self, phase: str) -> str:
        """获取时段前缀"""
        prefixes = {
            self.PHASE_MORNING: "早上好，",
            self.PHASE_WORK: "",
            self.PHASE_EVENING: "晚上好，",
            self.PHASE_NIGHT: "很晚了，"
        }
        return prefixes.get(phase, "")


# ═══════════════════════════════════════════════════════════════════════════════
# 弱连接引擎主类
# ═══════════════════════════════════════════════════════════════════════════════
class WeakConnectionEngine:
    """
    弱连接引擎（整合V2功能）

    核心流程：
    1. 接收感知事件（来自perception层）
    2. 保存到阶段锚点
    3. 检索向量记忆
    4. 生成AI建议（使用话术轮换）
    5. 发送通知事件（前端+语音）

    注意：到此为止，不处理用户回应
    """

    _instance = None  # 单例模式：类变量
    _lock = threading.Lock()  # 单例模式：线程锁

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if '_initialized' in self.__dict__:
            return
        self._initialized = True

        # 【Fix-Agent-5修复】放宽触发条件，让用户能感知到日常模式响应
        # 配置参数调整说明：
        # - cooldown: 冷却期，两次弱连接之间的最小间隔
        # - min_confidence: 最小置信度阈值，低于此值的建议不会推送
        # - max_recent: 防重复历史数量，避免短时间内重复相同上下文的建议

        self._cooldown = 180  # 【放宽】冷却期: 600秒 -> 180秒(3分钟)
        self._last_propose_time = 0  # 上次提议时间，用于冷却计算
        self._min_confidence = 4  # 【放宽】置信度阈值: 6 -> 4

        # 最近处理的上下文（防重复）
        self._recent_contexts = []  # 最近上下文列表
        self._max_recent = 20  # 【放宽】防重历史: 50 -> 20

        # V2新增：子系统
        self._message_rotator = MessageRotator()  # 话术轮换器
        self._time_phase = TimePhaseManager()  # 时段管理器

        # V2新增：已说过的话（更严格的防重复）
        self._said_messages: deque = deque(maxlen=20)  # 【放宽】与_max_recent保持一致

        # 注册事件监听
        self._register_event_handlers()

        logger.info("[WeakConnection] 弱连接引擎初始化完成（整合V2功能）")

    @property
    def config(self):
        """弱连接配置（供 API 路由读取）"""
        return {
            "enabled": True,
            "daily_mode_only": True,
            "cooldown_minutes": self._cooldown // 60,
            "session_min_interval": 300,
            "auto_hide_seconds": 30,
            "min_confidence": self._min_confidence,
            "max_recent": self._max_recent
        }

    def _register_event_handlers(self):
        """注册事件处理器"""
        try:
            from core.sync.event_bus import event_bus

            # 监听窗口变化事件
            event_bus.subscribe("context:window_changed", self._on_window_changed)
            logger.info("[WeakConnection] 已注册窗口变化事件监听")
        except Exception as e:
            logger.warning(f"[WeakConnection] 注册事件监听失败: {e}")

    async def _on_window_changed(self, event):
        """处理窗口变化事件

        【P0修复】event_bus 传入的是 Event 对象（含 .data 属性），
        兼容处理：先提取实际 dict 数据，再按原有逻辑处理。
        """
        # 兼容 Event 对象和 dict
        event_data = event.data if hasattr(event, 'data') else event

        @dataclass
        class WindowContextEvent:
            source: str = "window"
            keywords: list = None
            raw_data: dict = None

            def to_prompt(self) -> str:
                return f"用户正在使用: {self.raw_data.get('title', '未知窗口')}"

        event_wrapped = WindowContextEvent(
            keywords=event_data.get("keywords", []) if isinstance(event_data, dict) else [],
            raw_data=event_data if isinstance(event_data, dict) else {}
        )

        await self.on_context_event(event_wrapped)

        # 【P1新增】向感知总线推送环境变化事件，触发思维线程的感知-思考循环
        try:
            from sensors.system.bus import PerceptionData, bus
            _title = event_data.get("title", "未知窗口") if isinstance(event_data, dict) else "未知窗口"
            _keywords = event_data.get("keywords", []) if isinstance(event_data, dict) else []
            bus.publish(PerceptionData(
                source="weak_connection",
                timestamp=time.time(),
                confidence=0.8,
                content={
                    "event_type": "window_changed",
                    "window_title": _title,
                    "keywords": _keywords,
                    "triggered_think": True
                }
            ))
            logger.debug("[WeakConnection] 已向感知总线推送窗口变化事件，思维线程将响应")
        except Exception as e:
            logger.debug(f"[WeakConnection] 向感知总线推送事件失败: {e}")

    async def on_context_event(self, context_event):
        """
        接收感知层事件 - 唯一入口（异步版本）

        Args:
            context_event: 来自perception层的上下文事件
        """
        try:
            # 1. 检查是否应该处理
            if not self._should_process():
                return

            # 2. 提取上下文信息
            context = self._extract_context(context_event)
            if not context:
                return

            # 3. 检查是否重复上下文
            if self._is_duplicate_context(context):
                logger.debug("[WeakConnection] 重复上下文，跳过")
                return

            # 4. 保存到阶段锚点（关键！）
            anchor_id = await save_anchor(
                phase="perception",
                data={
                    "source": "weak_connection",
                    "context": context,
                    "keywords": getattr(context_event, 'keywords', []),
                    "raw_data": getattr(context_event, 'raw_data', {}),
                    "timestamp": time.time()
                },
                user_id="default",
                session_id=getattr(context_event, 'session_id', '')
            )

            logger.info(f"[WeakConnection] 阶段锚点已保存: {anchor_id}")

            # 5. 检索向量记忆
            memories = await self._recall_memories(context_event)

            # 6. 生成AI建议（V2：使用话术轮换和时段感知）
            proposal = await self._generate_proposal(context, memories, anchor_id, context_event)

            if proposal and proposal.confidence >= self._min_confidence:
                # V2新增：检查是否重复话术
                if proposal.message in self._said_messages:
                    logger.debug("[WeakConnection] 重复话术，跳过")
                    return

                # 7. 发送通知事件
                self._send_proposal_event(proposal)

                # 更新状态
                self._last_propose_time = time.time()
                self._recent_contexts.append(context)
                if len(self._recent_contexts) > self._max_recent:
                    self._recent_contexts.pop(0)

                # V2新增：记录已说的话术
                self._said_messages.append(proposal.message)

                logger.info(f"[WeakConnection] 提议已发送: {proposal.message[:50]}...")

        except Exception as e:
            logger.error(f"[WeakConnection] 处理事件失败: {e}")

    def _should_process(self) -> bool:
        """检查是否应该处理（V2更新：加入时段检查）"""
        # 【新增】调试日志
        logger.debug("[WeakConnection] 检查触发条件...")

        # V2新增：时段检查（深夜不打扰）
        phase = self._time_phase.get_current_phase()
        if phase == TimePhaseManager.PHASE_NIGHT:
            logger.debug("[WeakConnection] 深夜时段，不触发")
            return False

        # 必须是日常模式
        wm = get_work_mode_manager()
        mode = wm.get_current_mode()
        if mode != WorkMode.DAILY:
            logger.debug(f"[WeakConnection] 非日常模式({mode.value})，不触发")
            return False

        # 检查冷却期
        elapsed = time.time() - self._last_propose_time
        if elapsed < self._cooldown:
            remaining = self._cooldown - elapsed
            logger.debug(f"[WeakConnection] 冷却期内，还需{remaining:.0f}秒，不触发")
            return False

        # 用户必须空闲（无当前任务）
        from core.task.task_queue import task_queue
        if task_queue.current_task() is not None:
            logger.debug("[WeakConnection] 用户有进行中任务，不触发")
            return False

        logger.info("[WeakConnection] 通过所有检查，准备触发")
        return True

    def _extract_context(self, context_event) -> str | None:
        """提取上下文描述"""
        if hasattr(context_event, 'to_prompt'):
            return context_event.to_prompt()

        raw = getattr(context_event, 'raw_data', {})
        if 'window_title' in raw:
            return f"用户正在使用: {raw['window_title']}"
        if 'app_name' in raw:
            return f"用户打开了: {raw['app_name']}"

        return "用户正在使用电脑"

    def _is_duplicate_context(self, context: str) -> bool:
        """检查是否重复上下文"""
        return any(self._similarity(context, recent) > 0.7 for recent in self._recent_contexts)

    def _similarity(self, s1: str, s2: str) -> float:
        """简单相似度计算"""
        words1 = set(s1.lower().split())
        words2 = set(s2.lower().split())
        if not words1 or not words2:
            return 0.0
        intersection = words1 & words2
        return len(intersection) / max(len(words1), len(words2))

    async def _recall_memories(self, context_event) -> list:
        """检索相关记忆"""
        try:
            # 【P1-迁移】改用 vector_memory_compat（内部桥接 VectorStore）
            from core.memory.vector_memory_compat import vector_memory

            keywords = getattr(context_event, 'keywords', [])
            if not keywords:
                return []

            query = " ".join(keywords)
            results = await vector_memory.search_similar(query, top_k=2)

            memories = []
            for r in results:
                content = r.get('content', '')
                if content:
                    memories.append(content[:100])

            return memories

        except Exception as e:
            logger.debug(f"[WeakConnection] 检索记忆失败: {e}")
            return []

    async def _generate_proposal(self, context: str, memories: list, anchor_id: str, context_event=None) -> WeakProposal | None:
        """
        生成AI建议（V2更新：使用话术轮换和时段感知）【异步改造】
        """
        try:
            # V2新增：获取当前时段前缀
            phase = self._time_phase.get_current_phase()
            phase_prefix = self._time_phase.get_phase_prefix(phase)

            # V2新增：场景匹配 + 话术轮换
            keywords = getattr(context_event, 'keywords', []) if context_event else []
            memory_text = ""
            if memories:
                memory_text = f"之前你做过{memories[0][:30]}..." if len(memories[0]) > 30 else f"之前你做过{memories[0]}"

            # 场景：Excel/表格
            if any(kw in context for kw in ["报表", "Excel", "表格"]):
                if not self._time_phase.should_propose(phase, "data_task"):
                    return None

                message = self._message_rotator.get_message(
                    "excel_open",
                    phase_prefix + context,
                    memory_text
                )
                return WeakProposal(
                    anchor_id=anchor_id,
                    message=message,
                    context_summary=context,
                    confidence=8 if memories else 6,
                    suggested_action="生成报表脚本",
                    auto_hide=30
                )

            # 场景：代码/编程
            if any(kw in keywords for kw in ["代码", "编程", "IDE", "编辑器"]):
                message = self._message_rotator.get_message(
                    "code_open",
                    phase_prefix + context,
                    memory_text
                )
                return WeakProposal(
                    anchor_id=anchor_id,
                    message=message,
                    context_summary=context,
                    confidence=6,
                    suggested_action="代码辅助",
                    auto_hide=30
                )

            # 场景：空闲检测
            if "空闲" in context:
                if not self._time_phase.should_propose(phase, "organize"):
                    return None

                try:
                    from core.memory.memory_service import get_memory_service
                    ms = await get_memory_service()
                    memories = await ms.query_memories(user_id="default", limit=100)
                    unorganized = len(memories) if memories else 0
                    if unorganized < 3:
                        return None

                    memory_info = f"有{unorganized}条笔记还没整理"
                    message = self._message_rotator.get_message(
                        "idle_detected",
                        phase_prefix + context,
                        memory_info
                    )
                    return WeakProposal(
                        anchor_id=anchor_id,
                        message=message,
                        context_summary=context,
                        confidence=7,
                        suggested_action="整理记忆",
                        auto_hide=30
                    )
                except (ImportError, AttributeError, RuntimeError) as e:
                    logger.error(f"[WeakConnection] 空闲检测失败: {e}", exc_info=True)

            # 场景：多应用切换
            raw_data = getattr(context_event, 'raw_data', {}) if context_event else {}
            if raw_data.get("is_merged"):
                summary = raw_data.get("summary", context)
                message = self._message_rotator.get_message(
                    "multi_app_switch",
                    phase_prefix + summary,
                    ""
                )
                return WeakProposal(
                    anchor_id=anchor_id,
                    message=message,
                    context_summary=context,
                    confidence=5,
                    suggested_action="工作流优化",
                    auto_hide=30
                )

            # 默认：使用原有AI调用方式【异步改造】
            from core.ai.ai_adapter import call_thinker_async

            memory_text = "\n".join([f"- {m}" for m in memories[:2]]) if memories else "无相关记忆"

            prompt = f"""基于以下信息，生成一句给用户的话：

【当前场景】{phase_prefix}{context}
【相关记忆】
{memory_text}

要求：
1. 语气自然亲切，像朋友一样
2. 提及具体记忆增加可信度
3. 给出明确建议
4. 控制在30字以内
5. 格式：JSON {{"message": "...", "confidence": 0-10, "action": "建议行动"}}

输出："""

            response = await call_thinker_async([{"role": "user", "content": prompt}],
                                   temperature=0.7,
                                   max_tokens=200)

            try:
                data = json.loads(response)
                return WeakProposal(
                    anchor_id=anchor_id,
                    message=data.get("message", ""),
                    context_summary=context,
                    confidence=data.get("confidence", 5),
                    suggested_action=data.get("action", "处理任务"),
                    auto_hide=30
                )
            except json.JSONDecodeError:
                return WeakProposal(
                    anchor_id=anchor_id,
                    message=response[:50],
                    context_summary=context,
                    confidence=5,
                    suggested_action="处理任务",
                    auto_hide=30
                )

        except Exception as e:
            logger.debug(f"[WeakConnection] 生成建议失败: {e}")
            return None

    def _send_proposal_event(self, proposal: WeakProposal):
        """发送提议事件"""
        try:
            from core.sync.event_bus import event_bus

            # 发送到UI事件（前端显示气泡）
            event_bus.emit("ui:show_proposal", {
                "anchor_id": proposal.anchor_id,
                "message": proposal.message,
                "action_text": proposal.suggested_action,
                "auto_hide": proposal.auto_hide
            })

            # 发送到语音事件（播报，但不监听回应）
            event_bus.emit("voice:announce", {
                "text": proposal.message,
                "priority": "low",
                "wait_for_response": False
            })

        except Exception as e:
            logger.error(f"[WeakConnection] 发送事件失败: {e}")

    def on_user_input(self):
        """用户输入时调用，暂停弱连接"""
        # 延长冷却时间，避免打扰用户当前工作
        self._last_propose_time = time.time()
        logger.debug("[WeakConnection] 用户输入，暂停弱连接")

    def on_work_start(self):
        """工作开始时调用"""
        # 延长冷却时间到30分钟，让用户专注工作
        self._last_propose_time = time.time() + 1200  # 额外20分钟
        logger.debug("[WeakConnection] 工作开始，延长弱连接冷却期")

    def on_work_end(self):
        """工作结束时调用"""
        # 恢复正常冷却时间
        self._last_propose_time = 0
        logger.debug("[WeakConnection] 工作结束，恢复弱连接")

    async def submit_proposal(
        self,
        message: str,
        context_summary: str = "",
        confidence: int = 50,
        proposal_id: str = None,
    ) -> str:
        """
        接收外部模块（如独白/表达引擎）的提案，直接发送到前端。

        Args:
            message: 显示给用户的消息内容
            context_summary: 上下文摘要
            confidence: 置信度 0-100
            proposal_id: 可选提案ID

        Returns:
            str: 实际使用的 proposal_id
        """
        if proposal_id is None:
            proposal_id = f"external_{int(time.time())}"

        proposal = WeakProposal(
            anchor_id=proposal_id,
            message=message,
            context_summary=context_summary,
            confidence=confidence,
            suggested_action="处理",
            auto_hide=60,
        )
        self._send_proposal_event(proposal)

        # 更新弱连接自身状态，避免与感知层触发的话术重复
        self._last_propose_time = time.time()
        self._said_messages.append(message)

        logger.info(f"[WeakConnection] 外部提案已发送: {message[:50]}...")
        return proposal_id

    def should_run(self) -> bool:
        """【P0-BLOCKER修复】兼容旧版 Consciousness._act_on_thought() 调用"""
        try:
            return self.should_propose_task()
        except Exception:
            return False

    def check_thought(self, thought: str):
        """【P0-BLOCKER修复】兼容旧版 Consciousness._act_on_thought() 调用"""
        from types import SimpleNamespace
        try:
            if self.should_propose_task():
                proposal = self.generate_proposal()
                if proposal:
                    return SimpleNamespace(
                        triggered=True,
                        keyword="思考触发",
                        decision="是",
                        action=proposal
                    )
        except Exception:
            pass
        return SimpleNamespace(
            triggered=False,
            keyword="",
            decision="否",
            action=""
        )

    def should_propose_task(self, perception=None, user_id: str = "default") -> bool:
        """
        【P2断裂点#5】Daily模式下是否应该主动提出建议

        Args:
            perception: 环境感知数据（可选）
            user_id: 用户ID

        Returns:
            bool: 是否应该提出建议
        """
        try:
            # 检查用户配置是否允许弱连接
            if not self._is_weak_connection_enabled(user_id):
                return False

            # 检查时段（深夜不打扰）
            phase = self._time_phase.get_current_phase()
            if phase == TimePhaseManager.PHASE_NIGHT:
                return False

            # 必须是日常模式
            wm = get_work_mode_manager()
            if wm.get_current_mode() != WorkMode.DAILY:
                return False

            # 检查冷却期
            elapsed = time.time() - self._last_propose_time
            if elapsed < self._cooldown:
                return False

            # 检查是否有感知数据
            if perception:
                # 检查触发条件
                triggers = [
                    getattr(perception, 'cpu_percent', 0) > 80,
                    getattr(perception, 'has_new_window', False),
                    getattr(perception, 'idle_time', 0) > 300,  # 5分钟无操作
                    getattr(perception, 'is_work_hour_end', False),
                ]
                return any(triggers)

            # 默认使用系统状态检查
            try:
                import psutil
                if psutil.cpu_percent(interval=0.1) > 80:
                    return True
            except Exception:
                pass

            # 检查是否是工作时段结束
            try:
                from datetime import datetime
                hour = datetime.now().hour
                if hour == 18:  # 下午6点
                    return True
            except Exception:
                pass

            return False

        except Exception as e:
            logger.debug(f"[WeakConnection] 检查触发条件失败: {e}")
            return False

    def _is_weak_connection_enabled(self, user_id: str) -> bool:
        """检查用户是否启用弱连接"""
        try:
            from core.config import config
            return config.get("weak_connection.enabled", True)
        except Exception:
            return True  # 默认启用

    def generate_proposal(self, perception=None, user_id: str = "default") -> str:
        """
        【P2断裂点#5】生成主动建议

        Args:
            perception: 环境感知数据（可选）
            user_id: 用户ID

        Returns:
            str: 建议文本
        """
        try:
            if perception:
                if getattr(perception, 'cpu_percent', 0) > 80:
                    return "CPU使用率较高，是否需要清理后台进程？"
                elif getattr(perception, 'has_new_window', False):
                    return "检测到新窗口打开，是否需要帮助处理？"
                elif getattr(perception, 'idle_time', 0) > 300:
                    return "您已有一段时间未操作，是否需要帮助？"
                elif getattr(perception, 'is_work_hour_end', False):
                    return "工作时间即将结束，是否需要生成今日总结？"

            # 默认检查系统状态
            try:
                import psutil
                cpu = psutil.cpu_percent(interval=0.1)
                if cpu > 80:
                    return f"CPU使用率较高({cpu:.1f}%)，是否需要优化系统？"
            except Exception:
                pass

            # 检查时间
            try:
                from datetime import datetime
                hour = datetime.now().hour
                if hour == 18:
                    return "工作时间即将结束，是否需要生成今日总结？"
            except Exception:
                pass

            return "有什么可以帮您的吗？"

        except Exception as e:
            logger.debug(f"[WeakConnection] 生成建议失败: {e}")
            return "有什么可以帮您的吗？"

    def accept_proposal(self, anchor_id: str, message: str) -> dict:
        """
        用户接受弱连接提议（API路由依赖此方法）

        Args:
            anchor_id: 阶段锚点ID
            message: 提议消息

        Returns:
            dict: 处理结果
        """
        try:
            # 1. 获取锚点数据
            anchor_mgr = get_phase_anchor_manager()
            anchor_data = anchor_mgr.get_anchor(anchor_id)

            if not anchor_data:
                raise ValueError(f"锚点不存在: {anchor_id}")

            # 2. 切换到专注模式
            wm = get_work_mode_manager()
            wm.set_mode(WorkMode.FOCUS)

            # 3. 创建任务
            from core.task.task_queue import Task, task_queue

            task = Task(
                type="user",
                intent={"raw": message, "source": "weak_proposal"},
                session_id="default",
                metadata={
                    "anchor_id": anchor_id,
                    "anchor_context": anchor_data.get("data", {}),
                    "source": "weak_connection"
                }
            )
            # 异步推送到任务队列（保持方法签名同步，避免破坏现有调用方）
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(task_queue.push_async(task))
            except RuntimeError:
                asyncio.new_event_loop().run_until_complete(task_queue.push_async(task))

            logger.info(f"[WeakConnection] 用户接受提议，已创建任务: {task.id}")

            # 通知表达引擎用户点击反馈
            self._notify_expression_feedback(anchor_id, 'clicked')

            return {
                "success": True,
                "task_id": task.id,
                "anchor_id": anchor_id,
                "mode": "FOCUS"
            }

        except Exception as e:
            logger.error(f"[WeakConnection] 接受提议失败: {e}")
            raise

    def dismiss_proposal(self, anchor_id: str) -> dict:
        """
        用户忽略/关闭弱连接提议。

        这是反馈闭环的关键：用户不感兴趣，系统应降低后续打扰频率。
        """
        try:
            logger.info(f"[WeakConnection] 用户忽略提议: {anchor_id}")
            self._notify_expression_feedback(anchor_id, 'ignored')
            return {
                "success": True,
                "anchor_id": anchor_id,
                "action": "dismissed"
            }
        except Exception as e:
            logger.error(f"[WeakConnection] 忽略提议失败: {e}")
            raise

    def timeout_proposal(self, anchor_id: str) -> dict:
        """
        弱连接提议超时未处理。

        同样是反馈闭环的一部分：用户没理它，说明时机或内容不合适。
        """
        try:
            logger.info(f"[WeakConnection] 提议超时: {anchor_id}")
            self._notify_expression_feedback(anchor_id, 'timeout')
            return {
                "success": True,
                "anchor_id": anchor_id,
                "action": "timeout"
            }
        except Exception as e:
            logger.error(f"[WeakConnection] 超时提议处理失败: {e}")
            raise

    def _notify_expression_feedback(self, anchor_id: str, action: str):
        """统一通知表达引擎用户反馈（点击/忽略/超时）。"""
        try:
            from core.consciousness.expression_engine import get_expression_engine
            expr_engine = get_expression_engine()
            expr_engine.on_feedback_sync(anchor_id, action)
        except Exception as e:
            logger.debug(f"[WeakConnection] 通知表达引擎反馈失败: {e}")


# 全局实例
_weak_engine = None

def get_weak_connection_engine() -> WeakConnectionEngine:
    """获取弱连接引擎实例"""
    global _weak_engine
    if _weak_engine is None:
        _weak_engine = WeakConnectionEngine()
    return _weak_engine


async def on_context_event(context_event):
    """便捷函数：处理上下文事件（异步版本）"""
    return await get_weak_connection_engine().on_context_event(context_event)


# ═══════════════════════════════════════════════════════════════════════════════
# 【文件总结】
# ═══════════════════════════════════════════════════════════════════════════════
#
# 【文件角色】
# 本文件(weak_connection.py)是SiliconBase V5核心模块中的弱连接引擎。
# 弱连接是"感知-建议-推送"模式的核心实现，负责在日常模式下感知用户场景，
# 生成AI建议，并通过UI气泡和语音播报推送给用户，但不等待用户回应。
#
# 【V2整合说明】
# 本版本已整合weak_connection_v2.py的所有优点：
# 1. MessageRotator（话术轮换器）：避免重复话术，AI表达更自然
# 2. TimePhaseManager（时段管理器）：深夜不打扰，分时段智能节制
# 3. 增强的防重机制：50条历史（vs 原版的10条）
# 4. 更丰富的场景匹配：Excel、代码、空闲、多应用切换
# 5. 冷却时间调整为10分钟（vs 原版的5分钟）
#
# 【在系统中的位置】
# - 位于: SiliconBase_V5/core/weak_connection.py
# - 上游调用: event_bus（事件总线传递感知事件）
# - 下游依赖: task_queue（用户接受提议时创建任务）
#
# 【关联文件】
# 1. core/event_bus.py - 事件总线，接收context:window_changed等事件
# 2. core/phase_anchor.py - 阶段锚点管理器，保存感知阶段快照
# 3. core/vector_memory.py - 向量记忆，检索相关历史记忆
# 4. core/work_mode_manager.py - 工作模式管理器，检查当前模式
# 5. core/task_queue.py - 任务队列，用户接受提议时创建任务
# 6. core/ai_adapter.py - AI适配器，生成建议消息
#
# 【核心功能】
# 1. 场景感知: 监听窗口变化等事件，感知用户当前场景
# 2. 话术轮换: MessageRotator提供4类场景的多种话术模板，随机选择避免重复
# 3. 时段感知: TimePhaseManager根据时间调整行为，深夜不打扰
# 4. 记忆检索: 基于关键词从向量记忆中检索相关历史
# 5. AI建议生成: 调用轻量级AI生成自然、个性化的建议
# 6. 多模态推送: 通过UI气泡和语音播报推送建议
# 7. 防重复机制: 冷却期、相似度检查、时段过滤、话术去重
# 8. 模式联动: 用户接受提议时切换到专注模式并创建任务
#
# 【达到的效果】
# 1. 主动服务: AI主动感知用户场景并提供帮助建议
# 2. 非侵入式: 弱连接不等待回应，不打扰用户工作流
# 3. 上下文关联: 通过锚点ID关联完整上下文
# 4. 个性化建议: 结合历史记忆生成个性化建议
# 5. 平滑切换: 用户接受建议后平滑切换到专注模式
# 6. 智能节制: 冷却期、重复检测、时段感知避免过度打扰
# 7. 自然表达: 话术轮换使AI建议更自然、更像真人
#
# 【使用示例】
#   # 获取引擎实例
#   engine = get_weak_connection_engine()
#
#   # 处理上下文事件（通常由事件总线调用）
#   engine.on_context_event(context_event)
#
#   # 用户接受提议
#   result = engine.accept_proposal(anchor_id, "帮我处理这个")
#
# ═══════════════════════════════════════════════════════════════════════════════
